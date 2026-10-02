from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal


def _require_aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")


@dataclass(frozen=True)
class Filing:
    """One immutable version of a public company filing.

    `accepted_at` describes EDGAR acceptance. `available_at` is the earliest
    instant our research system is allowed to use information from the filing.
    Keeping the two separate avoids pretending EDGAR acceptance and downstream
    data availability are always identical.
    """

    accession_number: str
    company_id: str
    form_type: str
    period_end: date
    filed_date: date
    accepted_at: datetime
    available_at: datetime
    source: str = "sec"
    amendment_of: str | None = None

    def __post_init__(self) -> None:
        _require_aware(self.accepted_at, "accepted_at")
        _require_aware(self.available_at, "available_at")

        accepted_utc = self.accepted_at.astimezone(UTC)
        available_utc = self.available_at.astimezone(UTC)
        object.__setattr__(self, "accepted_at", accepted_utc)
        object.__setattr__(self, "available_at", available_utc)

        if available_utc < accepted_utc:
            raise ValueError("available_at cannot be earlier than accepted_at")
        if self.filed_date < self.period_end:
            raise ValueError("filed_date cannot be before period_end")
        if not self.accession_number.strip():
            raise ValueError("accession_number must not be blank")


@dataclass(frozen=True)
class FinancialFact:
    """A filing-backed financial fact version.

    Duration facts use period_start + period_end. Instant/balance-sheet facts
    have period_start=None and period_end equal to the balance-sheet date.
    """

    company_id: str
    filing_accession_number: str
    concept: str
    value: Decimal
    unit: str
    period_end: date
    available_at: datetime
    period_start: date | None = None
    source_taxonomy: str | None = None

    def __post_init__(self) -> None:
        _require_aware(self.available_at, "available_at")
        object.__setattr__(self, "available_at", self.available_at.astimezone(UTC))

        if self.period_start is not None and self.period_end < self.period_start:
            raise ValueError("period_end cannot be before period_start")
        if not self.concept.strip():
            raise ValueError("concept must not be blank")
        if not self.unit.strip():
            raise ValueError("unit must not be blank")

    @property
    def is_instant(self) -> bool:
        return self.period_start is None

    @property
    def identity_key(self) -> tuple[str, str, str, date | None, date]:
        return (
            self.company_id,
            self.concept,
            self.unit,
            self.period_start,
            self.period_end,
        )
