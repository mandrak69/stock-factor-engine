from dataclasses import asdict
from datetime import timedelta
from decimal import Decimal as D

from stock_factor_engine.point_in_time.financials import facts_as_of
from stock_factor_engine.fundamentals.ttm import calculate_ttm
from stock_factor_engine.strategy import CandidateSnapshot
from stock_factor_engine.regime.inputs import completed


def completed_prices(bars, as_of):
    return completed(bars, as_of, include_completed_close=True)


def session_factors(bars, session, reference_dates):
    if not bars or bars[-1].trading_date != session:
        raise ValueError('No exact-session price for ' + str(session))
    if len(bars) < 252:
        raise ValueError(f'Fewer than 252 completed trading sessions: {len(bars)}')
    # 252 intervals for 12-1 need 253 prices, though the universe filter is 252.
    if len(bars) < 253:
        raise ValueError('12-1 momentum requires 253 price observations')
    used = bars[-253:]
    if [bar.trading_date for bar in used] != list(reference_dates[-253:]):
        raise ValueError('Missing/misaligned sessions in 253-price factor window')
    p = [bar.adjusted_close for bar in used]
    returns = [p[i] / p[i - 1] - 1 for i in range(len(p) - 63, len(p))]
    mean = sum(returns, D(0)) / 63
    variance = sum(((value - mean) ** 2 for value in returns), D(0)) / 62
    peak, dd = p[-252], D(0)
    for value in p[-252:]:
        peak = max(peak, value)
        dd = min(dd, value / peak - 1)
    return {'momentum_12_1': p[-22] / p[-253] - 1,
            'momentum_6_1': p[-22] / p[-127] - 1,
            'volatility_63': (variance * 252).sqrt(), 'max_drawdown_252': dd}


