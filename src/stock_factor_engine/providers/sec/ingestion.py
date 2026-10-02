from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from stock_factor_engine.models.financials import Filing, FinancialFact
from stock_factor_engine.storage.time import timestamp
from .client import BASE_URL, SecClient, decode_json, normalize_cik


PARSER_VERSION = 'sec-v0.2.0'
# Explicit, deliberately small mapping. Aliases remain separate observations.
CONCEPTS = {
    'RevenueFromContractWithCustomerExcludingAssessedTax': 'revenue',
    'Revenues': 'revenue', 'SalesRevenueNet': 'revenue',
    'OperatingIncomeLoss': 'operating_income', 'NetIncomeLoss': 'net_income',
    'NetCashProvidedByUsedInOperatingActivities': 'operating_cash_flow',
    'PaymentsToAcquirePropertyPlantAndEquipment': 'capital_expenditure',
    'CashAndCashEquivalentsAtCarryingValue': 'cash', 'Assets': 'total_assets',
    'StockholdersEquity': 'shareholders_equity',
    'DebtLongtermAndShorttermCombinedAmount': 'total_debt',
    'LongTermDebt': 'long_term_debt_total',
    'LongTermDebtCurrent': 'long_term_debt_current',
    'LongTermDebtNoncurrent': 'long_term_debt_noncurrent',
    'ShortTermBorrowings': 'short_term_borrowings',
    'CommercialPaper': 'commercial_paper',
    'ShortTermInvestments': 'short_term_investments',
    'InterestExpense': 'interest_expense',
    'InterestExpenseNonOperating': 'interest_expense_nonoperating',
    'InterestExpenseNonoperating': 'interest_expense_nonoperating',
    'IncomeTaxExpenseBenefit': 'income_tax_expense',
    'IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest': 'pretax_income',
    'IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments': 'pretax_income_before_equity_method',
}
INSTANT_CONCEPTS = {'cash', 'total_assets', 'shareholders_equity', 'total_debt',
                    'long_term_debt_total', 'long_term_debt_current', 'long_term_debt_noncurrent',
                    'short_term_borrowings', 'commercial_paper', 'short_term_investments'}
FORMS = {'10-K', '10-Q', '10-K/A', '10-Q/A'}


def parse_filings(columns: dict, company_id: str) -> tuple[list[Filing], list[dict]]:
    required = ('accessionNumber', 'form', 'reportDate', 'filingDate', 'acceptanceDateTime')
    if 'acceptanceDateTime' not in columns and isinstance(columns.get('accessionNumber'), list):
        columns = {**columns, 'acceptanceDateTime': [None] * len(columns['accessionNumber'])}
    if not all(isinstance(columns.get(key), list) for key in required):
        raise ValueError('Missing submissions columns')
    if len({len(columns[key]) for key in required}) != 1:
        raise ValueError('Submissions columns have different lengths')
    filings, rejected = [], []
    for accession, form, period, filed, accepted in zip(*(columns[key] for key in required)):
        if form not in FORMS:
            continue
        try:
            accepted_at = datetime.fromisoformat(accepted.replace('Z', '+00:00'))
            # Conservative explicit policy, not a claim of exact dissemination time.
            filing = Filing(accession, company_id, form, date.fromisoformat(period),
                            date.fromisoformat(filed), accepted_at, accepted_at + timedelta(minutes=5))
            filings.append(filing)
        except (ValueError, TypeError, AttributeError) as error:
            rejected.append({'kind': 'filing', 'accession': accession, 'reason': str(error)})
    return filings, rejected


def parse_facts(payload: dict, company_id: str, filings: dict[str, Filing]):
    parsed, rejected = [], []
    for source_concept, details in payload.get('facts', {}).get('us-gaap', {}).items():
        if source_concept not in CONCEPTS:
            continue
        for unit, observations in details.get('units', {}).items():
            for observation in observations:
                accession = observation.get('accn')
                if observation.get('form') not in FORMS:
                    continue
                try:
                    filing = filings.get(accession)
                    if filing is None:
                        raise ValueError('No filing with a justified availability timestamp')
                    if observation['form'] != filing.form_type or observation['filed'] != filing.filed_date.isoformat():
                        raise ValueError('Fact filing metadata disagrees with submissions')
                    if unit != 'USD':
                        raise ValueError('Mapped financial concept requires USD units')
                    amount = Decimal(str(observation['val']))
                    if not amount.is_finite():
                        raise ValueError('Non-finite amount')
                    fact = FinancialFact(company_id, accession, CONCEPTS[source_concept], amount,
                                         unit, date.fromisoformat(observation['end']), filing.available_at,
                                         date.fromisoformat(observation['start']) if 'start' in observation else None,
                                         'us-gaap')
                    duration = CONCEPTS[source_concept] not in INSTANT_CONCEPTS
                    if duration == fact.is_instant:
                        raise ValueError('Unexpected instant/duration shape')
                    parsed.append((fact, source_concept))
                except (ValueError, TypeError, KeyError, ArithmeticError) as error:
                    rejected.append({'kind': 'fact', 'accession': accession, 'concept': source_concept,
                                     'observation': observation, 'reason': str(error)})
    return parsed, rejected


def persist_filing(db, filing: Filing, raw_id: str) -> bool:
    values = (filing.accession_number, filing.company_id, filing.form_type,
              filing.period_end.isoformat(), filing.filed_date.isoformat(),
              timestamp(filing.accepted_at), timestamp(filing.available_at), filing.source, filing.amendment_of)
    existing = db.execute('SELECT * FROM filings WHERE accession_number = ?', (filing.accession_number,)).fetchone()
    if existing:
        if tuple(existing)[:9] != values:
            raise ValueError(f'Conflicting filing: {filing.accession_number}')
        return False
    db.execute('INSERT INTO filings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', (*values, raw_id))
    return True


