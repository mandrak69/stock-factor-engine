import argparse
from datetime import datetime
import json
import sqlite3
from pathlib import Path

from stock_factor_engine.storage import connect_database
from stock_factor_engine.storage.market import market_report
from .ingestion import ingest_market, replay_response
from .identities import IDENTITIES


def main():
    parser = argparse.ArgumentParser(description='Import or inspect configured daily prices and corporate actions.')
    parser.add_argument('--symbol', choices=IDENTITIES, default='MSFT')
    parser.add_argument('--data-dir', type=Path, default=Path('data'))
    parser.add_argument('--replay-snapshot')
    parser.add_argument('--report-snapshot')
    parser.add_argument('--as-of', type=datetime.fromisoformat)
    args = parser.parse_args()
    if args.report_snapshot and (args.as_of is None or args.as_of.tzinfo is None):
        parser.error('--report-snapshot requires timezone-aware --as-of')
    if args.report_snapshot and args.replay_snapshot:
        parser.error('Choose report or replay, not both')
    if args.report_snapshot:
        connection = sqlite3.connect((args.data_dir / 'engine.sqlite').resolve().as_uri() + '?mode=ro', uri=True)
        connection.row_factory = sqlite3.Row
    else:
        connection = connect_database(args.data_dir / 'engine.sqlite')
    try:
        if args.report_snapshot:
            result = market_report(connection, snapshot_id=args.report_snapshot, as_of=args.as_of)
        else:
            response = replay_response(connection, args.data_dir, args.replay_snapshot) if args.replay_snapshot else None
            result = ingest_market(connection, args.data_dir, symbol=args.symbol, response=response)
        print(json.dumps(result, indent=2))
    finally:
        connection.close()


if __name__ == '__main__':
    main()
