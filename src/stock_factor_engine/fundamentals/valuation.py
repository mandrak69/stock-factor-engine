"""Explicit research valuations from a single provider price vintage."""
from datetime import date
from decimal import localcontext
from zoneinfo import ZoneInfo

from stock_factor_engine.point_in_time.financials import facts_as_of
from stock_factor_engine.providers.market.yahoo import PRICE_BASIS
from .balance import Result
from .ttm import Term, _sum, calculate_ttm, shape


def valuation_metrics(facts, bars, *, company_id, as_of, price_basis,
                      snapshot_last_date, split_dates=(), period_end=None):
    selected = facts_as_of(facts, company_id=company_id, as_of=as_of)
    today = as_of.astimezone(ZoneInfo('America/New_York')).date()
    if len({bar.trading_date for bar in bars}) != len(bars) or any(
            a.trading_date >= b.trading_date for a, b in zip(bars, bars[1:])):
        raise ValueError('Prices must have unique chronological dates')
    if price_basis != PRICE_BASIS:
        raise ValueError('Unsupported valuation price basis')
    if bars and snapshot_last_date < bars[-1].trading_date:
        raise ValueError('Snapshot horizon precedes its prices')
    eligible = [bar for bar in bars if bar.trading_date < today]
    price = eligible[-1] if eligible else None
    price_reason = None
    if price is None or (today - price.trading_date).days > 7:
        price_reason = 'No completed-session price within seven calendar days'
    elif not price.close.is_finite() or price.close <= 0:
        price_reason = 'Invalid provider close'
    price_result = Result(None if price_reason else price.close, 'USD/shares',
                          'provider split-adjusted close; no dividend adjustment', price_reason,
                          inputs={'price_date': price.trading_date if price else None,
                                  'price_basis': price_basis, 'snapshot_last_date': snapshot_last_date})
    ends = [fact.period_end for fact in selected if fact.concept == 'revenue'
            and fact.unit == 'USD' and fact.period_start is not None
            and price is not None and fact.period_end <= price.trading_date]
    end = period_end or (max(ends) if ends else None)
    if end is not None and (price is None or end > price.trading_date):
        raise ValueError('Financial period end is after the price date')
    results = {'price': price_result}

    def amount(concept):
        if end is None:
            return Result(None, 'USD', 'TTM ' + concept, 'No revenue reporting period available')
        if (price.trading_date - end).days > 180:
            return Result(None, 'USD', 'TTM ' + concept, 'Financial period more than 180 days before price')
        try:
            metric = calculate_ttm(selected, concept, end)
            return Result(metric.value, 'USD', metric.method,
                          inputs={'period_start': metric.period_start, 'period_end': metric.period_end},
                          sources=metric.terms)
        except ValueError as error:
            return Result(None, 'USD', 'TTM ' + concept, str(error))

    revenue, ocf, capex = (amount(concept) for concept in
                           ('revenue', 'operating_cash_flow', 'capital_expenditure'))
    results['revenue_ttm'] = revenue
    fcf_inputs = {'operating_cash_flow': ocf, 'capital_expenditure': capex}
    if ocf.value is None or capex.value is None:
        fcf = Result(None, 'USD', 'operating cash flow - capex', 'Missing FCF inputs', inputs=fcf_inputs)
    elif ocf.inputs != capex.inputs or (revenue.value is not None and ocf.inputs != revenue.inputs):
        fcf = Result(None, 'USD', 'operating cash flow - capex', 'Financial windows differ', inputs=fcf_inputs)
    else:
        fcf = Result(_sum((ocf.value, capex.value.copy_negate())), 'USD',
                     'operating cash flow - capex', inputs=fcf_inputs)
    results['free_cash_flow_ttm'] = fcf

    candidates = [fact for fact in selected if fact.concept in
                  ('reported_shares_outstanding', 'cover_shares_outstanding')
                  and fact.unit == 'shares' and fact.is_instant and price is not None
                  and fact.period_end <= price.trading_date]
    share_fact, share_reason = None, 'No reported outstanding share count by price date'
    if candidates:
        latest = max(fact.period_end for fact in candidates)
        latest_facts = [fact for fact in candidates if fact.period_end == latest]
        share_fact = sorted(latest_facts, key=lambda fact: (fact.concept, fact.filing_accession_number))[0]
        share_reason = None
        if len({fact.value for fact in latest_facts}) != 1:
            share_reason = 'Conflicting outstanding share counts at latest observation date'
        elif not share_fact.value.is_finite() or share_fact.value <= 0:
            share_reason = 'Invalid outstanding share count'
        elif (price.trading_date - latest).days > 120:
            share_reason = 'Share count more than 120 days before price'
        elif any(latest < day <= snapshot_last_date for day in split_dates):
            share_reason = 'Split after share observation; provider price and reported share basis not reconciled'
    shares = Result(None if share_reason else share_fact.value, 'shares',
                    'latest reported outstanding shares; never weighted-average shares', share_reason,
                    inputs={'observation_date': share_fact.period_end if share_fact else None,
                            'concept': share_fact.concept if share_fact else None},
                    sources=(Term(share_fact),) if share_fact else ())
    results['shares_outstanding'] = shares
    assumption = ('Research estimate: reported outstanding shares held constant until price date; '
                  'provider split history assumed complete, no independent as-traded price verification',)
    inputs = {'price': price_result, 'shares': shares}
    with localcontext() as context:
        context.prec = 34
        cap = Result(price_result.value * shares.value if price_result.value is not None and shares.value is not None else None,
                     'USD', 'provider close × latest reported outstanding shares',
                     price_reason or share_reason, inputs=inputs, assumptions=assumption)
        results['market_cap_estimate'] = cap
        for name, numerator, denominator, positive in [
                ('price_to_sales', cap, revenue, True), ('fcf_yield', fcf, cap, False)]:
            reason = None
            if numerator.value is None or denominator.value is None:
                reason = 'Missing valuation inputs'
            elif denominator.value <= 0:
                reason = 'Denominator must be positive'
            results[name] = Result(None if reason else numerator.value / denominator.value,
                                   'multiple' if positive else 'ratio',
                                   'market cap estimate / TTM revenue' if positive else 'TTM FCF / market cap estimate',
                                   reason, inputs={'numerator': numerator, 'denominator': denominator},
                                   assumptions=assumption)
        annual = [fact for fact in selected if fact.concept == 'eps_diluted'
                  and fact.unit == 'USD/shares' and fact.period_end == end and shape(fact) == 'annual'
                  and fact.period_start == revenue.inputs.get('period_start')]
        eps_fact = annual[0] if annual else None
        eps_reason = None
        if eps_fact is None or revenue.value is None:
            eps_reason = 'No direct annual diluted EPS matching the revenue TTM window; quarterly EPS is not summed'
        elif not eps_fact.value.is_finite() or eps_fact.value <= 0:
            eps_reason = 'Diluted EPS must be positive; loss/zero earnings have no P/E'
        elif any(eps_fact.period_start <= day <= snapshot_last_date for day in split_dates):
            eps_reason = 'Split during or after EPS period; reported EPS and provider price basis not reconciled'
        eps = Result(None if eps_reason else eps_fact.value, 'USD/shares', 'reported direct annual diluted EPS',
                     eps_reason, inputs={'period_start': eps_fact.period_start if eps_fact else None,
                                         'period_end': eps_fact.period_end if eps_fact else None},
                     sources=(Term(eps_fact),) if eps_fact else ())
        results['eps_diluted_annual'] = eps
        reason = price_reason or eps_reason
        results['pe_diluted_annual'] = Result(None if reason else price_result.value / eps.value,
                                             'multiple', 'provider close / reported annual diluted EPS', reason,
                                             inputs={'price': price_result, 'eps': eps},
                                             assumptions=('Provider price and reported EPS basis assumed compatible when no split is observed',))
    return end, results
