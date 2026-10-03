# Research valuation v0.1

```powershell
python -m stock_factor_engine.fundamentals --valuation --as-of (Get-Date).ToUniversalTime().ToString('o')
```

The report reads the existing SQLite database without new schema or derived
tables. Select a registered USD common-stock security with `--symbol AAPL`
(or MSFT, AMZN, GOOGL, GOOG, META). Without a symbol, a company must have exactly
one configured common-stock security. GOOGL and GOOG share a company but have
separate price securities. Independent results retain formulas,
SEC sources/accessions/availability, share observation dates,
price dates, fiscal periods, snapshot source/ID, assumptions and missing reasons.

## Definitions

- `market_cap_estimate`: provider close times the latest reported outstanding
  share count available by as-of and dated no later than price. Cover and
  financial-statement counts are eligible. Conflicting counts at the latest
  observation date are unavailable. Weighted-average shares never substitute.
- `price_to_sales`: market cap estimate / TTM revenue, in multiples; revenue
  must be positive. No fallback to another fiscal period.
- `fcf_yield`: (TTM operating cash flow minus TTM capex) / market cap estimate,
  as a ratio. Cash-flow windows must match each other and revenue when available.
  Negative FCF is retained as a negative yield.
- `pe_diluted_annual`: provider close / reported direct annual diluted EPS, in
  multiples. Its window must match the revenue TTM window. Quarterly/cumulative
  EPS is not added or differenced because weighted share denominators change.
  Zero/negative EPS produces unavailable P/E. No fallback to an older annual EPS
  when the latest fiscal end is quarterly. This is annual diluted P/E, not a
  universal quarterly TTM P/E.

P/E reference: [SEC financial-statement guide](https://www.sec.gov/about/reports-publications/beginners-guide-financial-statements).

## Dates and split basis

Financial facts use the existing availability/version contract. Default fiscal
end is the latest available revenue end no later than price; `--period-end`
can pin it. This version rejects prices older than seven calendar days, shares
older than 120 days, and financial period ends older than 180 days relative to
price. These are explicit coverage policies, not exchange/accounting standards.

Valuation uses **provider close**, not dividend-adjusted close: dividend
reinvestment is unsuitable for price times shares. Yahoo close is split adjusted
across its snapshot. Market cap rejects a split after the share observation
through the full snapshot price horizon. P/E separately rejects splits from EPS
period start through that horizon. This includes splits after a historical price
in a retrospective snapshot. Shares/EPS are not automatically multiplied: SEC
per-share figures may already be restated, risking double adjustment. Splits
before the share observation do not block market cap. Completeness of provider
split history and basis compatibility absent observed splits remain assumptions.

Market cap holds reported shares constant through the price date, without
inferring subsequent buybacks/issuance. It is a research estimate, not verified
contemporaneous/as-traded capitalization. The company-profile report retains
its separate unavailable verified market-cap placeholder; this mode provides
the labelled estimate.

Default selection only uses a snapshot downloaded by `--as-of`.
`--market-snapshot <id>` permits a later vintage for retrospective research,
labelled `known_at_as_of=false`. Date filtering does not turn current provider
adjustments or SEC aggregates into a validated historical trading dataset.
Results are independently available: missing/stale shares block market cap,
P/S and FCF yield but can leave annual P/E available; missing EPS does not block
the other valuations. Ratios use decimal arithmetic and no composite score.

## Multiple share classes

The universe registry identifies Alphabet (A/B/C) and Meta (A/B) as multiple-class
issuers. Their aggregate SEC shares and EPS lack verified class allocation in
this adapter. Valuation therefore blocks outstanding shares, market cap, P/S,
FCF yield and annual P/E for these issuers, including direct valuation CLI
requests. Financial/company-level growth and margins and individual traded-class
price factors remain separately available when their own inputs pass checks.
This is explicit missing coverage, not zero capitalization or zero earnings.
