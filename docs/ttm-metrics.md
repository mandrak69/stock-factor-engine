# Point-in-time TTM metrics v0.1

## Run

From the project directory, using the ingested SQLite database:

```powershell
.\.venv\Scripts\python.exe -m stock_factor_engine.fundamentals --as-of 2026-10-02T00:00:00Z
```

`--as-of` is required and must include a timezone. Optional arguments:
`--company-id`, `--database`, `--period-end YYYY-MM-DD`. Default company is
Microsoft. The database is opened read-only; no metrics or schema changes are
written. The command emits JSON containing visible period coverage, values,
reporting windows, methods, and signed source terms with filing accessions and
availability timestamps. Financial amounts are decimal strings in USD.

## Calculation policy

1. Select fact versions available at or before the requested instant using the
   existing point-in-time policy. Future amendments remain invisible.
2. Use the latest reported duration end across the four required concepts,
   unless an explicit reporting end was supplied. Missing coverage at that end
   raises; there is no silent fallback to an older complete year.
3. Recognize direct quarters (70–110 days), half-year cumulative facts
   (150–210), nine-month cumulative facts (240–300), and annual facts (350–380).
   Dates define periods; calendar labels or filing form alone are insufficient.
   The annual range accommodates ordinary leap years and 52/53-week calendars.
   Transition years and unusual durations need a later explicit fiscal-calendar
   policy and are currently unsupported.
4. Derive a quarter only by subtracting two cumulative observations with the
   same start date and a resulting quarter-length interval. Its start is the
   day after the earlier period ends. Direct and derived evidence for the exact
   same interval must agree, or calculation raises.
5. TTM is a direct annual period or exactly four contiguous, non-overlapping
   quarters covering 350–380 days. Alternatives must agree on both dates and
   amount. Direct annual evidence is preferred when it agrees. Never add YTD
   and standalone quarter amounts for overlapping intervals.
6. Require identical trailing windows and USD units across revenue, operating
   income, operating cash flow and capital expenditure. FCF equals operating
   cash flow minus capital expenditure, with capex represented as positive
   cash outflow. Negative derived capex raises for investigation.

Calculations use Decimal with sufficient local precision. Results retain their
source expression rather than only an unexplained total. Signed terms can
include cancellation between cumulative observations. TTM operating income is
the reported operating-income concept; it is not a general reconstructed EBIT
definition. FCF here is the simple cash-flow-minus-PP&E-capex definition, not a
company-adjusted or lease-adjusted measure.

Comparative facts can be restated independently across filings. Conflicting
direct/cumulative evidence fails closed; this version does not claim to solve
accounting-basis reconciliation. Latest-window quarterly checks can also reject
conflicts in relevant neighboring periods. Coverage counts describe observations
and duration shapes; earliest/latest dates alone do not prove gap-free history.
The aggregate companyfacts historical-data caveats in `sec-ingestion.md` still
apply. No stale-data eligibility filter, sector adjustment or backtest is included.

## Verification

Tests cover cumulative differences, rolling TTM, overlapping evidence, missing
quarters, conflicts, future restatements, Decimal precision, 53-week years,
negative capex and timezone-naive queries. Integration was checked read-only
against the local Microsoft SEC import for cutoffs in May 2020, May 2026 and
October 2026. These checks verify the imported-data calculation, not an external
audit of SEC accounting values.
