# Daily market data v0.1

## Scope and provider

The initial importer supports Microsoft common stock (USD, NASDAQ) using Yahoo
Finance's chart JSON endpoint. It needs no API key and no dataframe dependency.
This is an unofficial research adapter, not an exchange feed or a guaranteed
historical point-in-time service. Other symbols require explicit issuer/security
identity configuration before support is expanded.

```powershell
.\.venv\Scripts\python.exe -m stock_factor_engine.providers.market
```

This downloads the full available daily history, including splits and dividends.
The output includes `snapshot_id`, new observation counts, first/last dates and
quarantine count. Today's exchange-session candle is excluded even if a provider
returns partial intraday data. US dates are converted with America/New_York using
`tzdata`, so daylight-saving changes are handled correctly.

## Original versus adjusted data

The exact original provider JSON bytes are stored under
`data/raw/market/yahoo_chart/MSFT/` with source URL, retrieval timestamp and
SHA-256. Provider OHLC and volume are preserved as supplied. **Yahoo historical
OHLC already reflects split adjustments; these columns are not verified
as-traded prices.** The provider adjusted close additionally reflects dividend
adjustments. The explicit snapshot basis is
`provider_split_adjusted_ohlc_dividend_adjusted_close`.

Returns for this research slice use:

```text
adjusted_close[t] / adjusted_close[t-1] - 1
```

Do not multiply this return by a split ratio or add a dividend again. Corporate
actions are separate evidence for explaining/checking adjustment dates. A split
stores new shares divided by old shares, e.g. 2 means 2:1. Dividend amounts are
provider event amounts, not independently verified declaration or payment data.
The raw JSON retains numerator/denominator and original event timestamps.

Prices stay Decimal representations of provider values, including its floating
point artifacts. No speculative repairs are applied. Invalid OHLC, missing or
nonpositive prices, and invalid volume are quarantined. An action without a valid
bar fails the run. Source metadata must match MSFT, USD equity and the supported
exchange timezone. A failed run retains raw evidence and its error.

## Schema v2 and immutable snapshots

- `market_snapshots`: explicit series vintage and basis, source/raw document,
  security and retrieval instant.
- `daily_prices`: unique observation versions per security/source/trading date;
  provider OHLC, adjusted close and volume.
- `corporate_actions`: unique dividend/split observation versions.
- `snapshot_prices` and `snapshot_actions`: exact membership of each vintage.

Repeat imports preserve evidence and create a new snapshot, while identical
normalized observations are reused. A changed historical adjusted close creates
a new version; it never overwrites the older series. Queries use one explicit
snapshot, so old and new adjustment vintages cannot be mixed accidentally.
All five tables are append-only. Migration v2 preserves the existing financial
schema/data. Import requires the Microsoft company to exist from SEC ingestion.
The initial security/ticker validity starts at the first observed Yahoo date;
this is observed-history metadata, not a validated historical universe record.

## Reports and replay

```powershell
.\.venv\Scripts\python.exe -m stock_factor_engine.providers.market --report-snapshot <snapshot_id> --as-of 2026-10-02T00:00:00Z
.\.venv\Scripts\python.exe -m stock_factor_engine.providers.market --replay-snapshot <snapshot_id>
```

Reports open the database read-only. Replay checks raw-file hashes and path
containment and records a new snapshot without another download.

The report includes adjusted returns around dividends/splits, date coverage,
counts and any gaps longer than seven calendar days. It does not claim to detect
every missing exchange session; an exchange calendar is not yet implemented.
Daily observations are usable by this report only starting at the next local
calendar midnight. This deliberately conservative rule excludes same-session
data without guessing early closes or provider latency.

`snapshot_known_at_as_of` says whether the selected response had been downloaded
by the requested instant. If false, the result is a retrospective analysis using
a newer snapshot, not proof that those values were known then. Even if true,
corporate-action announcement times are not supplied, and current adjusted
histories are not a substitute for a fully verified point-in-time feed.

## Limits before portfolio use

Do not use these historical OHLC levels with historical shares outstanding to
calculate market cap, as-traded execution prices or original-dollar liquidity.
That requires a source of verified as-traded prices/volume or a fully audited
split reconstruction. No price-based hard filters are enabled by this slice.
Total-return momentum/volatility research may use a consistent adjusted vintage,
with the snapshot caveats above. Historical index membership, delistings,
survivorship controls and fill/cost models remain future work.

## Verification

Local Microsoft import: 10,217 daily bars from March 13, 1986 through October 1,
2026; 91 dividends and 9 splits. Zero quarantined observations. Replaying the
saved response added zero bars/actions. Tests cover migrations, immutable
vintages, corrupt evidence, partial sessions, DST, split/dividend double-counting,
invalid observations and historical cutoff labeling.

Provider behavior references:

- [yfinance history adapter source](https://github.com/ranaroussi/yfinance/blob/main/yfinance/scrapers/history.py)
- [yfinance price repair documentation](https://ranaroussi.github.io/yfinance/advanced/price_repair.html)

These references explain adapter/adjustment behavior; yfinance is not installed
or used by this importer. No Yahoo availability guarantee is implied.
