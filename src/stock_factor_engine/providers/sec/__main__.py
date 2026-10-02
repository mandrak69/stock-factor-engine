import argparse
import json
import os
from pathlib import Path

from stock_factor_engine.storage import connect_database
from .client import SecClient
from .ingestion import ingest_company
from .replay import ReplayClient


def main():
    parser = argparse.ArgumentParser(description='Import SEC filings and mapped US-GAAP facts.')
    parser.add_argument('--cik', default='0000789019', help='Microsoft by default')
    parser.add_argument('--data-dir', type=Path, default=Path('data'))
    parser.add_argument('--replay-run', help='Replay archived responses without network access')
    args = parser.parse_args()
    client = None
    if not args.replay_run:
        try:
            client = SecClient(os.environ.get('SEC_USER_AGENT', ''))
        except ValueError as error:
            parser.error(str(error) + '; set SEC_USER_AGENT')
    db = connect_database(args.data_dir / 'engine.sqlite')
    try:
        if args.replay_run:
            client = ReplayClient(db, args.data_dir, args.replay_run)
        print(json.dumps(ingest_company(db, args.data_dir, args.cik, client), indent=2))
    finally:
        db.close()


if __name__ == '__main__':
    main()
