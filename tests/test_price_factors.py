from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import json
import math
import statistics

import pytest

from stock_factor_engine.models.market import DailyPrice
from stock_factor_engine.factors.prices import benchmark_comparison, price_factors
from stock_factor_engine.providers.market.ingestion import ingest_market, replay_response
from stock_factor_engine.storage import connect_database


AS_OF = datetime(2025, 10, 2, 18, tzinfo=UTC)


def history(price=lambda i, day: Decimal(100)):
    bars = []
    day = date(2024, 1, 1)
    while day <= date(2025, 10, 1):
        if day.weekday() < 5:
            value = Decimal(price(len(bars), day))
            bars.append(DailyPrice(day, value, value, value, value, value, 1000))
        day += timedelta(days=1)
    return bars


def test_constant_prices_produce_zero_factors():
    result = price_factors(history(), as_of=AS_OF)
    assert all(item.value == 0 for item in result.values())
    assert result['volatility_252'].observations == 252
    assert result['return_252'].observations == 253


def test_momentum_omits_the_most_recent_completed_month():
    bars = history(lambda i, day: 1000 if day >= date(2025, 9, 1) else 100)
    result = price_factors(bars, as_of=AS_OF)
    momentum = result['momentum_12_1']
    assert momentum.value == 0
    assert momentum.period_start == date(2024, 9, 30)
    assert momentum.period_end == date(2025, 8, 29)
    assert result['return_252'].value == 9


def test_sample_volatility_and_running_peak_drawdown():
    bars = history(lambda i, day: 110 if i % 2 else 100)
    result = price_factors(bars, as_of=AS_OF)
    window = bars[-253:]
    reference_returns = [float(b.adjusted_close / a.adjusted_close - 1) for a, b in zip(window, window[1:])]
    expected = statistics.stdev(reference_returns) * math.sqrt(252)
    assert float(result['volatility_252'].value) == pytest.approx(expected, rel=1e-12)
    assert float(result['max_drawdown_252'].value) == pytest.approx(-1 / 11)
    assert result['return_252'].value == 0


def test_current_session_prices_are_invisible():
    bars = history()
    bars.append(DailyPrice(date(2025, 10, 2), *(Decimal(999) for _ in range(5)), 1))
    assert all(item.value == 0 for item in price_factors(bars, as_of=AS_OF).values())


def test_unavailable_history_and_stale_data():
    short = price_factors(history()[-50:], as_of=AS_OF)
    assert all(item.value is None for item in short.values())
    stale = price_factors(history()[:-20], as_of=AS_OF)
    assert all(item.value is None for item in stale.values())


def test_long_gaps_are_not_silently_accepted():
    bars = [bar for bar in history() if not date(2025, 2, 1) <= bar.trading_date <= date(2025, 2, 20)]
    result = price_factors(bars, as_of=AS_OF)
    assert all(item.value is None for item in result.values())


def test_benchmark_alignment_detects_one_missing_session():
    asset, benchmark = history(), history()
    benchmark.pop(-60)
    _, _, excess = benchmark_comparison(asset, benchmark, as_of=AS_OF)
    assert all(item.value is None for item in excess.values())
    assert 'dates differ' in excess['momentum_12_1_excess'].reason


def test_same_series_has_zero_excess_and_no_future_dates():
    bars = history()
    _, _, excess = benchmark_comparison(bars, bars, as_of=AS_OF)
    assert all(item.value == 0 for item in excess.values())


def test_duplicate_and_naive_inputs_are_rejected():
    with pytest.raises(ValueError, match='Duplicate'):
        price_factors(history() + [history()[-1]], as_of=AS_OF)
    with pytest.raises(ValueError, match='chronological'):
        price_factors(list(reversed(history())), as_of=AS_OF)
    with pytest.raises(ValueError, match='timezone-aware'):
        price_factors(history(), as_of=datetime(2025, 10, 2))


def test_spy_import_identity_and_replay(tmp_path, monkeypatch, capsys):
    connection = connect_database(tmp_path / 'engine.sqlite')
    epochs = [1727789400, 1727875800]
    payload = {'chart': {'error': None, 'result': [{
        'meta': {'symbol': 'SPY', 'currency': 'USD', 'instrumentType': 'ETF',
                 'exchangeTimezoneName': 'America/New_York'},
        'timestamp': epochs,
        'indicators': {'quote': [{name: [100, 100] for name in ('open', 'high', 'low', 'close', 'volume')}],
                       'adjclose': [{'adjclose': [100, 100]}]},
    }]}}
    response = (json.dumps(payload).encode(), AS_OF, 'https://query1.finance.yahoo.com/v8/finance/chart/SPY')
    try:
        first = ingest_market(connection, tmp_path, symbol='SPY', response=response)
        assert first['security_id'] == 'sec:0000884394:fund'
        assert tuple(connection.execute('SELECT company_id, security_type, exchange FROM securities').fetchone()) == (
            'sec:0000884394', 'etf', 'NYSE_ARCA')
        repeated = ingest_market(connection, tmp_path, symbol='SPY',
                                 response=replay_response(connection, tmp_path, first['snapshot_id']))
        assert repeated['new_bars'] == 0
        connection.execute('INSERT INTO companies (id, legal_name, cik) VALUES (?, ?, ?)',
                           ('sec:0000789019', 'Microsoft Corporation', '0000789019'))
        connection.commit()
        with pytest.raises(ValueError, match='configured'):
            ingest_market(connection, tmp_path, symbol='MSFT', response=response)
        payload['chart']['result'][0]['meta'].update(symbol='MSFT', instrumentType='EQUITY')
        microsoft = ingest_market(connection, tmp_path, symbol='MSFT',
                                  response=(json.dumps(payload).encode(), AS_OF, response[2]))
        from stock_factor_engine.factors.__main__ import main
        import sys
        arguments = ['factors', '--database', str(tmp_path / 'engine.sqlite'), '--as-of', AS_OF.isoformat()]
        monkeypatch.setattr(sys, 'argv', arguments)
        main()
        report = json.loads(capsys.readouterr().out)
        assert all(snapshot['known_at_as_of'] for snapshot in report['snapshots'].values())
        assert report['asset_factors']['volatility_252']['status'] == 'unavailable'
        earlier = arguments[:-1] + ['2025-10-01T18:00:00+00:00']
        monkeypatch.setattr(sys, 'argv', earlier)
        with pytest.raises(SystemExit) as error:
            main()
        assert error.value.code == 2
        monkeypatch.setattr(sys, 'argv', earlier + ['--asset-snapshot', microsoft['snapshot_id'],
                                                   '--benchmark-snapshot', first['snapshot_id']])
        main()
        report = json.loads(capsys.readouterr().out)
        assert not any(snapshot['known_at_as_of'] for snapshot in report['snapshots'].values())
    finally:
        connection.close()
