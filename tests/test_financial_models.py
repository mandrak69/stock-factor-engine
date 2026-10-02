from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from stock_factor_engine.models.financials import Filing, FinancialFact


def test_available_at_cannot_precede_edgar_acceptance() -> None:
    with pytest.raises(ValueError, match="available_at"):
        Filing(
            accession_number="x",
            company_id="acme",
            form_type="10-Q",
            period_end=date(2026, 6, 30),
            filed_date=date(2026, 8, 4),
            accepted_at=datetime(2026, 8, 4, 17, tzinfo=UTC),
            available_at=datetime(2026, 8, 4, 16, tzinfo=UTC),
        )


def test_financial_fact_distinguishes_instant_and_duration_facts() -> None:
    instant = FinancialFact(
        company_id="acme",
        filing_accession_number="x",
        concept="CashAndCashEquivalents",
        value=Decimal("500"),
        unit="USD",
        period_end=date(2026, 6, 30),
        available_at=datetime(2026, 8, 4, tzinfo=UTC),
    )
    duration = FinancialFact(
        company_id="acme",
        filing_accession_number="x",
        concept="Revenue",
        value=Decimal("1000"),
        unit="USD",
        period_start=date(2026, 4, 1),
        period_end=date(2026, 6, 30),
        available_at=datetime(2026, 8, 4, tzinfo=UTC),
    )

    assert instant.is_instant
    assert not duration.is_instant
