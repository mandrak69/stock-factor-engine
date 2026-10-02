# Shares and business growth v0.1

## Usage

```powershell
.\.venv\Scripts\python.exe -m stock_factor_engine.fundamentals --as-of 2026-10-02T00:00:00Z --company-profile
```

The report reads the local database without changing it. Like the other
fundamental reports, it uses an explicit timezone-aware `as_of`. Results include
availability status, amount, unit, source terms, inputs and unavailable reasons.
Growth and margin ratios are decimal fractions: `0.2` means 20%.

## Shares, EPS and distributions

Parser `sec-v0.3.0` adds explicit namespace/unit-aware mapping:

| SEC concept | Canonical concept | Unit / shape |
| --- | --- | --- |
| us-gaap:CommonStockSharesOutstanding | reported_shares_outstanding | shares / instant |
| dei:EntityCommonStockSharesOutstanding | cover_shares_outstanding | shares / instant |
| us-gaap:WeightedAverageNumberOfSharesOutstandingBasic | weighted_average_shares_basic | shares / duration |
| us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding | weighted_average_shares_diluted | shares / duration |
| us-gaap:EarningsPerShareDiluted | eps_diluted | USD/shares / duration |
| us-gaap:PaymentsForRepurchaseOfCommonStock | common_stock_repurchases | USD / duration |
| us-gaap:PaymentsOfDividendsCommonStock | common_stock_dividends_paid | USD / duration |

Preserve these distinctions: reporting-date shares, a later cover-page count and
average EPS denominators do not mean the same thing. The cover count is reported
with its own observation date. Basic/diluted averages and diluted EPS are shown
only when a direct annual observation matches the report window. They are never
summed from cumulative quarters or inserted as a market-cap share count.

Point share counts must be positive, have shares units and instant shape, and
must not have an observation date later than the source filing availability.
Namespace, original concept, accession and retrieval evidence are retained.
The annual reported-count change is current count / previous count - 1. It is a
descriptive count change, **not a validated dilution factor**: split-basis and
share-class reconciliation still need verification. It does not measure gross
issuance, employee compensation dilution or buybacks separately.

Common-stock repurchases and common-stock cash dividends paid are reported as
TTM cash amounts. These are not dividend yield, declared dividends per share or
shares actually retired. They can be used to explain capital distributions once
their context is checked.

## Growth and margins

- TTM growth is current TTM / previous TTM - 1 for revenue, operating income,
  operating cash flow, capex and free cash flow.
- The prior trailing period ends immediately before the current revenue
  trailing period begins. All component windows must match the revenue windows;
  missing periods stay unavailable rather than using stale or mismatched values.
- Current and comparative facts are both selected using the same `as_of`.
  Restated comparisons are used only after they become available. This is growth
  as known on the requested date, not a comparison of separately frozen annual
  reports published a year apart.
- Zero/negative comparison amounts do not produce a percentage growth figure.
  The original current/previous amounts remain visible. A move from loss to profit
  requires another explicitly defined indicator.
- Operating margin is TTM operating income / TTM revenue. FCF margin is TTM FCF /
  TTM revenue. Revenue must be positive and windows must align.

All existing TTM fiscal-length, conflict and companyfacts-vintage limitations
remain in effect. Exact Decimal sums are retained; ratios use 34 significant digits.

## Debt coverage and market-cap readiness

The profile includes total-debt coverage, borrowing/commercial-paper amounts at
the selected period end, and the latest reported observations with their actual
dates. An old reported zero is not carried into the current period.

In the current Microsoft import, the latest explicit short-term borrowing value
is from 2018, and the latest commercial-paper observation is from June 2025.
Neither establishes a zero June 2026 short-term balance. Total debt remains
unavailable under the strict component policy. A verified original-filing debt
extraction or broader provider will be needed to close that gap.

Market cap remains unavailable because provider-split-adjusted Yahoo history has
not been independently reconciled with a compatible share-count basis. This
report intentionally does not multiply mismatched price/share quantities.

## Local validation

Archived SEC replay added 1,447 new facts, zero filings and zero quarantine
observations. Repeating that replay added zero facts. A database backup was saved
before the extension. The October 2, 2026 view contains June 2026 year-end growth,
shares, EPS and distribution amounts; each number links to its source through
the result's nested SEC terms.

Tests cover unit/namespace separation, current/prior fiscal windows, future
restatements, loss bases, missing historical counts and refusal to sum weighted
average share observations.

Reference for EPS/share tagging:
[FASB taxonomy FAQ](https://www.fasb.org/taxonomyfaq).

## Subsequent data stages

The next separate stages are market/sector benchmarks and price factors, then a
small macro/event dataset with vintage-aware rates, inflation and labor data.
Neither macro signals nor analyst consensus are implemented in this release.
