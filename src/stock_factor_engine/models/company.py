from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Company:
    """Stable issuer/business identity.

    `cik` is the SEC Central Index Key when the company is an SEC filer.
    It is stored as a zero-padded string because leading zeroes are part of
    the canonical external representation used by SEC data endpoints.
    """

    id: str
    legal_name: str
    cik: str | None = None
    sector: str | None = None
    industry: str | None = None

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("Company id must not be blank")
        if not self.legal_name.strip():
            raise ValueError("Company legal_name must not be blank")
        if self.cik is not None and (len(self.cik) != 10 or not self.cik.isdigit()):
            raise ValueError("CIK must be a zero-padded 10 digit string")


@dataclass(frozen=True)
class Security:
    """A tradeable listed instrument issued by a company."""

    id: str
    company_id: str
    exchange: str
    currency: str
    security_type: str = "common_stock"
    active_from: date | None = None
    active_to: date | None = None

    def __post_init__(self) -> None:
        if self.active_from is not None and self.active_to is not None:
            if self.active_to < self.active_from:
                raise ValueError("Security active_to cannot be before active_from")

    def is_active_on(self, on_date: date) -> bool:
        return (
            (self.active_from is None or self.active_from <= on_date)
            and (self.active_to is None or on_date <= self.active_to)
        )


@dataclass(frozen=True)
class TickerAssignment:
    """Time-bounded ticker alias for a security.

    A ticker is not used as the primary identity of either Company or
    Security. The same security can therefore move from FB to META without
    rewriting its earlier history.
    """

    security_id: str
    symbol: str
    valid_from: date
    valid_to: date | None = None

    def __post_init__(self) -> None:
        normalized = self.symbol.strip().upper()
        if not normalized:
            raise ValueError("Ticker symbol must not be blank")
        object.__setattr__(self, "symbol", normalized)
        if self.valid_to is not None and self.valid_to < self.valid_from:
            raise ValueError("Ticker valid_to cannot be before valid_from")

    def is_valid_on(self, on_date: date) -> bool:
        return self.valid_from <= on_date and (
            self.valid_to is None or on_date <= self.valid_to
        )
