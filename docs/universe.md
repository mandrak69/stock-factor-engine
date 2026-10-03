# Multi-company research universe v0.1

The curated default list is MSFT, AAPL, GOOGL, AMZN and META. The central
registry `src/stock_factor_engine/universe/registry.py` binds ticker, CIK, issuer,
security, exchange, currency, instrument type and class policy. SPY is the ETF
benchmark. GOOG is an optional second Alphabet security, sharing its company
and filings with GOOGL but never sharing a price snapshot.

| Ticker | SEC CIK | Traded class | Company-capitalization coverage |
| --- | --- | --- | --- |
| MSFT | 0000789019 | Common | Reported-share estimate |
| AAPL | 0000320193 | Common | Reported-share estimate |
| GOOGL | 0001652044 | A | Class allocation unavailable |
| GOOG | 0001652044 | C | Class allocation unavailable |
| AMZN | 0001018724 | Common | Reported-share estimate |
| META | 0001326801 | A | Class allocation unavailable |
| SPY | 0000884394 | ETF | Benchmark only |

Issuer/class evidence includes [Apple filing](https://www.sec.gov/Archives/edgar/data/320193/000032019326000013/aapl-20260328.htm),
[Alphabet annual report](https://www.sec.gov/Archives/edgar/data/1652044/000130817926000344/goog014907-ars.pdf),
[Meta 10-K](https://www.sec.gov/Archives/edgar/data/1326801/000162828026003942/meta-20251231.htm),
and [Amazon filing](https://www.sec.gov/Archives/edgar/data/83246/000110465925020276/tm258081d23_424b2.pdf).

## Download

Run from the project root using the project's environment:

```powershell
$env:SEC_USER_AGENT = 'stock-factor-engine/0.1 your-contact@example.com'
.\.venv\Scripts\python.exe -m stock_factor_engine.universe ingest
```

Use an actual contact email; it is supplied through the process environment,
not saved in Git or report output. Downloads are sequential using the existing
SEC throttling/retry contract. Each issuer imports SEC first, then its market
series. An issuer requested through two classes downloads SEC only once in that
batch. SPY imports last without SEC. Provider evidence and observation versions
remain immutable in the existing SQLite schema v2; no migration is required.

```powershell
.\.venv\Scripts\python.exe -m stock_factor_engine.universe ingest --symbols AAPL AMZN
.\.venv\Scripts\python.exe -m stock_factor_engine.universe ingest --symbols GOOGL GOOG
.\.venv\Scripts\python.exe -m stock_factor_engine.universe ingest --market-only
```

Market-only mode requires previously imported SEC company identities. Use
`--skip-benchmark` to omit SPY. Batch output gives independent SEC/market status,
run/snapshot IDs, counts, quarantine paths and failure reasons. Partial failure
exits with code 1, preserves successful imports and continues later companies.
Repeating an identical archived response adds no normalized observations;
refreshed provider adjustments can legitimately create new historical versions.

## Compare

```powershell
.\.venv\Scripts\python.exe -m stock_factor_engine.universe report --as-of (Get-Date).ToUniversalTime().ToString('o')
.\.venv\Scripts\python.exe -m stock_factor_engine.universe report --as-of (Get-Date).ToUniversalTime().ToString('o') --format json --output work/comparison.json
```

Reports read without downloading. `--database`, `--symbols` and `--output` can
select the database, subset and destination. The table contains financial YoY
growth, operating/FCF margins, annual diluted P/E, P/S, FCF yield, momentum 12-1,
annualized volatility, maximum drawdown and 252-session return difference versus
SPY. JSON additionally contains market-cap estimates, 252-session asset return,
momentum excess, exact input dates, formulas, SEC evidence, financial details,
snapshot identities and per-metric availability. Ratios render as percentages
in the table; return differences are percentage points. Dates are shown because
different fiscal calendars and availability can imply different reporting ends.

Each series uses its latest snapshot downloaded by as-of; later vintages never
enter automatically. Trading dates are compared strictly for excess returns.
Missing SPY only blocks comparison factors. Missing company data keeps a row
with NA and reasons. A report with some missing metrics is still a valid report;
it does not fabricate values or drop companies. Financial conflicts fail closed
with their exact periods; no rounding tolerance or arbitrary value precedence
is inferred. Missing capex cannot be replaced by zero or an unrelated asset tag.

Alphabet and Meta have multiple share classes. This version does not allocate
SEC aggregates or sum class capitalizations, so market cap, P/S, FCF yield and
annual P/E are unavailable for them. Company-wide fundamentals and per-class
price factors remain independent. P/E also requires matching direct annual EPS:
quarterly reporting ends can have valid P/S but no annual P/E.

This is a present-day curated research list, not an as-of historical investment
universe. Historical predecessor tickers, listing dates, share-class changes,
delisted companies and survivorship bias are not certified by this registry.
Existing provider/SEC vintage limits and valuation freshness/basis policies
apply; this report does not rank securities or implement a trading backtest.
