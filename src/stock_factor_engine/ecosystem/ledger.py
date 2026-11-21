"""Analytical boundary accounts, not statutory consolidation of unrelated issuers.

One row represents one economic transaction, not two accounting legs. Unknown
counterparties remain unresolved. Announced amounts never enter these ledgers.
"""
from datetime import date
from decimal import Decimal as D

from .model import instant


CASH_KINDS = {'operating', 'capex', 'financing', 'distribution', 'investing_other'}


def money(value):
    result = D(str(value))
    if not result.is_finite() or result < 0:
        raise ValueError('Amounts must be finite, nonnegative USD magnitudes')
    return result


def boundary(payer, payee, members):
    if payer is None or payee is None:
        return 'unresolved'
    if payer == payee:
        raise ValueError('Self/alias transactions must be removed before aggregation')
    if payer in members and payee in members:
        return 'internal'
    if payer in members:
        return 'outflow'
    if payee in members:
        return 'inflow'
    raise ValueError('Transaction does not touch the selected group')


def calculate_accounts(payload, *, members, as_of, period_start, period_end):
    """Fail closed until all members attest complete cash and recognized-sales ledgers.

    Cash inputs must include every external cash category, plus reconciliation of
    opening cash + net cash + FX to closing cash. Category reclassification of
    internally manufactured fixed assets requires a separate evidenced adjustment.
    """
    cutoff = instant(as_of)
    start, end = date.fromisoformat(period_start), date.fromisoformat(period_end)
    if start > end or end > cutoff.date():
        raise ValueError('Invalid or future accounting period')
    members = set(members)
    if not members:
        raise ValueError('A nonempty economic-group perimeter is required')
    totals = {kind: D(0) for kind in CASH_KINDS}
    counts = {kind: 0 for kind in CASH_KINDS}
    cash_rows, sales_rows, excluded = [], [], []
    keys = set()
    external = set(payload.get('external_counterparties', []))
    if members & external:
        raise ValueError('A counterparty cannot be both internal and external')
    for ledger_name in ('cash', 'sales'):
        for row in payload.get(ledger_name, []):
            key = (ledger_name, row['economic_id'])
            if key in keys:
                raise ValueError('Duplicate economic transaction: ' + str(key))
            keys.add(key)
            amount = money(row['amount_usd'])
            if row.get('currency') != 'USD' or not row.get('source_urls') or any(
                    not url.startswith('https://') for url in row['source_urls']):
                raise ValueError('USD amounts and primary evidence URLs are required')
            available = instant(row['available_at'])
            rstart, rend = date.fromisoformat(row['period_start']), date.fromisoformat(row['period_end'])
            if rstart > rend or rend > available.date():
                raise ValueError('Evidence cannot precede the observed transaction period')
            if available > cutoff or rstart < start or rend > end:
                excluded.append({'ledger': ledger_name, 'id': row['economic_id'], 'reason': 'outside period or unavailable at cutoff'})
                continue
            if ledger_name == 'cash' and row.get('basis') != 'settled_cash':
                raise ValueError('Only actual settled cash belongs in cash ledger')
            if ledger_name == 'sales' and row.get('basis') != 'recognized_revenue':
                raise ValueError('Only recognized sales belong in revenue ledger')
            unknown = any(party not in members | external for party in (row.get('payer'), row.get('payee')))
            route = 'unresolved' if unknown else boundary(row.get('payer'), row.get('payee'), members)
            result = {**row, 'boundary': route, 'eliminated_usd': amount if route == 'internal' else D(0)}
            if ledger_name == 'cash':
                kind = row['category']
                if kind not in CASH_KINDS:
                    raise ValueError('Unknown cash category')
                cash_rows.append(result)
                if route in ('inflow', 'outflow'):
                    totals[kind] += amount * (1 if route == 'inflow' else -1)
                    counts[kind] += 1
            else:
                if row.get('payee') not in members:
                    raise ValueError('Sales ledger must describe a seller inside the group')
                sales_rows.append(result)
    gaps = []
    perimeter_review = payload.get('perimeter_review') or {}
    if not (perimeter_review.get('complete') is True and perimeter_review.get('source_urls')
            and all(u.startswith('https://') for u in perimeter_review['source_urls'])
            and instant(perimeter_review['available_at']) <= cutoff
            and perimeter_review.get('period_start') == period_start
            and perimeter_review.get('period_end') == period_end):
        gaps.append('Complete nonoverlapping legal/control perimeter has not been reconciled')
    for entity in sorted(members):
        for ledger_name in ('cash', 'sales'):
            matches = [row for row in payload.get('coverage', []) if row.get('entity_id') == entity
                       and row.get('ledger') == ledger_name and row.get('period_start') == period_start
                       and row.get('period_end') == period_end and row.get('complete') is True
                       and row.get('source_urls') and all(url.startswith('https://') for url in row['source_urls'])
                       and instant(row['available_at']) <= cutoff]
            if len(matches) != 1:
                gaps.append(entity + ': missing unique evidenced complete ' + ledger_name + ' reconciliation')
    unresolved = [row['economic_id'] for row in cash_rows + sales_rows if row['boundary'] == 'unresolved']
    gaps += ['Unresolved counterparty: ' + key for key in unresolved]
    cash_net = sum(totals.values(), D(0))
    reconciliation = payload.get('cash_reconciliation')
    if reconciliation:
        if (not reconciliation.get('source_urls') or any(not u.startswith('https://') for u in reconciliation['source_urls'])
                or instant(reconciliation['available_at']) > cutoff
                or reconciliation.get('period_start') != period_start or reconciliation.get('period_end') != period_end):
            gaps.append('Cash reconciliation evidence/period unavailable')
        else:
            opening = money(reconciliation['opening_usd'])
            closing = money(reconciliation['closing_usd'])
            fx = D(str(reconciliation['fx_usd']))
            if not fx.is_finite() or opening + cash_net + fx != closing:
                gaps.append('Opening cash + external net cash + FX does not equal closing cash')
    else:
        gaps.append('Missing opening/closing cash and FX reconciliation')
    if excluded:
        gaps.append('Ledger includes excluded observations; refresh period/cutoff reconciliation')
    complete = not gaps
    category_review = payload.get('category_review') or {}
    categories_complete = bool(category_review.get('complete') is True
        and category_review.get('source_urls')
        and all(u.startswith('https://') for u in category_review['source_urls'])
        and instant(category_review['available_at']) <= cutoff
        and category_review.get('period_start') == period_start and category_review.get('period_end') == period_end)
    gross_capex = sum((money(r['amount_usd']) for r in cash_rows
                      if r['boundary'] == 'outflow' and r['category'] == 'capex'), D(0))
    classified = complete and categories_complete
    external_sales = [row for row in sales_rows if row['boundary'] == 'inflow']
    observed_revenue = sum((money(row['amount_usd']) for row in external_sales), D(0)) if external_sales else None
    return {'status': 'complete' if complete else 'unavailable', 'gaps': gaps, 'excluded': excluded,
            'cash_eliminations': cash_rows, 'sales_eliminations': sales_rows,
            'documented_external_cash_by_category_usd': {k: totals[k] if counts[k] else None for k in sorted(totals)},
            'documented_external_revenue_usd': observed_revenue,
            'external_revenue_usd': (observed_revenue or D(0)) if complete else None,
            'external_net_cash_usd': cash_net if complete else None,
            'external_operating_cash_usd': totals['operating'] if classified else None,
            'external_gross_capex_usd': gross_capex if classified else None,
            'operating_minus_gross_capex_usd': totals['operating'] - gross_capex if classified else None,
            'self_funding_coverage': totals['operating'] / gross_capex if classified and gross_capex > 0 else None,
            'financing_gap_usd': gross_capex - totals['operating'] if classified else None,
            'cash_flow_category_status': 'reviewed' if categories_complete else 'requires review of internal asset production, leases and category reclassifications',
            'profit_usd': None,
            'profit_status': 'unavailable: needs costs, internal asset margins, depreciation, tax and equity-method eliminations'}


def internal_asset_adjustment(*, transfer_price, group_cost, useful_life_years,
                              elapsed_years=0, residual_value=0):
    """Simple straight-line sensitivity only; not an inferred company estimate."""
    price, cost, residual = map(money, (transfer_price, group_cost, residual_value))
    life, elapsed = D(str(useful_life_years)), D(str(elapsed_years))
    if not life.is_finite() or life <= 0 or not elapsed.is_finite() or not 0 <= elapsed <= life:
        raise ValueError('Invalid useful life or elapsed period')
    if residual > min(price, cost):
        raise ValueError('Residual value exceeds asset cost')
    margin = price - cost
    return {'original_internal_margin_usd': margin,
            'remaining_internal_margin_usd': margin * (1 - elapsed / life),
            'annual_depreciation_reduction_usd': margin / life,
            'group_net_book_value_usd': cost - (cost - residual) * elapsed / life}
