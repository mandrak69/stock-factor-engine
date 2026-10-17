import argparse
from datetime import date, datetime
from decimal import Decimal
import json
from pathlib import Path
import sqlite3

from stock_factor_engine.providers.market.ingestion import ingest_market
from stock_factor_engine.storage import connect_database
from stock_factor_engine.universe.registry import MARKET_SYMBOLS
from .report import regime_report
from .membership import JsonMembershipProvider
from .model import VixFrontMonth


def main(argv=None):
    parser = argparse.ArgumentParser(description='Market-regime inputs: ingest and fail-closed report')
    commands = parser.add_subparsers(dest='command', required=True)
    ingest = commands.add_parser('ingest')
    ingest.add_argument('--data-dir', type=Path, default=Path('data'))
    ingest.add_argument('--symbols', nargs='+', choices=MARKET_SYMBOLS, default=MARKET_SYMBOLS)
    report = commands.add_parser('report')
    report.add_argument('--database', type=Path, default=Path('data/engine.sqlite'))
    report.add_argument('--as-of', type=datetime.fromisoformat, required=True)
    report.add_argument('--constituents-json', type=Path,
                        help='Independently verified complete membership for the exact signal session')
    report.add_argument('--vix-front-month', type=Decimal)
    report.add_argument('--vix-session', type=date.fromisoformat)
    report.add_argument('--vix-contract')
    report.add_argument('--vix-expiry', type=date.fromisoformat)
    report.add_argument('--vix-source')
    args = parser.parse_args(argv)
    if args.command == 'report' and (args.as_of.tzinfo is None or args.as_of.utcoffset() is None):
        parser.error('--as-of must be timezone-aware')
    if args.command == 'ingest' and len(set(args.symbols)) != len(args.symbols):
        parser.error('--symbols must not contain duplicates')
    membership_provider = front_month = None
    if args.command == 'report':
        vx_values = (args.vix_front_month, args.vix_session, args.vix_contract, args.vix_expiry, args.vix_source)
        if any(value is not None for value in vx_values) and any(value is None for value in vx_values):
            parser.error('VX input requires price, session, contract, expiry and source together')
        try:
            if args.constituents_json:
                membership_provider = JsonMembershipProvider(args.constituents_json)
            if args.vix_front_month is not None:
                front_month = VixFrontMonth(args.vix_session, args.vix_front_month, args.vix_contract,
                                           args.vix_expiry, args.vix_source)
        except (ValueError, KeyError, OSError) as error:
            parser.error(str(error))
    if args.command == 'ingest':
        connection = connect_database(args.data_dir / 'engine.sqlite')
    else:
        connection = sqlite3.connect(args.database.resolve().as_uri() + '?mode=ro', uri=True)
        connection.row_factory = sqlite3.Row
    try:
        if args.command == 'ingest':
            result = {symbol: ingest_market(connection, args.data_dir, symbol=symbol) for symbol in args.symbols}
        else:
            try:
                result = regime_report(connection, as_of=args.as_of, membership_provider=membership_provider,
                                       vix_front_month=front_month)
            except ValueError as error:
                parser.error(str(error))
        print(json.dumps(result, indent=2, default=str))
        return 0
    finally:
        connection.close()


if __name__ == '__main__':
    raise SystemExit(main())
