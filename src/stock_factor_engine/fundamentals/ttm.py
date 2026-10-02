from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, localcontext

from stock_factor_engine.models.financials import FinancialFact
from stock_factor_engine.point_in_time.financials import facts_as_of


CONCEPTS = ('revenue', 'operating_income', 'operating_cash_flow', 'capital_expenditure')


class InsufficientCoverageError(ValueError):
    """No complete, contiguous trailing year at the requested reporting end."""


class InconsistentPeriodError(ValueError):
    """Alternative evidence gives conflicting amounts for the same period."""


@dataclass(frozen=True)
class Term:
    fact: FinancialFact
    coefficient: int = 1


@dataclass(frozen=True)
class Metric:
    concept: str
    period_start: date
    period_end: date
    value: Decimal
    method: str
    terms: tuple[Term, ...]
    unit: str = 'USD'


def _sum(values) -> Decimal:
    values = list(values)
    if any(not value.is_finite() for value in values):
        raise InconsistentPeriodError('Non-finite financial amount')
    with localcontext() as context:
        context.prec = max(28, max((value.adjusted() for value in values), default=0)
                           - min((value.as_tuple().exponent for value in values), default=0)
                           + len(values) + 10)
        return sum(values, Decimal(0))


def shape(fact: FinancialFact) -> str:
    if fact.period_start is None:
        return 'instant'
    days = (fact.period_end - fact.period_start).days + 1
    for name, lower, upper in [('quarter', 70, 110), ('half_year', 150, 210),
                               ('nine_months', 240, 300), ('annual', 350, 380)]:
        if lower <= days <= upper:
            return name
    return 'unsupported_duration'


def _consistent(candidates: list[Metric]) -> Metric:
    if len({candidate.value for candidate in candidates}) != 1:
        raise InconsistentPeriodError(
            f'Conflicting {candidates[0].concept} amounts for '
            f'{candidates[0].period_start}..{candidates[0].period_end}')
    # Prefer direct evidence; remaining ordering is deterministic.
    return min(candidates, key=lambda metric: (len(metric.terms), tuple(
        (term.fact.filing_accession_number, term.coefficient) for term in metric.terms)))


def quarters(facts: list[FinancialFact], concept: str) -> list[Metric]:
    """Direct quarters and cumulative differences; never add overlapping periods."""
    candidates: dict[tuple[date, date], list[Metric]] = {}
    durations = [fact for fact in facts if fact.concept == concept and fact.unit == 'USD'
                 and fact.period_start is not None and shape(fact) != 'unsupported_duration']
    for fact in durations:
        if shape(fact) == 'quarter':
            key = fact.period_start, fact.period_end
            candidates.setdefault(key, []).append(Metric(concept, *key, fact.value,
                                                        'direct_quarter', (Term(fact),)))
        for prior in durations:
            if prior.period_start != fact.period_start or prior.period_end >= fact.period_end:
                continue
            start = prior.period_end + timedelta(days=1)
            if 70 <= (fact.period_end - start).days + 1 <= 110:
                key = start, fact.period_end
                candidates.setdefault(key, []).append(Metric(
                    concept, *key, _sum((fact.value, prior.value.copy_negate())), 'cumulative_difference',
                    (Term(fact), Term(prior, -1))))
    result = [_consistent(group) for group in candidates.values()]
    if concept == 'capital_expenditure' and any(metric.value < 0 for metric in result):
        raise InconsistentPeriodError('Negative derived capital expenditure')
    return sorted(result, key=lambda metric: (metric.period_end, metric.period_start))


def calculate_ttm(facts: list[FinancialFact], concept: str, period_end: date) -> Metric:
    inputs = [fact for fact in facts if fact.concept == concept and fact.unit == 'USD']
    if any(not fact.value.is_finite() for fact in inputs):
        raise InconsistentPeriodError('Non-finite financial amount')
    if len({fact.company_id for fact in inputs}) > 1:
        raise ValueError('TTM inputs must belong to one company')
    candidates = [Metric(concept, fact.period_start, fact.period_end, fact.value,
                         'direct_annual', (Term(fact),)) for fact in facts
                  if fact.concept == concept and fact.unit == 'USD'
                  and fact.period_end == period_end and shape(fact) == 'annual']
    # Ignore older intervals which cannot contribute to this trailing window.
    relevant = [fact for fact in facts if period_end - timedelta(days=400) <= fact.period_end <= period_end]
    quarter_values = quarters(relevant, concept)

    def visit(end: date, reverse_path: list[Metric]):
        if len(reverse_path) == 4:
            path = list(reversed(reverse_path))
            days = (period_end - path[0].period_start).days + 1
            if 350 <= days <= 380:
                candidates.append(Metric(concept, path[0].period_start, period_end,
                                         _sum(item.value for item in path),
                                         'four_contiguous_quarters',
                                         tuple(term for item in path for term in item.terms)))
            return
        for quarter in quarter_values:
            if quarter.period_end == end:
                visit(quarter.period_start - timedelta(days=1), reverse_path + [quarter])

    visit(period_end, [])
    if not candidates:
        raise InsufficientCoverageError(f'No complete TTM window for {concept} ending {period_end}')
    windows = {(candidate.period_start, candidate.period_end) for candidate in candidates}
    if len(windows) != 1:
        raise InconsistentPeriodError(f'Multiple trailing windows for {concept}')
    result = _consistent(candidates)
    if concept == 'capital_expenditure' and result.value < 0:
        raise InconsistentPeriodError('Capital expenditure must use a positive outflow convention')
    return result


def ttm_metrics(facts, *, company_id: str, as_of: datetime, period_end: date | None = None):
    selected = facts_as_of(facts, company_id=company_id, as_of=as_of)
    as_of = as_of.astimezone(UTC)
    relevant = [fact for fact in selected if fact.concept in CONCEPTS and fact.unit == 'USD'
                and fact.period_start is not None]
    if not relevant:
        raise InsufficientCoverageError('No available duration facts')
    end = period_end or max(fact.period_end for fact in relevant)
    if end > as_of.date():
        raise InsufficientCoverageError('Reporting period ends after the as-of date')
    result = {concept: calculate_ttm(relevant, concept, end) for concept in CONCEPTS}
    windows = {(metric.period_start, metric.period_end) for metric in result.values()}
    if len(windows) != 1:
        raise InsufficientCoverageError('Metrics do not cover the same trailing window')
    ocf, capex = result['operating_cash_flow'], result['capital_expenditure']
    result['free_cash_flow'] = Metric(
        'free_cash_flow', ocf.period_start, end, _sum((ocf.value, capex.value.copy_negate())),
        'operating_cash_flow_minus_capex', ocf.terms + tuple(
            Term(term.fact, -term.coefficient) for term in capex.terms))
    return result


def coverage(facts):
    report = {}
    for concept in CONCEPTS:
        observations = [fact for fact in facts if fact.concept == concept and fact.unit == 'USD']
        shapes = {}
        for fact in observations:
            category = shape(fact)
            shapes[category] = shapes.get(category, 0) + 1
        report[concept] = {'visible_periods': len(observations), 'shapes': shapes,
                           'first_period_end': min((fact.period_end for fact in observations), default=None),
                           'last_period_end': max((fact.period_end for fact in observations), default=None)}
    return report
