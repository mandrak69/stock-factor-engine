import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import sqlite3
import sys

from stock_factor_engine.providers.sec.client import SecClient
from stock_factor_engine.storage import connect_database
from stock_factor_engine.storage.time import timestamp
from .ingestion import ingest_universe
from .registry import DEFAULT_SYMBOLS, IDENTITIES, selected_symbols
from .report import comparison_report, markdown_table


def main():
    parser = argparse.ArgumentParser(description='Import and compare a curated company research universe.')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('list', help='Inspect explicit company/security identities')
    ingest = commands.add_parser('ingest', help='Import SEC, company prices and SPY sequentially')
    ingest.add_argument('--symbols', nargs='+', default=DEFAULT_SYMBOLS)
    ingest.add_argument('--data-dir', type=Path, default=Path('data'))
    ingest.add_argument('--market-only', action='store_true', help='Refresh prices for previously imported SEC companies')
    ingest.add_argument('--skip-benchmark', action='store_true')
    report = commands.add_parser('report', help='Compare available data without downloading')
    report.add_argument('--symbols', nargs='+', default=DEFAULT_SYMBOLS)
    report.add_argument('--database', type=Path, default=Path('data/engine.sqlite'))
    report.add_argument('--as-of', required=True, type=datetime.fromisoformat)
    report.add_argument('--format', choices=['table', 'json'], default='table')
    report.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.command == 'list':
        print(json.dumps({'defaults': DEFAULT_SYMBOLS, 'instruments': IDENTITIES}, indent=2))
        return
    try:
        selected_symbols(args.symbols)
        if args.command == 'report':
            timestamp(args.as_of)
    except ValueError as error:
        parser.error(str(error))
    if args.command == 'ingest':
        try:
            client = None if args.market_only else SecClient(os.environ.get('SEC_USER_AGENT', ''))
        except ValueError as error:
            parser.error(str(error) + '; set SEC_USER_AGENT (contact email is not saved to Git)')
        connection = connect_database(args.data_dir / 'engine.sqlite')
        try:
            result = ingest_universe(connection, args.data_dir, args.symbols, sec_client=client,
                                     market_only=args.market_only, include_benchmark=not args.skip_benchmark,
                                     progress=lambda symbol: print(f'Importing {symbol}...', file=sys.stderr, flush=True))
            print(json.dumps(result, default=str, indent=2))
        finally:
            connection.close()
        if result['status'] != 'succeeded':
            raise SystemExit(1)
        return
    connection = sqlite3.connect(args.database.resolve().as_uri() + '?mode=ro', uri=True)
    connection.row_factory = sqlite3.Row
    try:
        result = comparison_report(connection, symbols=args.symbols, as_of=args.as_of)
    finally:
        connection.close()
    content = markdown_table(result) if args.format == 'table' else json.dumps(result, default=str, indent=2) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content, encoding='utf-8')
    else:
        print(content, end='')


if __name__ == '__main__':
    main()
