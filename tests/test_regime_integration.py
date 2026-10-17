from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D
import json

import pytest

from stock_factor_engine.models.market import DailyPrice
from stock_factor_engine.providers.market.ingestion import ingest_market, replay_response
from stock_factor_engine.providers.market.yahoo import parse, fetch
from stock_factor_engine.regime.inputs import Membership, breadth, regime_inputs
from stock_factor_engine.regime.report import narrow_market, regime_report
from stock_factor_engine.regime.__main__ import main
from stock_factor_engine.storage import connect_database
from stock_factor_engine.universe.registry import IDENTITIES, MARKET_SYMBOLS, selected_symbols


def history(end=120, raw=999):
    dates = []
    day = date(2024, 1, 2)
    while len(dates) < 200:
        if day.weekday() < 5:
            dates.append(day)
        day += timedelta(days=1)
    return [DailyPrice(day, D(raw), D(raw), D(raw), D(raw), D(end if i == 199 else 100), 0)
            for i, day in enumerate(dates)]


SPY = history()
SESSION = SPY[-1].trading_date
AS_OF = datetime.combine(SESSION + timedelta(days=1), datetime.min.time(), UTC) + timedelta(hours=18)
DATES = [bar.trading_date for bar in SPY]


def series():
    return {'SPY': SPY, 'RSP': history(110), 'HYG': history(108), 'LQD': history(104), '^VIX': history(999, raw=19)}


def members():
    return Membership(SESSION, frozenset({'old:A', 'old:B'}), 'verified fixture: exact-date history', True)


def test_ratios_use_adjusted_close_identical_63_sessions_and_ratio_return():
    session, result = regime_inputs(series(), as_of=AS_OF)
    assert session == SESSION
    assert result['rsp_spy'].value == D(110) / 120 - 1
    assert result['hyg_lqd'].value == D(108) / 104 - 1
    assert result['rsp_spy'].period_start == DATES[-64]
    assert result['rsp_spy'].observations == 64


@pytest.mark.parametrize('symbol,key', [('RSP', 'rsp_spy'), ('SPY', 'rsp_spy'), ('HYG', 'hyg_lqd'), ('LQD', 'hyg_lqd')])
def test_missing_internal_session_is_not_hidden_by_intersection(symbol, key):
    data = series()
    data[symbol] = data[symbol][:170] + data[symbol][171:]
    _, result = regime_inputs(data, as_of=AS_OF)
    assert result[key].value is None


def test_spy_200dma_and_vix_raw_close():
    _, result = regime_inputs(series(), as_of=AS_OF)
    assert result['spy_trend'].value == D(120) / (D(199 * 100 + 120) / 200) - 1
    assert result['vix_spot'].value == 19
    assert result['vix_spot'].unit == 'index_points'


@pytest.mark.parametrize('membership', [None, replace(members(), session=SESSION - timedelta(days=1)),
    replace(members(), complete=False), replace(members(), source=''), replace(members(), security_ids=frozenset())])
def test_breadth_requires_complete_exact_date_membership(membership):
    result = breadth({'old:A': SPY, 'old:B': SPY}, membership, SESSION, DATES)
    assert result.value is None and result.payload()['status'] == 'unavailable'


@pytest.mark.parametrize('bad', [[], SPY[1:], SPY[:-1], SPY[:170] + SPY[171:]])
def test_one_incomplete_member_closes_entire_breadth(bad):
    result = breadth({'old:A': SPY, 'old:B': bad}, members(), SESSION, DATES)
    assert result.value is None
    assert result.details['missing'] == ['old:B']


def test_breadth_does_not_include_current_nonmembers_and_narrow_condition():
    membership = replace(members(), security_ids=frozenset({'old:A', 'old:B', 'old:C'}))
    _, inputs = regime_inputs(series(), as_of=AS_OF, membership=membership,
        member_prices={'old:A': SPY, 'old:B': history(90), 'old:C': history(100), 'today:NEW': SPY})
    assert inputs['breadth'].value == D(1) / 3
    assert narrow_market(inputs) is True
    _, missing = regime_inputs(series(), as_of=AS_OF)
    assert narrow_market(missing) is None


