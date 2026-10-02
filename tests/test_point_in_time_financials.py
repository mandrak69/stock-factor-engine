from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from stock_factor_engine.models.financials import Filing, FinancialFact
from stock_factor_engine.point_in_time.financials import (
    AmbiguousFinancialFactError,
    facts_as_of,
    latest_fact_as_of,
)


def dt(year: int, month: int, day: int, hour: int = 0) -> datetime:
    return datetime(year, month, day, hour, tzinfo=UTC)


def fact(*, value: str, available_at: datetime, accession: str) -> FinancialFact:
    return FinancialFact(
        company_id="acme",
        filing_accession_number=accession,
        concept="Revenue",
        value=Decimal(value),
        unit="USD",
        period_start=date(2026, 4, 1),
        period_end=date(2026, 6, 30),
        available_at=available_at,
    )


def test_filing_keeps_acceptance_separate_from_availability() -> None:
    filing = Filing(
        accession_number="0000000000-26-000001",
        company_id="acme",
        form_type="10-Q",
        period_end=date(2026, 6, 30),
        filed_date=date(2026, 8, 4),
        accepted_at=dt(2026, 8, 4, 16),
        available_at=dt(2026, 8, 4, 17),
    )

    assert filing.available_at > filing.accepted_at


def test_future_filing_cannot_leak_into_historical_query() -> None:
    q1 = FinancialFact(
        company_id="acme",
        filing_accession_number="q1",
        concept="Revenue",
        value=Decimal("100"),
        unit="USD",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 3, 31),
        available_at=dt(2026, 5, 5),
    )
    q2 = fact(value="120", available_at=dt(2026, 8, 4), accession="q2")

    result = latest_fact_as_of(
        [q1, q2],
        company_id="acme",
        concept="Revenue",
        unit="USD",
        as_of=dt(2026, 7, 1),
    )

    assert result == q1


def test_restatement_becomes_visible_only_from_its_own_available_at() -> None:
    original = fact(value="120", available_at=dt(2026, 8, 4), accession="q2")
    restated = fact(value="117", available_at=dt(2026, 9, 10), accession="q2a")

    before = latest_fact_as_of(
        [original, restated],
        company_id="acme",
        concept="Revenue",
        unit="USD",
        period_start=date(2026, 4, 1),
        period_end=date(2026, 6, 30),
        as_of=dt(2026, 9, 1),
    )
    after = latest_fact_as_of(
        [original, restated],
        company_id="acme",
        concept="Revenue",
        unit="USD",
        period_start=date(2026, 4, 1),
        period_end=date(2026, 6, 30),
        as_of=dt(2026, 9, 11),
    )

    assert before == original
    assert after == restated


def test_different_values_with_same_availability_fail_closed() -> None:
    left = fact(value="120", available_at=dt(2026, 8, 4), accession="q2")
    right = fact(value="121", available_at=dt(2026, 8, 4), accession="other")

    with pytest.raises(AmbiguousFinancialFactError):
        facts_as_of([left, right], company_id="acme", as_of=dt(2026, 8, 5))


def test_as_of_must_be_timezone_aware() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        facts_as_of([], company_id="acme", as_of=datetime(2026, 8, 5))
