import argparse
import json
import sqlite3
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path

from stock_factor_engine.storage.financials import financial_facts_as_of
from stock_factor_engine.storage.time import timestamp
from .ttm import coverage, ttm_metrics
from .balance import Result, balance_metrics
from .company import company_profile
from .valuation import valuation_metrics
from stock_factor_engine.storage.market import snapshot_prices_as_of


def result_payload(result):
    return {'status': result.status, 'value': str(result.value) if result.value is not None else None,
            'unit': result.unit, 'formula': result.formula, 'reason': result.reason,
            'assumptions': result.assumptions,
            'inputs': {name: result_payload(item) if isinstance(item, Result) else item
                       for name, item in result.inputs.items()},
            'sources': [asdict(term) for term in result.sources]}


def main():
    parser = argparse.ArgumentParser(description='Inspect coverage and explain point-in-time TTM metrics.')
    parser.add_argument('--database', type=Path, default=Path('data/engine.sqlite'))
    parser.add_argument('--company-id', default='sec:0000789019')
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
            if len(securities) != 1:
                parser.error('Valuation requires exactly one configured USD common-stock security')
            snapshot_id = args.market_snapshot
            if snapshot_id is None:
                row = connection.execute('''SELECT id FROM market_snapshots WHERE security_id=? AND retrieved_at<=?
                    ORDER BY retrieved_at DESC, rowid DESC LIMIT 1''', (securities[0][0], timestamp(as_of))).fetchone()
                if row is None:
                    parser.error('No market snapshot downloaded by as-of; import prices or select an explicit retrospective snapshot')
                snapshot_id = row[0]
            snapshot, prices = snapshot_prices_as_of(connection, snapshot_id=snapshot_id, as_of=as_of)
            if snapshot['security_id'] != securities[0][0]:
                parser.error('Market snapshot belongs to a different security')
            last_date = connection.execute('''SELECT MAX(p.trading_date) FROM daily_prices p
                JOIN snapshot_prices s ON s.price_id=p.id WHERE s.snapshot_id=?''', (snapshot_id,)).fetchone()[0]
            if last_date is None:
                parser.error('Market snapshot contains no prices')
            splits = connection.execute('''SELECT a.event_date FROM corporate_actions a
                JOIN snapshot_actions s ON s.action_id=a.id WHERE s.snapshot_id=? AND a.kind='split' ''', (snapshot_id,)).fetchall()
            end, results = valuation_metrics(facts, prices, company_id=args.company_id, as_of=as_of,
                                             price_basis=snapshot['price_basis'],
                                             snapshot_last_date=date.fromisoformat(last_date),
                                             split_dates=[date.fromisoformat(row[0]) for row in splits],
                                             period_end=args.period_end)
            print(json.dumps({'company_id': args.company_id, 'as_of': timestamp(as_of),
                              'valuation_version': 'research-valuation-v0.1', 'period_end': end,
                              'snapshot': {'id': snapshot_id, 'retrieved_at': snapshot['retrieved_at'],
                                           'known_at_as_of': datetime.fromisoformat(snapshot['retrieved_at']) <= as_of,
                                           'source': snapshot['source'], 'price_basis': snapshot['price_basis']},
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
