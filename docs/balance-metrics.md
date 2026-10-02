# Balance and quality metrics v0.1

## Usage

```powershell
.\.venv\Scripts\python.exe -m stock_factor_engine.fundamentals --as-of 2026-10-02T00:00:00Z --balance
```

Returns independent metric results with `status`, `value`, `unit`, `formula`,
`reason`, nested `inputs`, SEC source terms and explicit `assumptions`. Missing
data affects dependent metrics only. No infinity, invented zeros or automatic
tax-rate clamps are emitted. Ratios use Decimal at 34 significant digits;
multiply a ratio by 100 to display a percent.

## Formulas

| Metric | Policy |
| --- | --- |
| Long-term debt | Reported long-term aggregate, or current + noncurrent maturities |
| Total debt | Reported combined short/long-term aggregate, or long-term total + short-term borrowings |
| Cash | Reported cash and cash equivalents, excluding short-term investments |
| Net debt | Total debt minus cash; negative means net cash under this definition |
| Invested capital | Total debt + shareholders' equity - cash |
| Average invested capital | Arithmetic mean of opening and closing invested capital |
| Effective tax rate | TTM income-tax expense / TTM pretax income |
| NOPAT proxy | TTM operating income × (1 - effective tax rate) |
| ROIC proxy | NOPAT proxy / average invested capital |
| Interest coverage | TTM operating income / TTM reported interest expense |

Closing balances must match the selected reporting end exactly. The opening
balance date is the day before the operating-income TTM window starts. Do not
replace a missing opening balance with an older quarter. Flow metrics must use
the same TTM dates. All inputs use only versions known at `as_of`.

Debt aggregate and component alternatives must agree when both are complete.
Do not add the long-term total to current maturities again. Commercial paper is
retained separately because it may overlap short-term borrowings; do not blindly
sum both. Face amount, fair value, gross debt before discounts, debt securities
held as investments, and lease liabilities are not substitutes for borrowed-debt
carrying balances in this policy. Lease adjustments require a future strategy
version. Cash and short-term investments are displayed separately, and only cash
is subtracted from capital/net debt under this release's formula.

Missing short-term borrowings are not assumed zero. When a complete reported
combined-debt aggregate exists, it can stand alone. Otherwise total debt and its
dependent metrics are unavailable without the missing component. For explicit
scenario analysis only, this option assumes zero at both opening and closing
dates and carries that assumption through dependent outputs:

```powershell
.\.venv\Scripts\python.exe -m stock_factor_engine.fundamentals --as-of 2026-10-02T00:00:00Z --balance --assume-zero-short-term-debt
```

This option is not a statement about the company's real borrowings. It is refused
if a nonzero commercial-paper balance contradicts the assumption. It must not be
enabled indiscriminately in a backtest.

Tax rates outside [0, 1], nonpositive pretax income, nonpositive average capital
or nonpositive interest expense make the affected ratios unavailable. Reported
zero interest does not become infinity. Negative cash/debt components are invalid;
negative equity and negative net debt are allowed. NOPAT uses the reported
company-wide effective rate as an approximation, not a tax calculation on
operating profit alone. Consequently the result is explicitly `roic_proxy`.
Total `InterestExpense` is preferred where current-period data exists; otherwise
nonoperating interest expense is used. A conflict in reported total interest
is not silently replaced by a narrower concept. Coverage is an operating-income
proxy and is not a reconstructed general EBIT definition.

## SEC map and replay

Parser `sec-v0.2.0` extends mapping with debt balances, short-term investments,
interest expense, income-tax expense and pretax-income concepts. Shape validation
is driven by canonical instant/duration definitions. Availability remains SEC
acceptance plus five minutes; existing observations are not changed.

Reparse saved responses without downloading again:

```powershell
.\.venv\Scripts\python.exe -m stock_factor_engine.providers.sec --replay-run <previous_run_id>
```

New concepts append facts using the new raw run's parser version. Existing
filings and facts are checked for equality and are not overwritten. The original
companyfacts historical-data limitations still apply. Pretax income excluding
equity-method investments is stored separately; it is not silently substituted
for a different pretax basis.

## Local Microsoft validation

Replaying archived run `1df2b8c1734b4733a216ae1db6a76563` added 1,212 facts,
zero filings and zero quarantine observations. A SQLite backup was made before
the replay. Default results for the June 30, 2026 reporting end include cash,
long-term debt, equity, tax rate, NOPAT proxy and interest coverage. Total debt,
net debt and ROIC remain unavailable because the aggregate import lacks an
explicit complete short-term borrowing balance at the required dates.

Tests cover debt double-counting, missing components, explicit assumptions,
future restatements, mismatched periods, zero denominators, tax benefits, negative
capital and both SEC observation shapes.

References for checking the local import's source semantics:

- [Microsoft FY26 10-K](https://www.sec.gov/Archives/edgar/data/789019/000119312526323660/msft-20260630.htm)
- [FASB example: noncurrent long-term debt](https://xbrl.fasb.org/impdocs/OCI_TIG/othercompincome.htm)
