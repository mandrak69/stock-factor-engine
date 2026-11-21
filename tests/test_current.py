from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D
import gzip
import hashlib
import json
import statistics

import pytest

from stock_factor_engine.current.calculations import completed_prices, session_factors, fundamental_factors
from stock_factor_engine.current.report import action, csv_write, load_evidence
from stock_factor_engine.models.financials import FinancialFact
from stock_factor_engine.models.market import DailyPrice, CorporateAction
from stock_factor_engine.regime.inputs import completed


AS_OF = datetime(2026, 11, 20, 21, 30, tzinfo=UTC)
SESSION = AS_OF.date()
COMPANY = 'sec:0000000001'
AVAILABLE = AS_OF - timedelta(minutes=10)


def facts():
    balances = {'current_assets': 500, 'current_liabilities': 300, 'cash': 100,
                'net_ppe': 200, 'total_debt': 80, 'long_term_debt_noncurrent': 60}
    durations = {'operating_income': 120, 'revenue': 600, 'operating_cash_flow': 150,
                 'capital_expenditure': 30, 'depreciation_amortization': 30}
    result = [FinancialFact(COMPANY, 'original', concept, D(value), 'USD', date(2025, 12, 31), AVAILABLE)
              for concept, value in balances.items()]
    result += [FinancialFact(COMPANY, 'original', concept, D(value), 'USD', date(2025, 12, 31),
                            AVAILABLE, date(2025, 1, 1)) for concept, value in durations.items()]
    result += [FinancialFact(COMPANY, 'original', 'cover_shares_outstanding', D(100), 'shares',
                             date(2026, 11, 1), AVAILABLE)]
    return result


def calculate(data, **kwargs):
    return fundamental_factors(data, company_id=COMPANY, as_of=AS_OF, session=SESSION, price=D(10), **kwargs)


def test_exact_capital_employed_ev_and_quality_inputs():
    metrics, reasons, audit = calculate(facts())
    assert not reasons
    assert audit['short_term_debt'] == 20
    assert audit['capital_employed'] == 320
    assert audit['market_cap'] == 1000 and audit['enterprise_value'] == 980
    assert metrics['return_on_capital'] == D(120) / 320
    assert metrics['fcf_margin'] == D('.20')
    assert metrics['net_debt_to_ebitda'] == -D(20) / 150
    assert metrics['earnings_yield'] == D(120) / 980
    assert metrics['fcf_yield'] == D('.12')


def test_future_amended_facts_are_not_visible():
    original = facts()
    future = [replace(fact, value=D(999999), filing_accession_number='future',
                      available_at=AS_OF + timedelta(seconds=1)) for fact in original]
    assert calculate(original + future)[:2] == calculate(original)[:2]


def test_availability_boundary_is_inclusive():
    data = [replace(fact, available_at=AS_OF) for fact in facts()]
    assert calculate(data)[0] is not None
    with pytest.raises(ValueError, match='No available operating income'):
        calculate([replace(fact, available_at=AS_OF + timedelta(microseconds=1)) for fact in data])


def test_missing_debt_and_depreciation_are_not_zero_filled():
    data = [fact for fact in facts() if fact.concept not in ('total_debt', 'depreciation_amortization')]
    metrics, reasons, _ = calculate(data)
    assert metrics is None
    assert any('Missing total debt' in reason for reason in reasons)
    assert any('depreciation' in reason for reason in reasons)


def test_negative_capital_employed_is_excluded():
    data = [replace(fact, value=D(900)) if fact.concept == 'current_liabilities' else fact for fact in facts()]
    assert any('Capital Employed is not positive' in reason for reason in calculate(data)[1])


def test_reported_shares_are_split_reconciled_not_weighted_averages():
    split = CorporateAction(date(2026, 11, 10), 'split', D(2))
    _, reasons, audit = calculate(facts(), splits=[split])
    assert not reasons and audit['market_cap'] == 2000
    weighted = [replace(fact, concept='weighted_average_shares_diluted') if fact.unit == 'shares' else fact for fact in facts()]
    assert any('actual shares outstanding' in reason for reason in calculate(weighted)[1])


def bars():
    dates = []
    day = SESSION
    while len(dates) < 253:
        if day.weekday() < 5: dates.append(day)
        day -= timedelta(days=1)
    dates.reverse()
    return [DailyPrice(day, D(10), D(10), D(10), D(10), D(100 + i), 100) for i, day in enumerate(dates)]


