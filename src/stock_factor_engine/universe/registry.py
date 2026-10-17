"""Curated research identities, not a historical investable universe."""

DEFAULT_SYMBOLS = ('MSFT', 'AAPL', 'GOOGL', 'AMZN', 'META')


def equity(cik, name, security_suffix='common', share_class='common', multiple_classes=False):
    return {'company_id': 'sec:' + cik, 'security_id': 'sec:' + cik + ':' + security_suffix,
            'instrument_type': 'EQUITY', 'security_type': 'common_stock', 'exchange': 'NASDAQ',
            'legal_name': name, 'cik': cik, 'requires_sec': True, 'share_class': share_class,
            'multiple_share_classes': multiple_classes}


IDENTITIES = {
    'MSFT': equity('0000789019', 'Microsoft Corporation'),
    'AAPL': equity('0000320193', 'Apple Inc.'),
    'GOOGL': equity('0001652044', 'Alphabet Inc.', 'class_a', 'A', True),
    'GOOG': equity('0001652044', 'Alphabet Inc.', 'class_c', 'C', True),
    'AMZN': equity('0001018724', 'Amazon.com, Inc.'),
    'META': equity('0001326801', 'Meta Platforms, Inc.', 'class_a', 'A', True),
    'SPY': {'company_id': 'sec:0000884394', 'security_id': 'sec:0000884394:fund',
            'instrument_type': 'ETF', 'security_type': 'etf', 'exchange': 'NYSE_ARCA',
            'legal_name': 'SPDR S&P 500 ETF Trust', 'cik': '0000884394', 'requires_sec': False,
            'share_class': 'fund', 'multiple_share_classes': False},
}

# Provider-scoped identities; these are market inputs, never stock candidates.
MARKET_SYMBOLS = ('SPY', 'RSP', 'HYG', 'LQD', '^VIX')
for symbol, name, exchange in (
    ('RSP', 'Invesco S&P 500 Equal Weight ETF', 'NYSE_ARCA'),
    ('HYG', 'iShares iBoxx USD High Yield Corporate Bond ETF', 'NYSE_ARCA'),
    ('LQD', 'iShares iBoxx USD Investment Grade Corporate Bond ETF', 'NYSE_ARCA'),
    ('^VIX', 'Cboe Volatility Index', 'CBOE'),
):
    is_index = symbol == '^VIX'
    IDENTITIES[symbol] = {
        'company_id': 'market:' + symbol, 'security_id': 'market:' + symbol,
        'instrument_type': 'INDEX' if is_index else 'ETF',
        'security_type': 'index' if is_index else 'etf', 'exchange': exchange,
        'legal_name': name, 'cik': None, 'requires_sec': False,
        'share_class': 'index' if is_index else 'fund', 'multiple_share_classes': False,
        'exchange_timezone': 'America/Chicago' if is_index else 'America/New_York',
    }


def selected_symbols(symbols):
    symbols = tuple(symbols)
    if not symbols or len(set(symbols)) != len(symbols):
        raise ValueError('Choose at least one symbol, without duplicates')
    if any(symbol not in IDENTITIES or not IDENTITIES[symbol]['requires_sec'] for symbol in symbols):
        raise ValueError('Universe symbols must be configured company equities')
    return symbols


def share_scope_reason(identity):
    if identity['multiple_share_classes']:
        return ('Issuer has multiple share classes; SEC aggregate shares/EPS are not mapped to '
                'individual classes and company capitalization cannot use one class price')
    return None