def persist_fact(db, fact: FinancialFact, source_concept: str, raw_id: str) -> bool:
    start = fact.period_start.isoformat() if fact.period_start else None
    key = (fact.company_id, fact.filing_accession_number, fact.concept, fact.unit, start,
           fact.period_end.isoformat(), timestamp(fact.available_at), fact.source_taxonomy, source_concept)
    existing = db.execute('''SELECT value_decimal FROM financial_facts WHERE
        company_id=? AND filing_accession_number=? AND concept=? AND unit=? AND
        period_start IS ? AND period_end=? AND available_at=? AND source_taxonomy=? AND source_concept=?''', key).fetchone()
    if existing:
        if Decimal(existing[0]) != fact.value:
            raise ValueError(f'Conflicting fact: {key}')
        return False
    db.execute('''INSERT INTO financial_facts (company_id, filing_accession_number, concept,
        unit, period_start, period_end, available_at, source_taxonomy, source_concept,
        value_decimal, raw_document_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (*key, str(fact.value), raw_id))
    return True


def ingest_company(db: sqlite3.Connection, data_dir: Path, cik: str, client: SecClient) -> dict:
    """Save evidence first; normalized inserts commit together or roll back together."""
    if db.in_transaction:
        raise ValueError('Ingestion requires a connection without an active transaction')
    cik = normalize_cik(cik)
    data_dir = Path(data_dir).resolve()
    run_id, company_id = uuid4().hex, 'sec:' + cik
    db.execute('INSERT INTO ingestion_runs VALUES (?, ?, ?, ?, NULL, ?, NULL)',
               (run_id, 'sec', PARSER_VERSION, timestamp(datetime.now(UTC)), 'running'))
    db.commit()
    raw_records = []

    def download(path: str, endpoint: str):
        content, retrieved_at = client.fetch(path)
        sha = hashlib.sha256(content).hexdigest()
        raw_id = uuid4().hex
        relative = Path('raw') / 'sec' / cik / endpoint / f'{run_id}-{raw_id}-{sha}.json'
        destination = data_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix('.tmp')
        temporary.write_bytes(content)
        temporary.replace(destination)
        raw_records.append((raw_id, run_id, 'sec', BASE_URL + path, timestamp(retrieved_at),
                            relative.as_posix(), sha, 'application/json'))
        return decode_json(content), raw_id

    try:
        submissions, submission_raw = download(f'/submissions/CIK{cik}.json', 'submissions')
        if normalize_cik(str(submissions['cik'])) != cik:
            raise ValueError('Submissions CIK does not match request')
        filings, rejected = parse_filings(submissions['filings']['recent'], company_id)
        filing_sources = [(filing, submission_raw) for filing in filings]
        for page in submissions['filings'].get('files', []):
            name = page['name']
            if not re.fullmatch(rf'CIK{cik}-submissions-[0-9]+\.json', name):
                raise ValueError('Invalid historical submissions filename')
            history, raw_id = download('/submissions/' + name, 'submissions')
            historical, issues = parse_filings(history, company_id)
            filing_sources.extend((filing, raw_id) for filing in historical)
            rejected.extend(issues)
        filing_map = {}
        for filing, _ in filing_sources:
            if filing.accession_number in filing_map and filing_map[filing.accession_number] != filing:
                raise ValueError('Conflicting submissions pages')
            filing_map[filing.accession_number] = filing
        companyfacts, facts_raw = download(f'/api/xbrl/companyfacts/CIK{cik}.json', 'companyfacts')
        if normalize_cik(str(companyfacts['cik'])) != cik:
            raise ValueError('Companyfacts CIK does not match request')
        if not isinstance(companyfacts.get('facts'), dict):
            raise ValueError('Missing companyfacts facts object')
        facts, issues = parse_facts(companyfacts, company_id, filing_map)
        rejected.extend(issues)
        report_path = data_dir / 'raw' / 'sec' / cik / f'{run_id}-quarantine.json'
        report_path.write_text(json.dumps(rejected, default=str, indent=2), encoding='utf-8')
        if not facts:
            raise ValueError('No valid mapped financial facts; inspect quarantine report')
        with db:
            db.executemany('INSERT INTO raw_documents VALUES (?, ?, ?, ?, ?, ?, ?, ?)', raw_records)
            existing = db.execute('SELECT cik FROM companies WHERE id=?', (company_id,)).fetchone()
            if existing is None:
                db.execute('INSERT INTO companies (id, legal_name, cik) VALUES (?, ?, ?)',
                           (company_id, submissions['name'], cik))
            elif existing[0] != cik:
                raise ValueError('Company identity conflict')
            new_filings = sum(persist_filing(db, filing, raw_id) for filing, raw_id in filing_sources)
            new_facts = sum(persist_fact(db, fact, source_concept, facts_raw) for fact, source_concept in facts)
            db.execute('UPDATE ingestion_runs SET status=?, finished_at=? WHERE id=?',
                       ('succeeded', timestamp(datetime.now(UTC)), run_id))
        return {'run_id': run_id, 'company_id': company_id, 'new_filings': new_filings,
                'new_facts': new_facts, 'quarantined': len(rejected), 'quarantine_file': str(report_path)}
    except Exception as error:
        db.rollback()
        with db:
            db.executemany('INSERT INTO raw_documents VALUES (?, ?, ?, ?, ?, ?, ?, ?)', raw_records)
            db.execute('UPDATE ingestion_runs SET status=?, finished_at=?, error=? WHERE id=?',
                       ('failed', timestamp(datetime.now(UTC)), str(error), run_id))
        raise
