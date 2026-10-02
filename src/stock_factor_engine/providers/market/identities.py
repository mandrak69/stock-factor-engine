"""Explicit issuer/instrument identities; no ticker-based auto-discovery."""

IDENTITIES = {
    'MSFT': {'company_id': 'sec:0000789019', 'security_id': 'sec:0000789019:common',
             'instrument_type': 'EQUITY', 'security_type': 'common_stock', 'exchange': 'NASDAQ',
             'legal_name': 'Microsoft Corporation', 'cik': '0000789019', 'requires_sec': True},
    'SPY': {'company_id': 'sec:0000884394', 'security_id': 'sec:0000884394:fund',
            'instrument_type': 'ETF', 'security_type': 'etf', 'exchange': 'NYSE_ARCA',
            'legal_name': 'SPDR S&P 500 ETF Trust', 'cik': '0000884394', 'requires_sec': False},
}
