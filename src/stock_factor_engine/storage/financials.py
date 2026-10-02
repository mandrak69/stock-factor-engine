from datetime import date, datetime
from decimal import Decimal

from stock_factor_engine.models.financials import FinancialFact
from stock_factor_engine.point_in_time.financials import facts_as_of
from stock_factor_engine.storage.time import timestamp


def financial_facts_as_of(connection, *, company_id: str, as_of: datetime):
    rows = connection.execute('SELECT * FROM financial_facts WHERE company_id=? AND available_at<=?',
                              (company_id, timestamp(as_of)))
    facts = [FinancialFact(
        row['company_id'], row['filing_accession_number'], row['concept'],
        Decimal(row['value_decimal']), row['unit'], date.fromisoformat(row['period_end']),
        datetime.fromisoformat(row['available_at']),
        date.fromisoformat(row['period_start']) if row['period_start'] else None,
        row['source_taxonomy'],
    ) for row in rows]
    return facts_as_of(facts, company_id=company_id, as_of=as_of)
