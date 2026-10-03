from stock_factor_engine.providers.market.ingestion import ingest_market
from stock_factor_engine.providers.sec.ingestion import ingest_company
from .registry import IDENTITIES, selected_symbols


def ingest_universe(connection, data_dir, symbols, *, sec_client=None, market_only=False,
                    include_benchmark=True, progress=None):
    """Sequential provider requests; one failed company does not erase others."""
    symbols = selected_symbols(symbols)
    if not market_only and sec_client is None:
        raise ValueError('SEC client with contact User-Agent is required')
    rows, companies = [], {}
    for symbol in symbols + (('SPY',) if include_benchmark else ()):
        identity = IDENTITIES[symbol]
        row = {'symbol': symbol, 'company_id': identity['company_id'], 'security_id': identity['security_id']}
        if progress:
            progress(symbol)
        if identity['requires_sec'] and not market_only:
            company_id = identity['company_id']
            if company_id not in companies:
                try:
                    companies[company_id] = {'status': 'succeeded', 'result': ingest_company(
                        connection, data_dir, identity['cik'], sec_client)}
                except Exception as error:
                    companies[company_id] = {'status': 'failed', 'error': str(error)}
            row['sec'] = companies[company_id]
        else:
            row['sec'] = {'status': 'skipped', 'reason': 'market-only' if identity['requires_sec'] else 'benchmark ETF'}
        try:
            row['market'] = {'status': 'succeeded', 'result': ingest_market(connection, data_dir, symbol=symbol)}
        except Exception as error:
            row['market'] = {'status': 'failed', 'error': str(error)}
        row['status'] = 'failed' if any(row[key]['status'] == 'failed' for key in ('sec', 'market')) else 'succeeded'
        rows.append(row)
    return {'registry_version': 'research-universe-v0.1',
            'status': 'partial_failure' if any(row['status'] == 'failed' for row in rows) else 'succeeded',
            'instruments': rows}
