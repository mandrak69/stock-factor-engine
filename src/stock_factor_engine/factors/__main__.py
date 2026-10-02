import argparse
from datetime import datetime
import json
from pathlib import Path
import sqlite3

from stock_factor_engine.storage.market import snapshot_prices_as_of
from stock_factor_engine.storage.time import timestamp
from stock_factor_engine.providers.market.identities import IDENTITIES
from stock_factor_engine.providers.market.yahoo import PRICE_BASIS
from .prices import benchmark_comparison


def main():
    parser = argparse.ArgumentParser(description='Explain Microsoft price factors against the SPY ETF proxy.')
    parser.add_argument('--database', type=Path, default=Path('data/engine.sqlite'))
    parser.add_argument('--as-of', required=True, type=datetime.fromisoformat)
    parser.add_argument('--asset-snapshot')
    parser.add_argument('--benchmark-snapshot')
    args = parser.parse_args()
    try:
        timestamp(args.as_of)
    except ValueError as error:
        parser.error(str(error))
    connection = sqlite3.connect(args.database.resolve().as_uri() + '?mode=ro', uri=True)
    connection.row_factory = sqlite3.Row
    try:
        snapshots, bars = {}, {}
        for symbol, explicit in [('MSFT', args.asset_snapshot), ('SPY', args.benchmark_snapshot)]:
            security_id = IDENTITIES[symbol]['security_id']
            if explicit is None:
                row = connection.execute('''SELECT id FROM market_snapshots WHERE security_id=?
                    AND retrieved_at<=? ORDER BY retrieved_at DESC, rowid DESC LIMIT 1''',
                    (security_id, timestamp(args.as_of))).fetchone()
                if row is None:
                    parser.error(f'No {symbol} snapshot downloaded by as-of; import it or pass an explicit retrospective snapshot')
                explicit = row[0]
            snapshot, prices = snapshot_prices_as_of(connection, snapshot_id=explicit, as_of=args.as_of)
            if snapshot['security_id'] != security_id or snapshot['price_basis'] != PRICE_BASIS:
                parser.error(f'Incorrect identity or price basis for {symbol} snapshot')
            snapshots[symbol] = {'snapshot_id': explicit, 'retrieved_at': snapshot['retrieved_at'],
                                 'known_at_as_of': datetime.fromisoformat(snapshot['retrieved_at']) <= args.as_of,
                                 'price_basis': snapshot['price_basis'], 'source': snapshot['source']}
            bars[symbol] = prices
        asset, benchmark, comparison = benchmark_comparison(bars['MSFT'], bars['SPY'], as_of=args.as_of)
        report = {'as_of': timestamp(args.as_of), 'strategy_factor_version': 'price-research-v0.1',
                  'benchmark': 'SPY adjusted market-price ETF proxy; not the official S&P 500 Total Return index',
                  'snapshots': snapshots, 'asset_factors': {k: v.payload() for k, v in asset.items()},
                  'benchmark_factors': {k: v.payload() for k, v in benchmark.items()},
                  'comparison': {k: v.payload() for k, v in comparison.items()}}
        print(json.dumps(report, default=str, indent=2))
    finally:
        connection.close()


if __name__ == '__main__':
    main()
