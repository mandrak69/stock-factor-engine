from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

from stock_factor_engine.models.financials import FinancialFact


class AmbiguousFinancialFactError(ValueError):
    """Raised when two different fact versions become available at the same instant.

    Silently choosing one would make a historical backtest depend on input order,
    so ambiguity is failed closed until a provider-specific precedence rule exists.
    """


def _normalize_as_of(as_of: datetime) -> datetime:
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    return as_of.astimezone(UTC)


def facts_as_of(
    facts: Iterable[FinancialFact],
    *,
    company_id: str,
    as_of: datetime,
) -> list[FinancialFact]:
    """Return the most recently available version of each fact identity.

    Facts with `available_at > as_of` are invisible. Later amendments or
    restatements replace an earlier version only from their own availability
    instant forward; they never rewrite earlier historical views.
    """

    cutoff = _normalize_as_of(as_of)
    selected: dict[tuple[str, str, str, object, object], FinancialFact] = {}

    for fact in facts:
        if fact.company_id != company_id or fact.available_at > cutoff:
            continue

        key = fact.identity_key
        current = selected.get(key)
        if current is None or fact.available_at > current.available_at:
            selected[key] = fact
            continue

        if fact.available_at == current.available_at and fact != current:
            raise AmbiguousFinancialFactError(
                "Multiple different financial facts have the same identity and "
                f"available_at: {key!r} at {fact.available_at.isoformat()}"
            )

    return sorted(
        selected.values(),
        key=lambda fact: (
            fact.period_end,
            fact.concept,
            fact.period_start or fact.period_end,
            fact.unit,
        ),
    )


def latest_fact_as_of(
    facts: Iterable[FinancialFact],
    *,
    company_id: str,
    concept: str,
    unit: str,
    as_of: datetime,
    period_start=None,
    period_end=None,
) -> FinancialFact | None:
    """Select one fact version as known at `as_of`.

    Optional period bounds allow an exact reporting-period lookup. Without
    them, the latest period_end available by the cutoff is returned.
    """

    visible = [
        fact
        for fact in facts_as_of(facts, company_id=company_id, as_of=as_of)
        if fact.concept == concept
        and fact.unit == unit
        and (period_start is None or fact.period_start == period_start)
        and (period_end is None or fact.period_end == period_end)
    ]
    if not visible:
        return None

    return max(visible, key=lambda fact: (fact.period_end, fact.available_at))
