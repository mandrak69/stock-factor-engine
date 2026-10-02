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
    parser.add_argument('--assume-zero-short-term-debt', action='store_true',
                        help='Explicitly assume missing short-term borrowings are zero; recorded in output')
    args = parser.parse_args()
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