def fundamental_factors(facts, *, company_id, as_of, session, price, splits=()):
    visible = [fact for fact in facts if fact.company_id == company_id and fact.available_at <= as_of
               and fact.period_end <= session]
    ends = [fact.period_end for fact in visible if fact.concept in
            ('operating_income', 'net_income', 'revenue', 'operating_cash_flow') and not fact.is_instant]
    if not ends:
        raise ValueError('No available operating income with justified SEC acceptance/availability timestamp')
    end = max(ends)
    durations = {'operating_income', 'operating_cash_flow', 'capital_expenditure', 'revenue',
                 'depreciation_amortization', 'depreciation', 'amortization_intangibles'}
    balances = {'cash', 'current_assets', 'current_liabilities', 'net_ppe', 'total_debt',
                'current_debt_total', 'long_term_debt_total', 'long_term_debt_current',
                'long_term_debt_noncurrent', 'short_term_borrowings'}
    shares = {'cover_shares_outstanding', 'reported_shares_outstanding'}
    relevant = [fact for fact in visible if
                (fact.concept in durations and not fact.is_instant
                 and end - timedelta(days=400) <= fact.period_end <= end)
                or (fact.concept in balances and fact.is_instant and fact.period_end == end)
                or (fact.concept in shares and fact.is_instant and fact.period_end >= end)]
    # Ambiguities outside any factor's contributing windows are not factor inputs.
    selected = facts_as_of(relevant, company_id=company_id, as_of=as_of)
    evidence = {}
    windows = {}
    reasons = []

    def instant(concept):
        used = [fact for fact in selected if fact.concept == concept and fact.is_instant
                and fact.period_end == end and fact.unit == 'USD']
        if not used:
            return None
        if len({fact.value for fact in used}) != 1:
            raise ValueError(f'Ambiguous {concept} at {end}')
        fact = used[-1]
        evidence[concept] = [asdict(fact)]
        if not fact.value.is_finite() or fact.value < 0:
            raise ValueError(f'Invalid negative/nonfinite {concept} at {end}')
        return fact.value

    def ttm(concept):
        try:
            metric = calculate_ttm(selected, concept, end)
            evidence[concept] = [asdict(term) for term in metric.terms]
            windows[concept] = (metric.period_start, metric.period_end)
            return metric.value
        except ValueError as error:
            reasons.append(str(error))
            return None

    raw = {name: instant(name) for name in ('cash', 'current_assets', 'current_liabilities', 'net_ppe',
        'total_debt', 'current_debt_total', 'long_term_debt_total', 'long_term_debt_current',
        'long_term_debt_noncurrent', 'short_term_borrowings')}
    total_debt = raw['total_debt']
    if total_debt is None:
        lt = raw['long_term_debt_total']
        if lt is None and raw['long_term_debt_current'] is not None and raw['long_term_debt_noncurrent'] is not None:
            lt = raw['long_term_debt_current'] + raw['long_term_debt_noncurrent']
        if lt is not None and raw['short_term_borrowings'] is not None:
            total_debt = lt + raw['short_term_borrowings']
        elif raw['current_debt_total'] is not None and raw['long_term_debt_noncurrent'] is not None:
            total_debt = raw['current_debt_total'] + raw['long_term_debt_noncurrent']
    lt_components = None
    if raw['long_term_debt_current'] is not None and raw['long_term_debt_noncurrent'] is not None:
        lt_components = raw['long_term_debt_current'] + raw['long_term_debt_noncurrent']
    if raw['long_term_debt_total'] is not None and lt_components is not None and raw['long_term_debt_total'] != lt_components:
        reasons.append('Long-term debt total conflicts with current plus noncurrent components')
    lt_check = raw['long_term_debt_total'] if raw['long_term_debt_total'] is not None else lt_components
    if raw['total_debt'] is not None and lt_check is not None and raw['short_term_borrowings'] is not None:
        if raw['total_debt'] != lt_check + raw['short_term_borrowings']:
            reasons.append('Combined total debt conflicts with complete debt components')
    short_debt = raw['current_debt_total']
    if short_debt is None:
        if total_debt is not None and raw['long_term_debt_noncurrent'] is not None:
            short_debt = total_debt - raw['long_term_debt_noncurrent']
        elif raw['short_term_borrowings'] is not None and raw['long_term_debt_current'] is not None:
            short_debt = raw['short_term_borrowings'] + raw['long_term_debt_current']
    if short_debt is not None and short_debt < 0:
        reasons.append('Derived short-term debt is negative')
    for name in ('cash', 'current_assets', 'current_liabilities', 'net_ppe'):
        if raw[name] is None:
            reasons.append(f'Missing {name} at {end}')
    if total_debt is None:
        reasons.append(f'Missing total debt and complete nonoverlapping debt components at {end}; no zero assumption')
    if short_debt is None:
        reasons.append(f'Missing short-term debt/current debt at {end}; no zero assumption')
    ebit, cfo, capex, revenue = [ttm(name) for name in
        ('operating_income', 'operating_cash_flow', 'capital_expenditure', 'revenue')]
    da = ttm('depreciation_amortization')
    if da is None:
        saved = reasons.pop()
        depreciation, amortization = ttm('depreciation'), ttm('amortization_intangibles')
        if depreciation is not None and amortization is not None:
            da = depreciation + amortization
        else:
            reasons.append(saved + '; separate depreciation and intangible amortization also incomplete')
    shares = [fact for fact in selected if fact.concept in ('cover_shares_outstanding', 'reported_shares_outstanding')
              and fact.is_instant and fact.unit == 'shares' and fact.period_end >= end]
    market_cap = None
    if not shares:
        reasons.append(f'No available actual shares outstanding dated at/after balance sheet {end}')
    else:
        share_date = max(fact.period_end for fact in shares)
        recent = [fact for fact in shares if fact.period_end == share_date]
        if len({fact.value for fact in recent}) != 1:
            reasons.append('Ambiguous issuer/class share counts; no single-class market cap substitution')
        else:
            share_count = recent[-1].value
            for action in splits:
                if share_date < action.event_date <= session and action.kind == 'split':
                    share_count *= action.value
            market_cap = share_count * price
            evidence['shares_outstanding'] = [asdict(recent[-1])]
    if ebit is not None and ebit <= 0:
        reasons.append('TTM EBIT is not positive')
    if revenue is not None and revenue <= 0:
        reasons.append('TTM revenue is not positive')
    if capex is not None and capex < 0:
        reasons.append('TTM CapEx must be positive-outflow convention')
    ce = None
    if all(raw[name] is not None for name in ('current_assets', 'cash', 'current_liabilities', 'net_ppe')) and short_debt is not None:
        ce = (raw['current_assets'] - raw['cash']) - (raw['current_liabilities'] - short_debt) + raw['net_ppe']
        if ce <= 0:
            reasons.append('Capital Employed is not positive: ' + str(ce))
    ebitda = None if ebit is None or da is None else ebit + da
    if ebitda is not None and ebitda <= 0:
        reasons.append('TTM EBITDA denominator is not positive')
    ev = None if market_cap is None or total_debt is None or raw['cash'] is None else market_cap + total_debt - raw['cash']
    if ev is not None and ev <= 0:
        reasons.append('Enterprise Value denominator is not positive')
    if market_cap is not None and market_cap <= 0:
        reasons.append('Market Cap denominator is not positive')
    if len(set(windows.values())) > 1:
        reasons.append('TTM metrics do not cover identical financial windows')
    if reasons:
        return None, sorted(set(reasons)), {'period_end': end, 'evidence': evidence}
    fcf = cfo - capex
    metrics = {'ebit_ttm': ebit, 'return_on_capital': ebit / ce,
               'fcf_margin': fcf / revenue, 'net_debt_to_ebitda': (total_debt - raw['cash']) / ebitda,
               'earnings_yield': ebit / ev, 'fcf_yield': fcf / market_cap}
    audit = {'period_end': end, 'capital_employed': ce, 'ebitda': ebitda, 'market_cap': market_cap,
             'enterprise_value': ev, 'total_debt': total_debt, 'short_term_debt': short_debt,
             'cash': raw['cash'], 'fcf': fcf, 'evidence': evidence}
    return metrics, [], audit


def as_traded_price(bar, splits):
    price = bar.close
    for action in splits:
        if action.kind == 'split' and action.event_date > bar.trading_date:
            price *= action.value
    return price


def candidate(member, *, facts, bars, splits, as_of, session, reference_dates):
    bars = completed_prices(bars, as_of)
    if member['sector'] in ('Financials', 'Utilities'):
        return None, ['Excluded sector: ' + member['sector']], {}
    try:
        factors = session_factors(bars, session, reference_dates)
        price = as_traded_price(bars[-1], splits)
        if price < 5:
            return None, ['Price below $5'], {}
        financial, reasons, audit = fundamental_factors(facts, company_id='sec:' + member['cik'],
            as_of=as_of, session=session, price=price, splits=splits)
        if reasons:
            return None, reasons, audit
        snapshot = CandidateSnapshot(symbol=member['ticker'], as_of=as_of, is_sp500_member=True,
            sector=member['sector'], price=price, completed_sessions=len(bars), **financial, **factors)
        return snapshot, [], audit
    except (ValueError, ArithmeticError) as error:
        return None, [type(error).__name__ + ': ' + str(error)], {}