def test_current_session_and_future_prices_are_ignored():
    data = series()
    tomorrow = AS_OF.date()
    data = {key: bars + [replace(bars[-1], trading_date=tomorrow, adjusted_close=D(5000))]
            for key, bars in data.items()}
    assert regime_inputs(data, as_of=AS_OF)[1] == regime_inputs(series(), as_of=AS_OF)[1]


def yahoo_payload(symbol):
    identity = IDENTITIES[symbol]
    epochs = [int(datetime.combine(day, datetime.min.time(), UTC).timestamp()) + 18 * 3600 for day in DATES]
    quotes = {name: [19] * 200 for name in ('open', 'high', 'low', 'close')}
    quotes['volume'] = [0] * 200
    indicators = {'quote': [quotes]}
    if symbol != '^VIX':
        indicators['adjclose'] = [{'adjclose': [19] * 200}]
    return {'chart': {'error': None, 'result': [{'meta': {'symbol': symbol, 'currency': 'USD',
        'instrumentType': identity['instrument_type'],
        'exchangeTimezoneName': identity.get('exchange_timezone', 'America/New_York')},
        'timestamp': epochs, 'indicators': indicators}]}}


@pytest.mark.parametrize('symbol', MARKET_SYMBOLS)
def test_market_identities_ingest_without_sec_and_replay(tmp_path, symbol):
    db = connect_database(tmp_path / 'engine.sqlite')
    try:
        content = json.dumps(yahoo_payload(symbol)).encode()
        result = ingest_market(db, tmp_path, symbol=symbol, response=(content, AS_OF, 'fixture://market'))
        assert result['bars_in_snapshot'] == 200
        replay = replay_response(db, tmp_path, result['snapshot_id'])
        assert ingest_market(db, tmp_path, symbol=symbol, response=replay)['new_bars'] == 0
        with pytest.raises(ValueError, match='company equities'):
            selected_symbols([symbol])
    finally:
        db.close()


def test_vix_chicago_dates_without_adjclose_and_timezone_validation():
    data = yahoo_payload('^VIX')
    result = data['chart']['result'][0]
    # 00:30 UTC is still the previous Chicago calendar day.
    result['timestamp'][0] = int(datetime(2024, 1, 3, 0, 30, tzinfo=UTC).timestamp())
    bars, _, rejected, _ = parse(json.dumps(data).encode(), '^VIX', AS_OF)
    assert bars[0].trading_date == date(2024, 1, 2)
    assert bars[0].adjusted_close == bars[0].close == 19 and not rejected
    result['meta']['exchangeTimezoneName'] = 'America/New_York'
    with pytest.raises(ValueError, match='timezone'):
        parse(json.dumps(data).encode(), '^VIX', AS_OF)


def test_vix_fetch_symbol_accepted_without_network(monkeypatch):
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self): return b'fixture'
    def urlopen(request, timeout):
        assert '/chart/^VIX?' in request.full_url
        return Response()
    monkeypatch.setattr('stock_factor_engine.providers.market.yahoo.urlopen', urlopen)
    assert fetch('^VIX')[0] == b'fixture'


def test_report_and_cli_fail_closed_without_membership(tmp_path, capsys):
    path = tmp_path / 'engine.sqlite'
    db = connect_database(path)
    try:
        for symbol in MARKET_SYMBOLS:
            ingest_market(db, tmp_path, symbol=symbol,
                          response=(json.dumps(yahoo_payload(symbol)).encode(), AS_OF, 'fixture://market'))
        report = regime_report(db, as_of=AS_OF)
        assert report['missing_inputs'] == ['breadth']
        assert report['status'] == 'unavailable' and report['equity_exposure'] is None
    finally:
        db.close()
    assert main(['report', '--database', str(path), '--as-of', AS_OF.isoformat()]) == 0
    assert json.loads(capsys.readouterr().out)['inputs']['breadth']['status'] == 'unavailable'


def test_reports_do_not_use_future_snapshots(tmp_path):
    db = connect_database(tmp_path / 'engine.sqlite')
    try:
        ingest_market(db, tmp_path, symbol='SPY', response=(json.dumps(yahoo_payload('SPY')).encode(), AS_OF, 'fixture://market'))
        report = regime_report(db, as_of=AS_OF - timedelta(days=1))
        assert all(value['status'] == 'unavailable' for value in report['inputs'].values())
    finally:
        db.close()


