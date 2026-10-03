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
