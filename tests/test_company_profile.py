from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from stock_factor_engine.fundamentals.company import company_profile
from stock_factor_engine.models.financials import Filing, FinancialFact
from stock_factor_engine.providers.sec.ingestion import parse_facts


AS_OF = datetime(2024, 3, 1, tzinfo=UTC)


def fact(concept, value, start=None, end='2023-12-31', unit='USD', available=AS_OF, accession='f'):
    return FinancialFact('c', accession, concept, Decimal(str(value)), unit, date.fromisoformat(end),
                         available, date.fromisoformat(start) if start else None, 'us-gaap')


def observations():
    result = []
    for start, end, revenue, income, ocf, capex in [
        ('2022-01-01', '2022-12-31', 100, 10, 20, 5),
        ('2023-01-01', '2023-12-31', 120, 15, 25, 7)]:
        result += [fact(concept, value, start, end) for concept, value in [
            ('revenue', revenue), ('operating_income', income),
            ('operating_cash_flow', ocf), ('capital_expenditure', capex)]]
    result += [fact('reported_shares_outstanding', 100, end='2022-12-31', unit='shares'),
               fact('reported_shares_outstanding', 90, unit='shares'),
               fact('cover_shares_outstanding', 89, end='2024-01-20', unit='shares'),
               fact('weighted_average_shares_basic', 95, '2023-01-01', unit='shares'),
               fact('weighted_average_shares_diluted', 97, '2023-01-01', unit='shares'),
               fact('eps_diluted', '1.25', '2023-01-01', unit='USD/shares')]
    return result


def run(facts):
    return company_profile(facts, company_id='c', as_of=AS_OF)[1]


def test_growth_margins_and_separate_share_definitions():
    result = run(observations())
    assert result['revenue_growth_yoy'].value == Decimal('0.2')
    assert result['operating_income_growth_yoy'].value == Decimal('0.5')
    assert result['free_cash_flow_growth_yoy'].value == Decimal('0.2')
    assert result['operating_margin'].value == Decimal('0.125')
    assert result['fcf_margin'].value == Decimal('0.15')
    assert result['reported_shares_outstanding'].value == 90
    assert result['latest_cover_shares_outstanding'].value == 89
    assert result['weighted_average_shares_basic'].value == 95
    assert result['weighted_average_shares_diluted'].value == 97
    assert result['eps_diluted'].value == Decimal('1.25')
    assert result['reported_share_count_change'].value == Decimal('-0.1')
    assert result['reported_share_count_change'].assumptions
    assert result['market_cap'].value is None


def test_prior_period_is_not_previous_publication_date():
    facts = observations() + [fact('revenue', 80, '2022-01-01', '2022-12-31',
                                  available=datetime(2024, 2, 1, tzinfo=UTC), accession='restatement')]
    # New comparison must win over an earlier version, irrespective of list order.
    facts = [item for item in facts if item.concept != 'revenue' or item.period_end != date(2022, 12, 31)
             or item.filing_accession_number == 'restatement'] + [
        fact('revenue', 100, '2022-01-01', '2022-12-31', available=datetime(2023, 2, 1, tzinfo=UTC), accession='old')]
    assert run(facts)['revenue_growth_yoy'].value == Decimal('0.5')


def test_future_shares_and_future_revenue_are_invisible():
    facts = observations() + [fact('reported_shares_outstanding', 50, unit='shares',
                                  available=datetime(2024, 4, 1, tzinfo=UTC), accession='future'),
                              fact('revenue', 240, '2023-01-01',
                                   available=datetime(2024, 4, 1, tzinfo=UTC), accession='future')]
    result = run(facts)
    assert result['reported_shares_outstanding'].value == 90
    assert result['revenue_growth_yoy'].value == Decimal('0.2')


@pytest.mark.parametrize('base', [0, -10])
def test_zero_and_loss_base_do_not_create_growth_percentage(base):
    facts = [item for item in observations() if item.concept != 'operating_income' or item.period_end != date(2022, 12, 31)]
    facts += [fact('operating_income', base, '2022-01-01', '2022-12-31')]
    result = run(facts)
    assert result['operating_income_growth_yoy'].value is None
    assert result['operating_income_ttm'].value == 15


def test_weighted_shares_are_not_summed_from_cumulative_quarters():
    facts = [item for item in observations() if item.concept != 'weighted_average_shares_basic']
    facts += [fact('weighted_average_shares_basic', 80, '2023-01-01', '2023-06-30', unit='shares'),
              fact('weighted_average_shares_basic', 90, '2023-01-01', '2023-09-30', unit='shares')]
    assert run(facts)['weighted_average_shares_basic'].value is None


def test_missing_historical_shares_remain_missing():
    facts = [item for item in observations() if item.concept != 'reported_shares_outstanding'
             or item.period_end != date(2022, 12, 31)]
    assert run(facts)['reported_share_count_change'].value is None


def test_mismatched_prior_window_is_rejected():
    facts = [item for item in observations() if item.concept != 'operating_income'
             or item.period_end != date(2022, 12, 31)]
    facts += [fact('operating_income', 10, '2021-12-27', '2022-12-31')]
    assert run(facts)['operating_income_growth_yoy'].value is None


def test_namespace_units_and_shapes_are_preserved():
    filing = Filing('a', 'c', '10-K', date(2023, 12, 31), date(2024, 2, 1), AS_OF, AS_OF)
    observation = {'accn': 'a', 'form': '10-K', 'filed': '2024-02-01', 'end': '2023-12-31', 'val': 100}
    payload = {'facts': {
        'dei': {'EntityCommonStockSharesOutstanding': {'units': {'shares': [observation]}}},
        'us-gaap': {
            'CommonStockSharesOutstanding': {'units': {'shares': [observation]}},
            'WeightedAverageNumberOfDilutedSharesOutstanding': {'units': {'shares': [{**observation, 'start': '2023-01-01'}]}},
            'EarningsPerShareDiluted': {'units': {'USD/shares': [{**observation, 'start': '2023-01-01', 'val': 1.2}]}},
        }}}
    parsed, rejected = parse_facts(payload, 'c', {'a': filing})
    assert rejected == []
    facts = {item.concept: item for item, _ in parsed}
    assert facts['cover_shares_outstanding'].source_taxonomy == 'dei'
    assert facts['reported_shares_outstanding'].source_taxonomy == 'us-gaap'
    assert facts['weighted_average_shares_diluted'].period_start == date(2023, 1, 1)
    assert facts['eps_diluted'].unit == 'USD/shares'
    payload['facts']['dei']['EntityCommonStockSharesOutstanding']['units'] = {'USD': [observation]}
    _, rejected = parse_facts(payload, 'c', {'a': filing})
    assert len(rejected) == 1
