from decimal import Decimal
from zoneinfo import ZoneInfo

from stock_factor_engine.factors.prices import benchmark_comparison, price_factors
from stock_factor_engine.fundamentals.balance import Result
from stock_factor_engine.fundamentals.company import company_profile
from stock_factor_engine.fundamentals.reporting import result_payload
from stock_factor_engine.fundamentals.valuation import valuation_metrics
from stock_factor_engine.storage.financials import financial_facts_as_of
from stock_factor_engine.storage.research import price_context
from stock_factor_engine.storage.time import timestamp
from .registry import IDENTITIES, selected_symbols, share_scope_reason

VALUATIONS = ('market_cap_estimate', 'pe_diluted_annual', 'price_to_sales', 'fcf_yield')
GROWTH = ('revenue_growth_yoy', 'operating_margin', 'fcf_margin')
FACTORS = ('momentum_12_1', 'volatility_252', 'max_drawdown_252', 'return_252')
EXCESS = ('momentum_12_1_excess', 'return_252_excess')


def unavailable(reason, unit='ratio'):
    return result_payload(Result(None, unit, 'unavailable', reason))


def comparison_report(connection, *, symbols, as_of):
    symbols = selected_symbols(symbols)
    timestamp(as_of)
    today = as_of.astimezone(ZoneInfo('America/New_York')).date()
    try:
        benchmark_meta, benchmark_prices, _, _ = price_context(
            connection, security_id=IDENTITIES['SPY']['security_id'], as_of=as_of)
        benchmark_error = None
    except ValueError as error:
        benchmark_meta, benchmark_prices, benchmark_error = None, [], str(error)
    rows = []
    for symbol in symbols:
        identity = IDENTITIES[symbol]
        row = {'symbol': symbol, 'company_id': identity['company_id'], 'security_id': identity['security_id'],
               'share_class': identity['share_class'], 'share_scope_warning': share_scope_reason(identity),
               'snapshot': None, 'financial_period_end': None, 'metrics': {}, 'errors': {}}
        metrics = row['metrics']
        try:
            meta, prices, horizon, splits = price_context(connection, security_id=identity['security_id'], as_of=as_of)
            row['snapshot'] = meta
            factors = price_factors(prices, as_of=as_of)
            metrics.update({key: value.payload() for key, value in factors.items()})
            if benchmark_error:
                metrics.update({key: unavailable('SPY benchmark: ' + benchmark_error) for key in EXCESS})
            else:
                _, _, excess = benchmark_comparison(prices, benchmark_prices, as_of=as_of)
                metrics.update({key: value.payload() for key, value in excess.items()})
        except ValueError as error:
            row['errors']['prices'] = str(error)
            meta, prices, horizon, splits = None, [], today, []
            metrics.update({key: unavailable(str(error)) for key in FACTORS + EXCESS})
        facts = []
        try:
            facts = financial_facts_as_of(connection, company_id=identity['company_id'], as_of=as_of)
            # Complete financial periods must precede the price being compared.
            financial_cutoff = prices[-1].trading_date if prices else today
            facts = [fact for fact in facts if fact.period_end <= financial_cutoff]
            end, profile = company_profile(facts, company_id=identity['company_id'], as_of=as_of)
            row['financial_metrics'] = {key: result_payload(value) for key, value in profile.items()}
            row['financial_period_end'] = end
            for key in GROWTH:
                metrics[key] = (unavailable('Financial period more than 180 days old') if
                                (financial_cutoff - end).days > 180 else result_payload(profile[key]))
        except ValueError as error:
            row['errors']['financials'] = str(error)
            metrics.update({key: unavailable(str(error)) for key in GROWTH})
        if meta is None:
            metrics.update({key: unavailable(row['errors'].get('prices', 'Missing price context')) for key in VALUATIONS})
        else:
            try:
                end, valuation = valuation_metrics(facts, prices, company_id=identity['company_id'], as_of=as_of,
                                                   price_basis=meta['price_basis'], snapshot_last_date=horizon,
                                                   split_dates=splits, share_scope_reason=share_scope_reason(identity))
                row['valuation_inputs'] = {key: result_payload(value) for key, value in valuation.items()}
                metrics.update({key: result_payload(valuation[key]) for key in VALUATIONS})
            except ValueError as error:
                row['errors']['valuation'] = str(error)
                metrics.update({key: unavailable(str(error)) for key in VALUATIONS})
        count = sum(metric['status'] == 'available' for metric in metrics.values())
        row['status'] = 'available' if count == len(metrics) else 'partial' if count else 'unavailable'
        rows.append(row)
    return {'as_of': timestamp(as_of), 'registry_version': 'research-universe-v0.1',
            'universe': 'Curated present-day research list; not a point-in-time historical universe',
            'benchmark': {'symbol': 'SPY', 'description': 'ETF adjusted market-price proxy',
                          'snapshot': benchmark_meta, 'error': benchmark_error}, 'companies': rows}


def markdown_table(report):
    columns = [('Growth', 'revenue_growth_yoy', True), ('Op. margin', 'operating_margin', True),
               ('FCF margin', 'fcf_margin', True), ('P/E annual', 'pe_diluted_annual', False),
               ('P/S', 'price_to_sales', False), ('FCF yield', 'fcf_yield', True),
               ('Mom. 12-1', 'momentum_12_1', True), ('Vol. 252', 'volatility_252', True),
               ('Drawdown', 'max_drawdown_252', True), ('Excess 252', 'return_252_excess', True)]
    lines = [f"As-of: {report['as_of']}", '',
             '| Symbol | Price date | Fiscal end | ' + ' | '.join(column[0] for column in columns) + ' |',
             '| ' + ' | '.join('---' for _ in range(len(columns) + 3)) + ' |']
    reasons = []
    for row in report['companies']:
        cells = [row['symbol'], str(row['valuation_inputs']['price']['inputs']['price_date'])
                 if row.get('valuation_inputs') else 'NA', str(row['financial_period_end'] or 'NA')]
        for label, key, percent in columns:
            metric = row['metrics'][key]
            if metric['status'] == 'available':
                value = Decimal(str(metric['value']))
                cells.append(f'{value * 100:.2f}%' if percent else f'{value:.2f}')
            else:
                cells.append('NA')
                reasons.append(f"- {row['symbol']} / {label}: {'; '.join(input_reasons(metric))}")
        lines.append('| ' + ' | '.join(cells) + ' |')
    lines += ['', 'NA means unavailable; each reason is listed below. Excess is a percentage-point difference.',
              'Market capitalization is a reported-share estimate. Annual P/E requires a matching annual EPS window.',
              report['universe'], ''] + reasons
    return '\n'.join(lines) + '\n'


def input_reasons(metric):
    reasons = []
    for value in metric.get('inputs', {}).values():
        if isinstance(value, dict) and value.get('status') == 'unavailable':
            reasons.extend(input_reasons(value))
    return list(dict.fromkeys(reasons)) or [metric.get('reason') or 'Missing input']
