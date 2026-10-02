from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from stock_factor_engine.fundamentals.balance import balance_metrics
from stock_factor_engine.models.financials import FinancialFact
from stock_factor_engine.providers.sec.ingestion import parse_facts
from stock_factor_engine.models.financials import Filing


AS_OF = datetime(2024, 3, 1, tzinfo=UTC)


def fact(concept, value, end='2023-12-31', start=None, available=None):
    return FinancialFact('c', 'amend' if available else 'original', concept, Decimal(str(value)),
                         'USD', date.fromisoformat(end), available or datetime(2024, 2, 1, tzinfo=UTC),
                         date.fromisoformat(start) if start else None, 'us-gaap')


def observations():
    facts = []
    for end, debt, cash, equity in [('2022-12-31', 50, 10, 60), ('2023-12-31', 60, 20, 80)]:
        facts += [fact('total_debt', debt, end), fact('cash', cash, end),
                  fact('shareholders_equity', equity, end)]
    facts += [fact(concept, value, start='2023-01-01') for concept, value in [
        ('operating_income', 30), ('income_tax_expense', 5), ('pretax_income', 25),
        ('interest_expense', 3)]]
    return facts


def run(facts, **kwargs):
    return balance_metrics(facts, company_id='c', as_of=AS_OF, **kwargs)[1]


def test_balances_roic_tax_and_interest():
    result = run(observations())
    assert result['total_debt'].value == 60
    assert result['net_debt'].value == 40
    assert result['invested_capital'].value == 120
    assert result['average_invested_capital'].value == 110
    assert result['effective_tax_rate'].value == Decimal('0.2')
    assert result['nopat_proxy'].value == 24
    assert abs(result['roic_proxy'].value - Decimal(24) / 110) < Decimal('1e-27')
    assert result['interest_coverage'].value == 10


def test_debt_components_do_not_double_count_total():
    facts = observations() + [fact('long_term_debt_total', 50), fact('long_term_debt_current', 10),
                              fact('long_term_debt_noncurrent', 40), fact('short_term_borrowings', 10)]
    assert run(facts)['total_debt'].value == 60
    result = run([item for item in facts if item.concept != 'total_debt'])
    assert result['total_debt'].value == 60


def test_conflicting_debt_components_are_unavailable():
    facts = observations() + [fact('long_term_debt_total', 50), fact('long_term_debt_current', 11),
                              fact('long_term_debt_noncurrent', 40), fact('short_term_borrowings', 10)]
    assert run(facts)['long_term_debt'].value is None


def test_missing_debt_is_not_zero_and_assumption_is_explicit():
    facts = [item for item in observations() if item.concept != 'total_debt']
    facts += [fact('long_term_debt_total', 50), fact('long_term_debt_total', 40, '2022-12-31')]
    assert run(facts)['total_debt'].value is None
    explicit = run(facts, assume_zero_short_term_debt=True)
    assert explicit['total_debt'].value == 50
    assert len(explicit['roic_proxy'].assumptions) == 2
    facts += [fact('commercial_paper', 5)]
    assert run(facts, assume_zero_short_term_debt=True)['total_debt'].value is None


@pytest.mark.parametrize('concept,value', [('interest_expense', 0), ('pretax_income', 0),
                                         ('pretax_income', -1), ('income_tax_expense', -1),
                                         ('income_tax_expense', 30)])
def test_invalid_ratios_are_not_infinite_or_clamped(concept, value):
    facts = [item for item in observations() if item.concept != concept]
    facts += [fact(concept, value, start='2023-01-01')]
    result = run(facts)
    target = 'interest_coverage' if concept == 'interest_expense' else 'roic_proxy'
    assert result[target].value is None
    assert result['cash'].value == 20


def test_opening_balance_must_match_exact_date():
    facts = [item for item in observations() if item.period_end != date(2022, 12, 31)]
    facts += [fact('total_debt', 50, '2022-09-30')]
    assert run(facts)['average_invested_capital'].value is None


def test_future_restatement_and_old_balance_are_not_leaked():
    facts = observations() + [fact('total_debt', 99, available=datetime(2024, 4, 1, tzinfo=UTC))]
    assert run(facts)['total_debt'].value == 60
    results = balance_metrics(facts, company_id='c', as_of=datetime(2024, 5, 1, tzinfo=UTC))[1]
    assert results['total_debt'].value == 99


def test_nonoperating_interest_fallback_and_tax_window_mismatch():
    facts = [item for item in observations() if item.concept not in {'interest_expense', 'income_tax_expense'}]
    facts += [fact('interest_expense_nonoperating', 2, start='2023-01-01'),
              fact('income_tax_expense', 5, start='2022-12-26')]
    results = run(facts)
    assert results['interest_coverage'].value == 15
    assert results['effective_tax_rate'].value is None


def test_negative_average_capital_is_not_valid_roic():
    facts = [item for item in observations() if item.concept != 'shareholders_equity']
    facts += [fact('shareholders_equity', -200), fact('shareholders_equity', -200, '2022-12-31')]
    assert run(facts)['roic_proxy'].value is None


def test_new_sec_mapping_preserves_shapes():
    filing = Filing('a', 'c', '10-K', date(2023, 12, 31), date(2024, 2, 1), AS_OF, AS_OF)
    payload = {'facts': {'us-gaap': {
        'LongTermDebtCurrent': {'units': {'USD': [{'accn': 'a', 'form': '10-K', 'filed': '2024-02-01',
                                                'end': '2023-12-31', 'val': 10}]}},
        'InterestExpenseNonoperating': {'units': {'USD': [{'accn': 'a', 'form': '10-K', 'filed': '2024-02-01',
                                                          'start': '2023-01-01', 'end': '2023-12-31', 'val': 3}]}},
    }}}
    parsed, rejected = parse_facts(payload, 'c', {'a': filing})
    assert rejected == []
    assert [(item.concept, item.is_instant) for item, _ in parsed] == [
        ('long_term_debt_current', True), ('interest_expense_nonoperating', False)]
