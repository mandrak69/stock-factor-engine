# Price research factors v0.1

The first comparison is Microsoft against SPY. SPY is an ETF market-price proxy
for the S&P 500; it is not the official S&P 500 Total Return index. Its price
can reflect fund expenses, tracking differences and premiums/discounts. Fund
description: https://www.ssga.com/us/en/individual/etfs/state-street-spdr-sp-500-etf-trust-spy

## Run and inspect

```powershell
python -m stock_factor_engine.providers.market --symbol SPY
python -m stock_factor_engine.factors --as-of (Get-Date).ToUniversalTime().ToString('o')
```

The report contains formulas, values as decimal strings, effective price dates,
observation counts, snapshot IDs, sources and independent availability statuses.
Values are ratios: 0.10 means 10%; an excess return of 0.10 means ten percentage
points. Data lives in the existing SQLite schema v2; no new database is needed.
Calculations read immutable price snapshots and do not persist derived scores.

## Definitions

- **Momentum 12-1:** let t be the last completed calendar month-end at the
  requested New York date. Return from t minus 12 months to t minus one month,
  using the last trading date on or before each anchor. This covers eleven
  months and excludes the most recent completed month. For October 2, 2025,
  anchors are September 30, 2024 and August 31, 2025 (trading August 29).
- **Volatility 252:** sample standard deviation (ddof=1) of 252 simple daily
  adjusted-close returns, multiplied by sqrt(252). This needs 253 prices.
- **Maximum drawdown 252:** minimum of price/running peak minus one over the
  latest 253 prices. It is zero or negative. The peak starts at the beginning
  of this window; older all-time peaks do not enter the calculation.
- **Return 252:** last adjusted close/first adjusted close minus one over the
  same 253 prices. This is a fixed session window, not a calendar-year return.
- **Excess return/momentum:** Microsoft minus SPY for the corresponding window;
  an arithmetic percentage-point difference, not a relative-price ratio.

Both instruments use Yahoo dividend-adjusted close. Splits and dividends must
not be applied again. These are provider-based research returns, without
trading costs or an independently verified reinvestment model.

## Coverage and time

All inputs must have unique, strictly chronological dates. The current New York
session is excluded. A final price more than seven calendar days old makes all
factors unavailable. Annual windows require 253 prices spanning 330–400 days;
momentum requires at least 200 prices and anchors no more than seven days old.
Any gap longer than seven days rejects that factor's window. These checks catch
large gaps but do not certify every exchange holiday or missing session.

Comparisons require identical boundaries and identical trading-date sets.
Missing observations are never silently removed through an inner join. Each
instrument can still have its own available factors when comparison is unavailable.

By default the CLI chooses the latest snapshot downloaded by `--as-of` for
each instrument. It refuses to automatically use a later download. Explicit
`--asset-snapshot` and `--benchmark-snapshot` allow retrospective research,
with `known_at_as_of=false` if that snapshot was downloaded later. Filtering
dates alone cannot make a current adjusted historical series point-in-time:
future corporate actions and provider revisions may affect older prices.
Even a snapshot known at the requested instant is not proof that every provider
adjustment was historically available. This version is not a validated trading
backtest, portfolio score or investment recommendation.