def test_momentum_uses_session_offsets_and_risk_is_sample_total_return_volatility():
    prices = bars()
    result = session_factors(prices, SESSION, [bar.trading_date for bar in prices])
    assert result['momentum_12_1'] == D(331) / 100 - 1
    assert result['momentum_6_1'] == D(331) / 226 - 1
    returns = [float(b.adjusted_close / a.adjusted_close - 1) for a, b in zip(prices[-64:], prices[-63:])]
    assert float(result['volatility_63']) == pytest.approx(statistics.stdev(returns) * 252 ** .5)
    assert result['max_drawdown_252'] == 0


def test_dd_uses_only_last_252_prices_and_missing_sessions_fail_closed():
    prices = bars()
    prices[0] = replace(prices[0], adjusted_close=D(10000))
    reference = [bar.trading_date for bar in prices]
    assert session_factors(prices, SESSION, reference)['max_drawdown_252'] == 0
    with pytest.raises(ValueError, match='253 price observations'):
        session_factors(prices[1:], SESSION, reference)
    extended = [replace(prices[0], trading_date=prices[0].trading_date - timedelta(days=1))] + prices
    with pytest.raises(ValueError, match='misaligned'):
        session_factors(extended[:100] + extended[101:], SESSION, reference)


def test_after_close_is_explicit_and_legacy_next_midnight_default_is_preserved():
    prices = bars()
    assert completed(prices, AS_OF)[-1].trading_date < SESSION
    assert completed_prices(prices, AS_OF)[-1].trading_date == SESSION
    assert completed_prices(prices, AS_OF.replace(hour=21, minute=14))[-1].trading_date < SESSION
    assert completed_prices(prices, AS_OF.replace(hour=21, minute=15))[-1].trading_date == SESSION


@pytest.mark.parametrize('rank,held,expected', [(20, False, 'BUY'), (21, False, 'WATCH'),
    (20, True, 'KEEP'), (35, True, 'KEEP'), (36, True, 'SELL'), (None, True, 'SELL')])
def test_actions_follow_user_rules(rank, held, expected):
    assert action(rank, held) == expected


def test_csv_preserves_missing_values_and_real_zero(tmp_path):
    import csv
    path = tmp_path / 'test.csv'
    csv_write(path, [{'Ticker': 'A', 'Rank Change': 0}, {'Ticker': 'B', 'Rank Change': None}], ('Ticker', 'Rank Change'))
    with path.open(encoding='utf-8-sig') as stream: rows = list(csv.DictReader(stream))
    assert rows[0]['Rank Change'] == '0' and rows[1]['Rank Change'] == ''


def test_evidence_hash_is_verified(tmp_path):
    folder = tmp_path / 'raw'
    folder.mkdir()
    content = b'{}'
    (folder / 'test.json.gz').write_bytes(gzip.compress(content))
    (folder / 'test.meta.json').write_text(json.dumps({'sha256': hashlib.sha256(content).hexdigest()}))
    assert load_evidence(tmp_path, 'test')[0] == content
    (folder / 'test.json.gz').write_bytes(gzip.compress(b'changed'))
    with pytest.raises(ValueError, match='SHA-256'):
        load_evidence(tmp_path, 'test')



def test_source_store_does_not_send_sec_contact_to_yahoo(tmp_path, monkeypatch):
    from stock_factor_engine.current.sources import EvidenceStore
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self): return b'{}'
    def open_request(request, timeout):
        assert '@' not in request.get_header('User-agent')
        return Response()
    monkeypatch.setattr('stock_factor_engine.current.sources.urlopen', open_request)
    store = EvidenceStore(tmp_path, 'synthetic-test-contact@example.test')
    assert store.get('test', 'https://query1.finance.yahoo.com/v8/finance/chart/SPY', 'yahoo')[0] == {}


def test_source_store_rejects_contact_egress_to_other_hosts(tmp_path):
    from stock_factor_engine.current.sources import EvidenceStore
    store = EvidenceStore(tmp_path, 'synthetic-test-contact@example.test')
    with pytest.raises(ValueError, match='configured HTTPS host'):
        store.get('test', 'https://unrelated.example.test/data', 'sec')



def test_price_filter_and_capitalization_undo_splits_after_historical_session():
    from stock_factor_engine.current.calculations import as_traded_price
    bar = bars()[-1]
    post_decision_split = CorporateAction(SESSION + timedelta(days=3), 'split', D(2))
    past_split = CorporateAction(SESSION - timedelta(days=3), 'split', D(3))
    assert as_traded_price(bar, [post_decision_split, past_split]) == D(20)
