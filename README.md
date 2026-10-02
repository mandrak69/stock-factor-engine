# stock-factor-engine

An explainable, point-in-time stock selection and backtesting engine for long-term factor strategies.

The first strategy is **Conservative Compounder v0.1**:

- 40% Quality
- 25% Value
- 20% Momentum
- 15% Risk
- quarterly rebalance
- hard eligibility filters before scoring
- point-in-time data only
- S&P 500 Total Return benchmark

## Why this project exists

The project is designed to answer a narrower question than a trading bot:

> Given only information that was publicly available at a historical point in time, which eligible stocks would the strategy have selected and why?

The system deliberately separates stock selection, portfolio construction, backtesting, and eventual broker execution.

## Current status

The initial slice contains:

- product/system specification;
- architecture boundaries;
- company/security/ticker identity models;
- SEC filing and financial fact models;
- point-in-time financial fact selection;
- tests for future-information and restatement leakage.

No broker integration, live trading, ML model, or UI is in scope yet.

## Development

```bash
python -m pip install -e '.[dev]'
pytest
```

See `docs/system-design-and-product-specification.md` and `docs/architecture.md`.

## Local database

```bash
python -m stock_factor_engine.storage --database data/engine.sqlite
```

SQLite schema migrations run automatically on initialization. Source JSON will
live under `data/raw/`; local data is excluded from Git. See
`docs/storage-design.md` for the schema, provenance and time contracts.

## SEC ingestion

```powershell
$env:SEC_USER_AGENT = 'stock-factor-engine/0.1 your-contact@example.com'
python -m stock_factor_engine.providers.sec --cik 0000789019
```

Use your actual contact address. See `docs/sec-ingestion.md` for supported
concepts, archived replay, quarantine and historical-data limitations.

## TTM metrics and coverage

```powershell
python -m stock_factor_engine.fundamentals --as-of 2026-10-02T00:00:00Z
```

Reports point-in-time revenue, operating income, operating cash flow, capital
expenditure and free cash flow with source explanations. See `docs/ttm-metrics.md`
for period validation, supported fiscal durations and calculation limits.

## Balance and quality metrics

```powershell
python -m stock_factor_engine.fundamentals --as-of 2026-10-02T00:00:00Z --balance
```

Reports debt, cash, invested capital, effective tax rate, ROIC proxy and interest
coverage with independent availability statuses. See `docs/balance-metrics.md`
for formulas and missing-data policies. Replaying an archived SEC run imports
the newly mapped concepts without another download.
