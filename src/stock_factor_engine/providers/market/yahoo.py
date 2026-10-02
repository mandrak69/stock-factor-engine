from datetime import UTC, datetime
from decimal import Decimal
import json
import re
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from stock_factor_engine.models.market import CorporateAction, DailyPrice
from .identities import IDENTITIES


SOURCE = 'yahoo_chart'
PRICE_BASIS = 'provider_split_adjusted_ohlc_dividend_adjusted_close'


def fetch(symbol: str):
    if not re.fullmatch(r'[A-Z0-9.-]{1,20}', symbol):
        raise ValueError('Invalid ticker symbol')
    url = f'https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?' + urlencode({
        'period1': 0, 'period2': int(datetime.now(UTC).timestamp()), 'interval': '1d',
        'events': 'div,splits', 'includeAdjustedClose': 'true'})
    request = Request(url, headers={'User-Agent': 'stock-factor-engine/0.1', 'Accept': 'application/json'})
    with urlopen(request, timeout=30) as response:
        content = response.read()
    return content, datetime.now(UTC), url


def parse(content: bytes, symbol: str, retrieved_at: datetime):
    if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
        raise ValueError('retrieved_at must be timezone-aware')
    payload = json.loads(content, parse_float=Decimal)
    chart = payload['chart']
    if chart.get('error') or not chart.get('result') or len(chart['result']) != 1:
        raise ValueError('Yahoo did not return one valid price series')
    result = chart['result'][0]
    meta = result['meta']
    identity = IDENTITIES.get(symbol)
    if identity is None or meta.get('symbol') != symbol or meta.get('currency') != 'USD' or meta.get('instrumentType') != identity['instrument_type']:
        raise ValueError('Only explicitly configured matching USD instruments are supported')
    if meta.get('exchangeTimezoneName') != 'America/New_York':
        raise ValueError('Only US Eastern exchange dates are supported in v0.1')
    timezone = ZoneInfo('America/New_York')
    today = retrieved_at.astimezone(timezone).date()
    timestamps = result['timestamp']
    quotes = result['indicators']['quote'][0]
    adjusted = result['indicators']['adjclose'][0]['adjclose']
    arrays = [quotes[name] for name in ('open', 'high', 'low', 'close', 'volume')] + [adjusted]
    if any(len(values) != len(timestamps) for values in arrays):
        raise ValueError('Price columns have different lengths')
    bars, actions, rejected = [], [], []
    for epoch, values in zip(timestamps, zip(*arrays)):
        trading_date = datetime.fromtimestamp(epoch, timezone).date()
        # Exclude all current-session rows, including partial intraday candles.
        if trading_date >= today:
            continue
        try:
            opening, high, low, close, volume, adj = values
            bars.append(DailyPrice(trading_date, *(Decimal(str(value)) for value in (opening, high, low, close, adj)), volume))
        except (ValueError, TypeError, ArithmeticError) as error:
            rejected.append({'kind': 'bar', 'date': str(trading_date), 'reason': str(error)})
    if not bars or len({bar.trading_date for bar in bars}) != len(bars):
        raise ValueError('Empty series or duplicate trading dates')
    dates = {bar.trading_date for bar in bars}
    for event_type, kind in [('dividends', 'dividend'), ('splits', 'split')]:
        for event in result.get('events', {}).get(event_type, {}).values():
            event_date = datetime.fromtimestamp(event['date'], timezone).date()
            if event_date >= today:
                continue
            if event_date not in dates:
                raise ValueError(f'Corporate action has no valid bar at {event_date}')
            amount = Decimal(str(event['amount'])) if kind == 'dividend' else Decimal(str(event['numerator'])) / Decimal(str(event['denominator']))
            actions.append(CorporateAction(event_date, kind, amount))
    if len({(action.event_date, action.kind) for action in actions}) != len(actions):
        raise ValueError('Duplicate corporate actions')
    return sorted(bars, key=lambda bar: bar.trading_date), sorted(actions, key=lambda action: (action.event_date, action.kind)), rejected, meta
