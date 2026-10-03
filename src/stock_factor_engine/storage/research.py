from datetime import date, datetime

from .market import snapshot_prices_as_of
from .time import timestamp
from stock_factor_engine.providers.market.yahoo import PRICE_BASIS


def price_context(connection, *, security_id, as_of, snapshot_id=None):
    """One vintage, including split evidence beyond a retrospective price cutoff."""
    timestamp(as_of)
    if snapshot_id is None:
        row = connection.execute('''SELECT id FROM market_snapshots WHERE security_id=? AND retrieved_at<=?
            ORDER BY retrieved_at DESC, rowid DESC LIMIT 1''', (security_id, timestamp(as_of))).fetchone()
        if row is None:
            raise ValueError('No market snapshot downloaded by as-of')
        snapshot_id = row[0]
    snapshot, prices = snapshot_prices_as_of(connection, snapshot_id=snapshot_id, as_of=as_of)
    if snapshot['security_id'] != security_id:
        raise ValueError('Market snapshot belongs to a different security')
    if snapshot['price_basis'] != PRICE_BASIS:
        raise ValueError('Unsupported research price basis')
    last_date = connection.execute('''SELECT MAX(p.trading_date) FROM daily_prices p
        JOIN snapshot_prices s ON s.price_id=p.id WHERE s.snapshot_id=?''', (snapshot_id,)).fetchone()[0]
    if last_date is None:
        raise ValueError('Market snapshot contains no prices')
    splits = connection.execute('''SELECT a.event_date FROM corporate_actions a
        JOIN snapshot_actions s ON s.action_id=a.id WHERE s.snapshot_id=? AND a.kind='split' ''', (snapshot_id,)).fetchall()
    metadata = {'id': snapshot_id, 'retrieved_at': snapshot['retrieved_at'],
                'known_at_as_of': datetime.fromisoformat(snapshot['retrieved_at']) <= as_of,
                'source': snapshot['source'], 'price_basis': snapshot['price_basis'],
                'security_id': security_id, 'last_snapshot_price_date': last_date}
    return metadata, prices, date.fromisoformat(last_date), [date.fromisoformat(row[0]) for row in splits]
