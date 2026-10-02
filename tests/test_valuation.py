from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from stock_factor_engine.fundamentals.valuation import valuation_metrics
from stock_factor_engine.models.financials import FinancialFact
from stock_factor_engine.models.market import DailyPrice
from stock_factor_engine.providers.market.yahoo import PRICE_BASIS

AS_OF = datetime(2024, 3, 1, 18, tzinfo=UTC)
PRICE_DATE = date(2024, 2, 29)


def fact(concept, value, start=None, end='2023-12-31', unit='USD', available=None):
    return FinancialFact('c', concept, concept, Decimal(str(value)), unit, date.fromisoformat(end),
                         available or datetime(2024, 2, 1, tzinfo=UTC),
                         date.fromisoformat(start) if start else None, 'us-gaap')


def data():
    return [fact(concept, value, '2023-01-01') for concept, value in
            [('revenue', 1000), ('operating_cash_flow', 100), ('capital_expenditure', 20)]] + [
        fact('eps_diluted', 2, '2023-01-01', unit='USD/shares'),
        fact('reported_shares_outstanding', 100, unit='shares'),
        fact('cover_shares_outstanding', 90, end='2024-01-20', unit='shares'),
        fact('weighted_average_shares_diluted', 999, '2023-01-01', unit='shares')]


def bar(on_date=PRICE_DATE, close=10, adjusted=1):
    return DailyPrice(on_date, *(Decimal(close) for _ in range(4)), Decimal(adjusted), 100)


def run(facts=None, bars=None, **kwargs):
    return valuation_metrics(data() if facts is None else facts, [bar()] if bars is None else bars,
                             company_id='c', as_of=AS_OF, price_basis=PRICE_BASIS,
                             snapshot_last_date=kwargs.pop('snapshot_last_date', PRICE_DATE), **kwargs)[1]


def test_formulas_use_provider_close_and_outstanding_not_adjusted_or_weighted_shares():
    results = run()
    assert results['market_cap_estimate'].value == 900
    assert results['price_to_sales'].value == Decimal('0.9')
    assert results['pe_diluted_annual'].value == 5
    assert abs(results['fcf_yield'].value - Decimal(80) / 900) < Decimal('1e-27')
    assert results['shares_outstanding'].inputs['observation_date'] == date(2024, 1, 20)
    assert results['market_cap_estimate'].assumptions


def test_future_information_and_current_session_are_excluded():
    observations = data() + [fact('cover_shares_outstanding', 1, end='2024-02-20', unit='shares',
                                 available=datetime(2024, 3, 2, tzinfo=UTC)),
                             fact('reported_shares_outstanding', 5, end='2024-03-01', unit='shares')]
    results = run(observations, [bar(), bar(date(2024, 3, 1), 999)],
                  snapshot_last_date=date(2024, 3, 1))
    assert results['market_cap_estimate'].value == 900
    assert results['price'].inputs['price_date'] == PRICE_DATE


def test_loss_eps_blocks_pe_but_negative_fcf_yield_is_preserved():
    observations = [item for item in data() if item.concept not in ('eps_diluted', 'operating_cash_flow')]
    observations += [fact('eps_diluted', -2, '2023-01-01', unit='USD/shares'),
                     fact('operating_cash_flow', 10, '2023-01-01')]
    results = run(observations)
    assert results['pe_diluted_annual'].value is None
    assert results['fcf_yield'].value < 0
    assert results['price_to_sales'].value == Decimal('0.9')


def test_no_quarterly_eps_sum_or_weighted_share_fallback():
    observations = [item for item in data() if item.concept not in
                    ('eps_diluted', 'reported_shares_outstanding', 'cover_shares_outstanding')]
    observations += [fact('eps_diluted', 2, '2023-10-01', unit='USD/shares')]
    results = run(observations)
    assert results['pe_diluted_annual'].value is None
    assert results['market_cap_estimate'].value is None
    assert results['revenue_ttm'].value == 1000


@pytest.mark.parametrize('split_day', [date(2024, 2, 10), date(2024, 3, 20)])
def test_split_between_observation_and_snapshot_horizon_blocks_including_future_split(split_day):
    results = run(split_dates=[split_day], snapshot_last_date=date(2024, 4, 1))
    assert results['market_cap_estimate'].value is None
    assert results['pe_diluted_annual'].value is None
    assert 'Split' in results['shares_outstanding'].reason


def test_split_before_share_date_can_still_block_eps_independently():
    results = run(split_dates=[date(2024, 1, 1)])
    assert results['market_cap_estimate'].value == 900
    assert results['pe_diluted_annual'].value is None


def test_stale_price_blocks_all_valuations():
    results = run(bars=[bar(date(2024, 2, 1))])
    assert all(results[name].value is None for name in
               ('market_cap_estimate', 'pe_diluted_annual', 'price_to_sales', 'fcf_yield'))


def test_conflicting_share_counts_are_unavailable():
    results = run(data() + [fact('reported_shares_outstanding', 91, end='2024-01-20', unit='shares')])
    assert results['market_cap_estimate'].value is None
    assert 'Conflicting' in results['shares_outstanding'].reason
    assert results['pe_diluted_annual'].value == 5


def test_missing_financials_do_not_block_market_cap():
    results = run([item for item in data() if item.unit == 'shares'])
    assert results['market_cap_estimate'].value == 900
    assert results['price_to_sales'].value is None
    assert results['fcf_yield'].value is None


def test_stale_shares_do_not_block_pe_and_stale_financials_do_not_block_market_cap():
    observations = [item for item in data() if item.concept not in
                    ('reported_shares_outstanding', 'cover_shares_outstanding')]
    observations += [fact('reported_shares_outstanding', 90, end='2023-09-01', unit='shares')]
    results = run(observations)
    assert results['market_cap_estimate'].value is None
    assert '120 days' in results['shares_outstanding'].reason
    assert results['pe_diluted_annual'].value == 5
    observations = [item for item in data() if item.unit == 'shares']
    observations += [fact('revenue', 1000, '2022-07-01', end='2023-06-30')]
    results = run(observations)
    assert results['market_cap_estimate'].value == 900
    assert results['price_to_sales'].value is None
    assert '180 days' in results['revenue_ttm'].reason


def test_invalid_basis_dates_and_naive_asof_are_rejected():
    with pytest.raises(ValueError, match='unique chronological'):
        run(bars=[bar(), bar()])
    with pytest.raises(ValueError, match='after the price'):
        run(period_end=date(2024, 3, 1))
    with pytest.raises(ValueError, match='Unsupported'):
        valuation_metrics(data(), [bar()], company_id='c', as_of=AS_OF,
                          price_basis='raw', snapshot_last_date=PRICE_DATE)
    with pytest.raises(ValueError):
        valuation_metrics(data(), [bar()], company_id='c', as_of=AS_OF.replace(tzinfo=None),
                          price_basis=PRICE_BASIS, snapshot_last_date=PRICE_DATE)
