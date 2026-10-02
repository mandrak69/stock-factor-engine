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
