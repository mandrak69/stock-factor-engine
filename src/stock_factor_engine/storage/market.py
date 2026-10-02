from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from stock_factor_engine.models.market import DailyPrice, total_return


def snapshot_prices_as_of(connection, *, snapshot_id: str, as_of: datetime):
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError('as_of must be timezone-aware')
    snapshot = connection.execute('SELECT * FROM market_snapshots WHERE id=?', (snapshot_id,)).fetchone()
    if snapshot is None:
        raise ValueError('Unknown market snapshot')
    cutoff = as_of.astimezone(ZoneInfo('America/New_York')).date().isoformat()
    rows = connection.execute('''SELECT p.* FROM daily_prices p JOIN snapshot_prices s ON s.price_id=p.id
        WHERE s.snapshot_id=? AND p.trading_date<? ORDER BY p.trading_date''', (snapshot_id, cutoff)).fetchall()
    bars = [DailyPrice(date.fromisoformat(row['trading_date']),
                      *(Decimal(row[key]) for key in ('open_decimal', 'high_decimal', 'low_decimal', 'close_decimal', 'adjusted_close_decimal')),
                      row['volume']) for row in rows]
    return snapshot, bars


def market_report(connection, *, snapshot_id: str, as_of: datetime):
    snapshot, bars = snapshot_prices_as_of(connection, snapshot_id=snapshot_id, as_of=as_of)
    cutoff = as_of.astimezone(ZoneInfo('America/New_York')).date().isoformat()
    if len(bars) < 2:
        raise ValueError('At least two completed-session prices are needed')
    actions = connection.execute('''SELECT a.* FROM corporate_actions a JOIN snapshot_actions s ON s.action_id=a.id
        WHERE s.snapshot_id=? AND a.event_date<? ORDER BY a.event_date, a.kind''', (snapshot_id, cutoff)).fetchall()
    price_by_date = {bar.trading_date: index for index, bar in enumerate(bars)}
    examples = []
    for action in actions:
        index = price_by_date.get(date.fromisoformat(action['event_date']))
        if index is not None and index > 0:
            previous, current = bars[index - 1:index + 1]
            examples.append({'date': action['event_date'], 'kind': action['kind'], 'value': action['value_decimal'],
                             'provider_close_before': str(previous.close), 'provider_close_after': str(current.close),
                             'adjusted_return': str(total_return(previous, current))})
    # Flag obvious missing stretches without pretending to supply an exchange calendar.
    gaps = [{'after': str(a.trading_date), 'before': str(b.trading_date)}
            for a, b in zip(bars, bars[1:]) if b.trading_date - a.trading_date > timedelta(days=7)]
    return {'snapshot_id': snapshot_id, 'security_id': snapshot['security_id'],
            'as_of': as_of.isoformat(), 'retrieved_at': snapshot['retrieved_at'],
            'snapshot_known_at_as_of': datetime.fromisoformat(snapshot['retrieved_at']) <= as_of,
            'price_basis': snapshot['price_basis'], 'bars': len(bars),
            'first_date': str(bars[0].trading_date), 'last_date': str(bars[-1].trading_date),
            'last_provider_close': str(bars[-1].close), 'last_adjusted_close': str(bars[-1].adjusted_close),
            'last_session_adjusted_return': str(total_return(bars[-2], bars[-1])),
            'dividends': sum(row['kind'] == 'dividend' for row in actions),
            'splits': sum(row['kind'] == 'split' for row in actions),
            'long_calendar_gaps': gaps, 'corporate_action_examples': examples[-12:],
            'split_examples': [example for example in examples if example['kind'] == 'split']}
