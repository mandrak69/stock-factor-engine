from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, localcontext

from stock_factor_engine.point_in_time.financials import facts_as_of
from .ttm import Term, _sum, calculate_ttm


@dataclass(frozen=True)
class Result:
    value: Decimal | None
    unit: str
    formula: str
    reason: str | None = None
    inputs: dict = field(default_factory=dict)
    sources: tuple[Term, ...] = ()
    assumptions: tuple[str, ...] = ()

    @property
    def status(self):
        return 'available' if self.value is not None else 'unavailable'


def balance_metrics(facts, *, company_id: str, as_of: datetime,
                    period_end: date | None = None, assume_zero_short_term_debt=False):
    selected = facts_as_of(facts, company_id=company_id, as_of=as_of)
    available_periods = [fact.period_end for fact in selected if fact.concept == 'operating_income'
                         and fact.period_start is not None and fact.unit == 'USD']
    if not available_periods:
        raise ValueError('No operating-income reporting period available')
    end = period_end or max(available_periods)
    if end > as_of.astimezone(UTC).date():
        raise ValueError('Reporting end is after as-of')

    def instant(concept, on_date):
        values = [fact for fact in selected if fact.concept == concept and fact.is_instant
                  and fact.period_end == on_date and fact.unit == 'USD']
        if not values:
            return Result(None, 'USD', concept, f'Missing {concept} at {on_date}')
        fact = values[0]
        if not fact.value.is_finite():
            return Result(None, 'USD', concept, 'Non-finite amount')
        if concept != 'shareholders_equity' and fact.value < 0:
            return Result(None, 'USD', concept, 'Negative balance')
        return Result(fact.value, 'USD', concept, sources=(Term(fact),))

    def duration(concept):
        try:
            metric = calculate_ttm(selected, concept, end)
            return Result(metric.value, 'USD', metric.method,
                          inputs={'period_start': metric.period_start, 'period_end': metric.period_end},
                          sources=metric.terms)
        except ValueError as error:
            return Result(None, 'USD', 'TTM ' + concept, str(error))

    def derived(formula, inputs, operation, unit='USD', sources=()):
        missing = [name for name, result in inputs.items() if result.value is None]
        if missing:
            return Result(None, unit, formula, 'Unavailable inputs: ' + ', '.join(missing), inputs=inputs)
        with localcontext() as context:
            # Ratios intentionally have 34 significant digits; currency sums use _sum.
            context.prec = 34
            try:
                value = operation(*[result.value for result in inputs.values()])
            except (ValueError, ArithmeticError) as error:
                return Result(None, unit, formula, str(error), inputs=inputs)
        assumptions = tuple(sorted({item for result in inputs.values() for item in result.assumptions}))
        return Result(value, unit, formula, inputs=inputs, sources=sources, assumptions=assumptions)

    def long_term(on_date):
        total = instant('long_term_debt_total', on_date)
        current, noncurrent = instant('long_term_debt_current', on_date), instant('long_term_debt_noncurrent', on_date)
        components = derived('current + noncurrent long-term debt', {'current': current, 'noncurrent': noncurrent},
                             lambda a, b: _sum((a, b)))
        if total.value is not None:
            if components.value is not None and total.value != components.value:
                return Result(None, 'USD', 'long-term debt', 'Total disagrees with current + noncurrent')
            return total
        return components

    def debt(on_date):
        total, lt = instant('total_debt', on_date), long_term(on_date)
        short = instant('short_term_borrowings', on_date)
        paper = instant('commercial_paper', on_date)
        # Commercial paper can overlap short-term borrowings; never blindly add it.
        if short.value is None and assume_zero_short_term_debt:
            if paper.value is not None and paper.value != 0:
                return Result(None, 'USD', 'total debt', 'Zero assumption conflicts with reported commercial paper')
            short = Result(Decimal(0), 'USD', 'explicit short-term debt assumption',
                           assumptions=(f'Short-term borrowings assumed zero at {on_date}',))
        components = derived('long-term debt + short-term borrowings', {'long_term': lt, 'short_term': short},
                             lambda a, b: _sum((a, b)))
        if total.value is not None:
            if components.value is not None and total.value != components.value:
                return Result(None, 'USD', 'total debt', 'Combined debt disagrees with components')
            return total
        return components

    def invested(on_date):
        return derived('debt + equity - cash', {
            'total_debt': debt(on_date), 'equity': instant('shareholders_equity', on_date),
            'cash': instant('cash', on_date)}, lambda d, e, c: _sum((d, e, c.copy_negate())))

    def positive_ratio(numerator, denominator):
        if denominator <= 0:
            raise ValueError('Denominator must be positive')
        return numerator / denominator

    results = {'cash': instant('cash', end), 'long_term_debt': long_term(end),
               'total_debt': debt(end), 'equity': instant('shareholders_equity', end),
               'short_term_investments': instant('short_term_investments', end)}
    for name in ('cash', 'long_term_debt', 'total_debt'):
        if results[name].value is not None and results[name].value < 0:
            results[name] = Result(None, 'USD', results[name].formula, 'Negative balance')
    results['net_debt'] = derived('total debt - cash',
                                  {'debt': results['total_debt'], 'cash': results['cash']},
                                  lambda d, c: _sum((d, c.copy_negate())))
    results['invested_capital'] = invested(end)
    income, tax, pretax = duration('operating_income'), duration('income_tax_expense'), duration('pretax_income')
    results['operating_income_ttm'], results['income_tax_ttm'], results['pretax_income_ttm'] = income, tax, pretax
    interest = duration('interest_expense')
    if interest.value is None and not any(
        fact.concept == 'interest_expense' and fact.period_end == end
        and fact.period_start is not None for fact in selected
    ):
        interest = duration('interest_expense_nonoperating')
    results['interest_expense_ttm'] = interest
    if income.value is not None:
        start = income.inputs['period_start']
        opening_date = start - timedelta(days=1)
        results['invested_capital_opening'] = invested(opening_date)
        average = derived('(opening capital + closing capital) / 2',
                          {'opening': results['invested_capital_opening'], 'closing': results['invested_capital']},
                          lambda a, b: _sum((a, b)) / Decimal(2))
    else:
        average = Result(None, 'USD', 'average invested capital', 'Missing TTM operating income window')
    results['average_invested_capital'] = average
    # All duration inputs must refer to the operating-income window.
    for name in ('income_tax_ttm', 'pretax_income_ttm', 'interest_expense_ttm'):
        item = results[name]
        if item.value is not None and income.value is not None and item.inputs != income.inputs:
            results[name] = Result(None, item.unit, item.formula, 'Duration window differs from operating income')
    rate = derived('income tax / pretax income',
                   {'tax': results['income_tax_ttm'], 'pretax': results['pretax_income_ttm']},
                   positive_ratio, 'ratio')
    if rate.value is not None and not Decimal(0) <= rate.value <= Decimal(1):
        rate = Result(None, 'ratio', rate.formula, 'Effective tax rate outside [0, 1]; no automatic clamp', inputs=rate.inputs)
    results['effective_tax_rate'] = rate
    results['nopat_proxy'] = derived('operating income * (1 - effective tax rate)',
                                     {'operating_income': income, 'tax_rate': rate}, lambda i, r: i * (1 - r))
    results['roic_proxy'] = derived('NOPAT proxy / average invested capital',
                                    {'nopat': results['nopat_proxy'], 'capital': average}, positive_ratio, 'ratio')
    results['interest_coverage'] = derived('operating income / interest expense',
                                          {'operating_income': income, 'interest': results['interest_expense_ttm']},
                                          positive_ratio, 'multiple')
    return end, results