def test_complete_membership_report_and_cli_issue_real_decision(tmp_path, capsys):
    from stock_factor_engine.regime.membership import JsonMembershipProvider

    database = tmp_path / 'engine.sqlite'
    db = connect_database(database)
    try:
        for symbol in MARKET_SYMBOLS:
            ingest_market(db, tmp_path, symbol=symbol,
                          response=(json.dumps(yahoo_payload(symbol)).encode(), AS_OF, 'fixture://market'))
        # Test-only member universe; the production adapter must receive the full verified history.
        security_id = IDENTITIES['SPY']['security_id']
        membership_path = tmp_path / 'members.json'
        payload = {'session': str(SESSION), 'source': 'verified test fixture only',
                   'complete': True, 'security_ids': [security_id]}
        membership_path.write_text(json.dumps(payload), encoding='utf-8')
        provider = JsonMembershipProvider(membership_path)
        report = regime_report(db, as_of=AS_OF, membership_provider=provider)
        assert report['status'] == 'available'
        assert report['regime'] == 'RISK_OFF' and report['equity_exposure'] == D('.25')
        assert report['missing_inputs'] == []
        assert security_id in report['member_snapshots']
        assert report['membership_source'] == payload['source']
        assert main(['report', '--database', str(database), '--as-of', AS_OF.isoformat(),
                     '--constituents-json', str(membership_path)]) == 0
        assert json.loads(capsys.readouterr().out)['status'] == 'available'
        payload['session'] = str(SESSION - timedelta(days=1))
        membership_path.write_text(json.dumps(payload), encoding='utf-8')
        stale = regime_report(db, as_of=AS_OF, membership_provider=JsonMembershipProvider(membership_path))
        assert stale['status'] == 'unavailable' and stale['missing_inputs'] == ['breadth']
    finally:
        db.close()


@pytest.mark.parametrize('change', [ {'complete': False}, {'complete': 'true'},
    {'security_ids': []}, {'security_ids': ['a', 'a']}, {'source': ''}])
def test_json_membership_rejects_unverified_partial_or_duplicate_lists(tmp_path, change):
    from stock_factor_engine.regime.membership import JsonMembershipProvider

    payload = {'session': str(SESSION), 'source': 'verified test source', 'complete': True, 'security_ids': ['a']}
    payload.update(change)
    path = tmp_path / 'members.json'
    path.write_text(json.dumps(payload), encoding='utf-8')
    with pytest.raises(ValueError):
        JsonMembershipProvider(path)


def test_vx_cli_requires_contract_metadata_and_rejects_wrong_session(tmp_path, capsys):
    db_path = tmp_path / 'engine.sqlite'
    db = connect_database(db_path)
    try:
        for symbol in MARKET_SYMBOLS:
            ingest_market(db, tmp_path, symbol=symbol,
                          response=(json.dumps(yahoo_payload(symbol)).encode(), AS_OF, 'fixture://market'))
    finally:
        db.close()
    base = ['report', '--database', str(db_path), '--as-of', AS_OF.isoformat()]
    with pytest.raises(SystemExit) as error:
        main(base + ['--vix-front-month', '18'])
    assert error.value.code == 2
    assert 'requires price, session, contract, expiry and source' in capsys.readouterr().err
    args = ['--vix-front-month', '18', '--vix-session', str(SESSION),
            '--vix-contract', 'VX test contract', '--vix-expiry', str(SESSION + timedelta(days=20)),
            '--vix-source', 'test-only verified source']
    assert main(base + args) == 0
    report = json.loads(capsys.readouterr().out)
    assert report['vix_front_month_status'] == 'available'
    assert report['vix_front_month']['contract'] == 'VX test contract'
    args[3] = str(SESSION - timedelta(days=1))
    with pytest.raises(SystemExit) as error:
        main(base + args)
    assert error.value.code == 2
    assert 'exact regime session' in capsys.readouterr().err


def test_naive_asof_rejected_even_without_series():
    with pytest.raises(ValueError, match='timezone-aware'):
        regime_inputs({}, as_of=datetime(2024, 10, 7))


def test_json_membership_requires_object(tmp_path):
    from stock_factor_engine.regime.membership import JsonMembershipProvider

    path = tmp_path / 'members.json'
    path.write_text('[]', encoding='utf-8')
    with pytest.raises(ValueError, match='must be an object'):
        JsonMembershipProvider(path)
