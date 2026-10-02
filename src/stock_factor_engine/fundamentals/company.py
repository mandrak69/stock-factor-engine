from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, localcontext

from stock_factor_engine.point_in_time.financials import facts_as_of
from .balance import Result, balance_metrics
from .ttm import Term, _sum, calculate_ttm, shape


def company_profile(facts, *, company_id: str, as_of: datetime, period_end: date | None = None):
    selected = facts_as_of(facts, company_id=company_id, as_of=as_of)
    ends = [fact.period_end for fact in selected if fact.concept == 'revenue'
            and fact.period_start is not None and fact.unit == 'USD']
    if not ends:
        raise ValueError('No revenue reporting period available')
    end = period_end or max(ends)
    if end > as_of.astimezone(UTC).date():
        raise ValueError('Reporting end is after as-of')
    results = {}

    def amount(concept, on_date):
        try:
            metric = calculate_ttm(selected, concept, on_date)
            return Result(metric.value, 'USD', metric.method,
                          inputs={'period_start': metric.period_start, 'period_end': metric.period_end},
                          sources=metric.terms)
        except ValueError as error:
            return Result(None, 'USD', 'TTM ' + concept, str(error))

    current = {concept: amount(concept, end) for concept in (
        'revenue', 'operating_income', 'operating_cash_flow', 'capital_expenditure',
        'common_stock_repurchases', 'common_stock_dividends_paid')}
    revenue = current['revenue']
    start = revenue.inputs.get('period_start')
    previous_end = start - timedelta(days=1) if start else None

    def fcf(inputs):
        ocf, capex = inputs['operating_cash_flow'], inputs['capital_expenditure']
        if ocf.value is None or capex.value is None:
            return Result(None, 'USD', 'operating cash flow - capex', 'Missing FCF inputs', inputs=inputs)
        if ocf.inputs != capex.inputs:
            return Result(None, 'USD', 'operating cash flow - capex', 'FCF input windows differ', inputs=inputs)
        return Result(_sum((ocf.value, capex.value.copy_negate())), 'USD', 'operating cash flow - capex',
                      inputs=inputs)

    current['free_cash_flow'] = fcf({name: current[name] for name in ('operating_cash_flow', 'capital_expenditure')})
    prior = {concept: amount(concept, previous_end) if previous_end else Result(
        None, 'USD', 'prior TTM ' + concept, 'Missing current revenue window') for concept in (
            'revenue', 'operating_income', 'operating_cash_flow', 'capital_expenditure')}
    prior['free_cash_flow'] = fcf({name: prior[name] for name in ('operating_cash_flow', 'capital_expenditure')})

    def ratio(current_value, prior_value, formula):
        inputs = {'current': current_value, 'previous': prior_value}
        if current_value.value is None or prior_value.value is None:
            return Result(None, 'ratio', formula, 'Missing current or previous value', inputs=inputs)
        if prior_value.value <= 0:
            return Result(None, 'ratio', formula, 'Previous value must be positive; no loss-to-profit percentage', inputs=inputs)
        with localcontext() as context:
            context.prec = 34
            value = current_value.value / prior_value.value - 1
        return Result(value, 'ratio', formula, inputs=inputs)

    for concept in ('revenue', 'operating_income', 'operating_cash_flow', 'capital_expenditure', 'free_cash_flow'):
        results[concept + '_ttm'] = current[concept]
        results[concept + '_previous_ttm'] = prior[concept]
        # Require matched fiscal windows across all components, not merely similar lengths.
        current_window = current[concept].inputs
        prior_window = prior[concept].inputs
        if concept == 'free_cash_flow':
            current_window = current[concept].inputs.get('operating_cash_flow', Result(None, 'USD', '')).inputs
            prior_window = prior[concept].inputs.get('operating_cash_flow', Result(None, 'USD', '')).inputs
        if current[concept].value is not None and (
            current_window.get('period_start') != start or current_window.get('period_end') != end
        ):
            results[concept + '_growth_yoy'] = Result(None, 'ratio', 'current / previous - 1', 'Current fiscal window differs from revenue')
        elif prior[concept].value is not None and (
            prior_window.get('period_end') != previous_end or start is None
            or prior_window.get('period_start') != prior['revenue'].inputs.get('period_start')
            or not 350 <= (previous_end - prior_window['period_start']).days + 1 <= 380
        ):
            results[concept + '_growth_yoy'] = Result(None, 'ratio', 'current / previous - 1', 'Previous fiscal window differs')
        else:
            results[concept + '_growth_yoy'] = ratio(current[concept], prior[concept], 'current TTM / previous TTM - 1')

    def instant(concept, on_date=None, unit='shares'):
        matches = [fact for fact in selected if fact.concept == concept and fact.unit == unit
                   and fact.is_instant and (on_date is None or fact.period_end == on_date)
                   and fact.period_end <= as_of.astimezone(UTC).date()]
        if not matches:
            return Result(None, unit, concept, f'Missing {concept} at requested date')
        fact = max(matches, key=lambda item: item.period_end)
        if not fact.value.is_finite() or fact.value < 0 or (unit == 'shares' and fact.value == 0):
            return Result(None, unit, concept, 'Invalid observation amount')
        return Result(fact.value, unit, concept, inputs={'observation_date': fact.period_end}, sources=(Term(fact),))

    shares = instant('reported_shares_outstanding', end)
    prior_shares = instant('reported_shares_outstanding', previous_end) if previous_end else Result(None, 'shares', 'prior shares', 'Missing window')
    results['reported_shares_outstanding'], results['previous_reported_shares_outstanding'] = shares, prior_shares
    # A count change is descriptive; without split-basis reconciliation it is not a dilution factor.
    change = ratio(shares, prior_shares, 'reported share count / previous reported share count - 1')
    if change.value is not None:
        change = Result(change.value, change.unit, change.formula, inputs=change.inputs,
                        assumptions=('Reported-count change only; split basis not independently verified',))
    results['reported_share_count_change'] = change
    results['latest_cover_shares_outstanding'] = instant('cover_shares_outstanding')

    for concept, unit in [('weighted_average_shares_basic', 'shares'),
                          ('weighted_average_shares_diluted', 'shares'), ('eps_diluted', 'USD/shares')]:
        matches = [fact for fact in selected if fact.concept == concept and fact.unit == unit
                   and fact.period_start == start and fact.period_end == end and shape(fact) == 'annual']
        if matches:
            fact = matches[0]
            results[concept] = Result(fact.value, unit, 'reported annual value; not sum of cumulative observations',
                                     inputs={'period_start': start, 'period_end': end}, sources=(Term(fact),))
        else:
            results[concept] = Result(None, unit, 'reported annual value', 'No direct annual observation for this window')
    results['common_stock_repurchases_ttm'] = current['common_stock_repurchases']
    results['common_stock_dividends_paid_ttm'] = current['common_stock_dividends_paid']
    for concept, name in [('operating_income', 'operating_margin'), ('free_cash_flow', 'fcf_margin')]:
        numerator = current[concept]
        if numerator.value is None or revenue.value is None or revenue.value <= 0:
            results[name] = Result(None, 'ratio', concept + ' / revenue', 'Missing or invalid margin inputs')
        elif results[concept + '_growth_yoy'].reason == 'Current fiscal window differs from revenue':
            results[name] = Result(None, 'ratio', concept + ' / revenue', 'Input fiscal windows differ')
        else:
            with localcontext() as context:
                context.prec = 34
                results[name] = Result(numerator.value / revenue.value, 'ratio', concept + ' / revenue',
                                       inputs={'numerator': numerator, 'revenue': revenue})
    try:
        _, balance = balance_metrics(selected, company_id=company_id, as_of=as_of, period_end=end)
        results['total_debt_coverage'] = balance['total_debt']
    except ValueError as error:
        results['total_debt_coverage'] = Result(None, 'USD', 'total debt', str(error))
    results['market_cap'] = Result(None, 'USD', 'as-traded price × contemporaneous shares',
                                 'Verified as-traded prices and compatible share basis not yet available')
    for concept in ('short_term_borrowings', 'commercial_paper'):
        results[concept + '_at_period_end'] = instant(concept, end, 'USD')
        results['latest_reported_' + concept] = instant(concept, unit='USD')
    return end, results
