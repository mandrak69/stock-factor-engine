from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from stock_factor_engine.fundamentals.ttm import (
    CONCEPTS, InconsistentPeriodError, InsufficientCoverageError,
    calculate_ttm, coverage, quarters, ttm_metrics,
)
from stock_factor_engine.models.financials import FinancialFact


def fact(start, end, value, concept='revenue', available='2024-02-01T00:00:00+00:00', accession='filing'):
    return FinancialFact('company', accession, concept, Decimal(str(value)), 'USD',
                         date.fromisoformat(end), datetime.fromisoformat(available),
                         date.fromisoformat(start) if start else None, 'us-gaap')


def annual_facts():
    return [fact('2023-01-01', '2023-12-31', amount, concept)
            for concept, amount in zip(CONCEPTS, (100, 20, 30, 10))]


def test_annual_metrics_and_exact_fcf():
    metrics = ttm_metrics(annual_facts(), company_id='company', as_of=datetime(2024, 3, 1, tzinfo=UTC))
    assert metrics['revenue'].value == 100
    assert metrics['free_cash_flow'].value == 20
    assert metrics['revenue'].method == 'direct_annual'
    assert [term.coefficient for term in metrics['free_cash_flow'].terms] == [1, -1]


def test_ytd_differences_and_no_double_counting():
    facts = [fact('2023-01-01', end, value) for end, value in (
        ('2023-03-31', 10), ('2023-06-30', 25), ('2023-09-30', 45), ('2023-12-31', 70))]
    facts.append(fact('2023-04-01', '2023-06-30', 15))
    assert [quarter.value for quarter in quarters(facts, 'revenue')] == [10, 15, 20, 25]
    assert calculate_ttm(facts, 'revenue', date(2023, 12, 31)).value == 70


def test_rolling_year_from_cumulative_data():
    facts = [fact('2022-01-01', '2022-09-30', 60),
             fact('2022-01-01', '2022-12-31', 100),
             fact('2023-01-01', '2023-03-31', 20),
             fact('2023-01-01', '2023-06-30', 45),
             fact('2023-01-01', '2023-09-30', 75)]
    metric = calculate_ttm(facts, 'revenue', date(2023, 9, 30))
    assert metric.value == 115
    assert metric.period_start == date(2022, 10, 1)
    assert metric.method == 'four_contiguous_quarters'
    assert sum(term.coefficient * term.fact.value for term in metric.terms) == metric.value


def test_gap_does_not_use_stale_annual_fallback():
    facts = [fact('2022-01-01', '2022-12-31', 100), fact('2023-07-01', '2023-09-30', 30)]
    with pytest.raises(InsufficientCoverageError):
        calculate_ttm(facts, 'revenue', date(2023, 9, 30))


def test_conflicting_quarter_and_cumulative_evidence():
    facts = [fact('2023-01-01', '2023-03-31', 10),
             fact('2023-01-01', '2023-06-30', 25),
             fact('2023-04-01', '2023-06-30', 16)]
    with pytest.raises(InconsistentPeriodError):
        quarters(facts, 'revenue')


def test_future_restatement_is_invisible_until_available():
    facts = annual_facts() + [fact('2023-01-01', '2023-12-31', 90,
                                   available='2024-04-01T00:00:00+00:00', accession='amendment')]
    before = ttm_metrics(facts, company_id='company', as_of=datetime(2024, 3, 1, tzinfo=UTC))
    after = ttm_metrics(facts, company_id='company', as_of=datetime(2024, 5, 1, tzinfo=UTC))
    assert before['revenue'].value == 100
    assert after['revenue'].value == 90
    with pytest.raises(InsufficientCoverageError):
        ttm_metrics(facts, company_id='company', as_of=datetime(2024, 1, 1, tzinfo=UTC))


def test_all_metrics_must_cover_latest_reporting_end():
    facts = annual_facts() + [fact('2024-01-01', '2024-03-31', 30,
                                  available='2024-05-01T00:00:00+00:00')]
    with pytest.raises(InsufficientCoverageError):
        ttm_metrics(facts, company_id='company', as_of=datetime(2024, 6, 1, tzinfo=UTC))


def test_53_week_fiscal_year_and_instant_coverage():
    facts = [fact('2022-12-26', '2023-12-31', 100), fact(None, '2023-12-31', 1)]
    assert calculate_ttm(facts, 'revenue', date(2023, 12, 31)).value == 100
    assert coverage(facts)['revenue']['shapes'] == {'annual': 1, 'instant': 1}


def test_fcf_preserves_more_than_default_decimal_precision():
    facts = annual_facts()
    facts[2] = fact('2023-01-01', '2023-12-31', '123456789012345678901234567890.123456789', 'operating_cash_flow')
    facts[3] = fact('2023-01-01', '2023-12-31', '0.000000001', 'capital_expenditure')
    result = ttm_metrics(facts, company_id='company', as_of=datetime(2024, 3, 1, tzinfo=UTC))
    assert result['free_cash_flow'].value == Decimal('123456789012345678901234567890.123456788')


def test_negative_capex_and_naive_cutoff_fail():
    facts = annual_facts()
    facts[3] = fact('2023-01-01', '2023-12-31', -10, 'capital_expenditure')
    with pytest.raises(InconsistentPeriodError):
        ttm_metrics(facts, company_id='company', as_of=datetime(2024, 3, 1, tzinfo=UTC))
    with pytest.raises(ValueError, match='timezone-aware'):
        ttm_metrics(annual_facts(), company_id='company', as_of=datetime(2024, 3, 1))


def test_annual_and_four_quarters_must_agree():
    facts = [fact('2023-01-01', '2023-12-31', 101)]
    facts.extend(fact(start, end, 25) for start, end in [
        ('2023-01-01', '2023-03-31'), ('2023-04-01', '2023-06-30'),
        ('2023-07-01', '2023-09-30'), ('2023-10-01', '2023-12-31')])
    with pytest.raises(InconsistentPeriodError):
        calculate_ttm(facts, 'revenue', date(2023, 12, 31))


def test_invalid_amount_is_rejected():
    with pytest.raises(InconsistentPeriodError):
        calculate_ttm([fact('2023-01-01', '2023-12-31', 'NaN')], 'revenue', date(2023, 12, 31))
