import argparse
import json
import sqlite3
from datetime import date, datetime
from pathlib import Path

from stock_factor_engine.storage.financials import financial_facts_as_of
from stock_factor_engine.storage.time import timestamp
from .ttm import coverage, ttm_metrics
from .balance import balance_metrics
from .reporting import result_payload
from .company import company_profile
from .valuation import valuation_metrics
from stock_factor_engine.storage.research import price_context
from stock_factor_engine.universe.registry import IDENTITIES, share_scope_reason


def main():
    parser = argparse.ArgumentParser(description='Inspect coverage and explain point-in-time TTM metrics.')
    parser.add_argument('--database', type=Path, default=Path('data/engine.sqlite'))
    parser.add_argument('--company-id')
    parser.add_argument('--symbol', choices=[symbol for symbol, identity in IDENTITIES.items() if identity['requires_sec']],
                        help='Registered equity for --valuation; useful for multi-class issuers')
    parser.add_argument('--as-of', required=True, help='Timezone-aware ISO timestamp, e.g. 2026-10-02T00:00:00Z')
    parser.add_argument('--period-end', type=date.fromisoformat)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--balance', action='store_true', help='Report balance, debt, ROIC proxy and interest coverage')
    modes.add_argument('--company-profile', action='store_true', help='Report shares, growth, margins and debt coverage')
    modes.add_argument('--valuation', action='store_true', help='Report research market cap, P/E, P/S and FCF yield')
    parser.add_argument('--market-snapshot', help='Explicit price vintage for --valuation; later vintages are labelled retrospective')
    parser.add_argument('--assume-zero-short-term-debt', action='store_true',
                        help='Explicitly assume missing short-term borrowings are zero; recorded in output')
    args = parser.parse_args()
    if args.symbol and not args.valuation:
        parser.error('--symbol applies only to --valuation')
    identity = IDENTITIES.get(args.symbol) if args.symbol else None
    if identity and args.company_id and args.company_id != identity['company_id']:
        parser.error('--symbol and --company-id identify different companies')
    args.company_id = args.company_id or (identity['company_id'] if identity else 'sec:0000789019')
    if args.market_snapshot and not args.valuation:
        parser.error('--market-snapshot applies only to --valuation')
    if args.assume_zero_short_term_debt and not args.balance:
        parser.error('--assume-zero-short-term-debt applies only to --balance')
    try:
        as_of = datetime.fromisoformat(args.as_of)
        timestamp(as_of)
    except ValueError as error:
        parser.error(str(error))
    connection = sqlite3.connect(args.database.resolve().as_uri() + '?mode=ro', uri=True)
    connection.row_factory = sqlite3.Row
    try:
        facts = financial_facts_as_of(connection, company_id=args.company_id, as_of=as_of)
        if args.valuation:
            securities = connection.execute("SELECT id FROM securities WHERE company_id=? AND security_type='common_stock' AND currency='USD'",
                                             (args.company_id,)).fetchall()
            if identity:
                securities = [row for row in securities if row[0] == identity['security_id']]
            if len(securities) != 1:
                parser.error('Valuation requires exactly one configured USD common-stock security')
            identity = identity or next((item for item in IDENTITIES.values() if item['security_id'] == securities[0][0]), None)
            if identity is None:
                parser.error('Valuation security needs explicit registry share-class configuration')
            try:
                snapshot, prices, last_date, splits = price_context(connection, security_id=securities[0][0],
                                                                  as_of=as_of, snapshot_id=args.market_snapshot)
            except ValueError as error:
                parser.error(str(error))
            end, results = valuation_metrics(facts, prices, company_id=args.company_id, as_of=as_of,
                                             price_basis=snapshot['price_basis'],
                                             snapshot_last_date=last_date, split_dates=splits,
                                             period_end=args.period_end,
                                             share_scope_reason=share_scope_reason(identity))
            print(json.dumps({'company_id': args.company_id, 'as_of': timestamp(as_of),
                              'valuation_version': 'research-valuation-v0.1', 'period_end': end,
                              'snapshot': snapshot,
                              'metrics': {name: result_payload(result) for name, result in results.items()}},
                             default=str, indent=2))
            return
        if args.company_profile:
            end, results = company_profile(facts, company_id=args.company_id, as_of=as_of, period_end=args.period_end)
            print(json.dumps({'company_id': args.company_id, 'as_of': timestamp(as_of),
                              'period_end': end, 'metrics': {name: result_payload(result)
                                                           for name, result in results.items()}},
                             default=str, indent=2))
            return
        if args.balance:
            end, results = balance_metrics(facts, company_id=args.company_id, as_of=as_of,
                                          period_end=args.period_end,
                                          assume_zero_short_term_debt=args.assume_zero_short_term_debt)
            print(json.dumps({'company_id': args.company_id, 'as_of': timestamp(as_of),
                              'period_end': end, 'metrics': {name: result_payload(result)
                                                           for name, result in results.items()}},
                             default=str, indent=2))
            return
        metrics = ttm_metrics(facts, company_id=args.company_id, as_of=as_of, period_end=args.period_end)
        report = {'company_id': args.company_id, 'as_of': timestamp(as_of),
                  'coverage': coverage(facts), 'metrics': {}}
        for name, metric in metrics.items():
            report['metrics'][name] = {
                'value': str(metric.value), 'unit': metric.unit,
                'period_start': metric.period_start, 'period_end': metric.period_end,
                'method': metric.method, 'sources': [{
                    'coefficient': term.coefficient, 'value': str(term.fact.value),
                    'concept': term.fact.concept, 'period_start': term.fact.period_start,
                    'period_end': term.fact.period_end,
                    'accession': term.fact.filing_accession_number,
                    'available_at': timestamp(term.fact.available_at),
                } for term in metric.terms],
            }
        print(json.dumps(report, default=str, indent=2))
    finally:
        connection.close()


if __name__ == '__main__':
    main()
