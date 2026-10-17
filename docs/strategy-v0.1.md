# Strategy v0.1 — Greenblatt benchmark and active rotation variants

This document freezes the first research specification before historical results
are inspected. The goal is to distinguish rules inherited from published ideas
from rules that are explicit project hypotheses.

## Scope

The strategy kernel lives in `src/stock_factor_engine/strategy/v0_1.py`. It is a
pure ranking/portfolio-construction layer: it does not download data, call SEC or
market providers, execute orders, or silently substitute missing observations.
Inputs must already be point-in-time snapshots containing only information that
was available at the requested `as_of` instant.

The current repository's curated MSFT/AAPL/GOOGL/AMZN/META registry is **not** a
historical S&P 500 membership source. A validated historical backtest must not
use today's constituents backwards. Until a point-in-time constituent source is
added, this module is a strategy kernel and testable specification, not a claim
of completed S&P 500 backtest coverage.

## Frozen v0.1 universe

- point-in-time S&P 500 membership;
- exclude Financials and Utilities;
- price >= $5;
- at least 252 completed trading sessions;
- positive TTM EBIT;
- **no additional market-cap cutoff** while the universe is S&P 500;
- financial inputs must be available by `as_of`, not merely belong to a period
  ending before `as_of`.

If a later version broadens the universe to Russell 3000/all-US equities, a
`market cap >= $1B` filter is a candidate rule and must be tested separately.

## Ranking inputs

### Greenblatt benchmark

The benchmark ranking uses two cross-sectional percentiles:

```text
Greenblatt score = 50% Return-on-Capital percentile
                 + 50% EBIT/EV percentile
```

The implementation calls the inputs `return_on_capital` and `earnings_yield`.
The data adapter must document the exact accounting construction. Do not label a
ROIC proxy or a different EV definition as exact Greenblatt ROC without saying
so.

### Conservative Compounder extension

```text
Quality = 50% ROC
        + 30% FCF margin
        + 20% inverse Net Debt / EBITDA

Value = 60% EBIT / EV
      + 40% FCF yield

Momentum = 60% 12-1 momentum
         + 40% 6-1 momentum

Risk = 60% inverse 63-session annualized volatility
     + 40% inverse abs(252-session maximum drawdown)

Final score = 40% Quality
            + 25% Value
            + 20% Momentum
            + 15% Risk
```

Each raw metric is winsorized cross-sectionally at the 1st/99th percentile,
then converted to a 0–100 percentile score. Ties receive the average percentile
position. Lower leverage, volatility, and drawdown magnitude are better.
Missing/non-finite required inputs exclude that security from the relevant
ranking; zero is never substituted for missing data.

## Portfolio variants

### A — Classic Greenblatt control

- rank on the Greenblatt score;
- top 30;
- equal weight;
- annual rebalance;
- the annual scheduler/backtest is responsible for holding until the next
  scheduled rebalance rather than reacting to intermediate rank changes.

### B — Monthly rank rotation

- evaluate monthly;
- BUY when rank <= 20;
- KEEP an existing holding while rank <= 35;
- SELL when rank > 35 or the security becomes ineligible;
- equal-weight the resulting portfolio.

`20/35` is a project hypothesis. The buffer is intentionally wider than the
entry threshold to reduce churn; it is not presented as a Greenblatt rule.

### C — Weekly continuous reweight

- evaluate weekly;
- use top 35;
- raw target weight = `36 - rank`;
- normalize raw weights to 100% invested.

This is inspired by the idea of continuously moving more capital toward more
attractive relative-value opportunities. It is **not** Gotham's proprietary
weighting formula.

## Signal, fills, and costs

The frozen backtest contract is:

```text
signal: completed-session close(t)
fill:   next-session open(t+1)
```

The strategy must not use close(t) information and also pretend to fill at the
same close.

Base transaction cost is 10 bps per traded notional with sensitivity at
0/10/25 bps. The cost estimator therefore treats a 100% A -> B switch as one
full sell plus one full buy: 200% traded notional, or 20 bps at the 10-bps base
assumption.

## Rule provenance

| Rule | Origin | Status |
| --- | --- | --- |
| good business + cheap business / ROC + earnings yield | Greenblatt | source-inspired core |
| exclude Financials and Utilities | Greenblatt | benchmark rule |
| top 30 / equal-weight annual control | Greenblatt | benchmark rule |
| more capital toward relatively more attractive names | Gotham-inspired | concept only; exact Gotham implementation is proprietary |
| 12-1 momentum | academic momentum literature | source-inspired factor |
| point-in-time inputs / next-session execution | backtesting practice | anti-look-ahead contract |
| no extra market-cap filter for S&P 500 | project decision | frozen v0.1 |
| 20/35 monthly buffer | project decision | test hypothesis |
| weekly `36-rank` weights | project decision | test hypothesis |
| 40/25/20/15 factor mix | project decision | test hypothesis |
| 1%/99% winsorization | project decision | robustness choice |
| 10 bps cost, 0/10/25 sensitivity | project decision | backtest assumption |

## Primary references behind the sourced ideas

- Joel Greenblatt, *The Little Book That Beats the Market* / *The Little Book
  That Still Beats the Market*.
- Magic Formula Investing FAQ: https://www.magicformulainvesting.com/Home/Faqs
- Gotham Funds strategy materials: https://www.gothamfunds.com/strategy
- Kenneth French Data Library, Momentum Factor description:
  https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library/det_mom_factor.html
- Asness, Frazzini, Pedersen, *Quality Minus Junk*:
  https://www.aqr.com/Insights/Research/Working-paper/Quality-minus-Junk

These references motivate parts of the design. Numeric project choices above
remain our hypotheses and must not be retroactively tuned on the same test
period and then presented as independent evidence.

## Integration gaps before the first defensible historical backtest

1. Add a point-in-time S&P 500 constituent history with membership start/end
   dates and provenance.
2. Produce exact or explicitly labelled proxy inputs for ROC, EBIT/EV and
   Net Debt/EBITDA from point-in-time filings.
3. Add 6-1 momentum and 63-session volatility to the market-factor adapter.
4. Build the scheduler/simulator for annual, monthly and weekly rebalance dates,
   next-session-open fills, delistings, corporate actions and cash.
5. Report CAGR, total return, max drawdown, volatility, Sharpe, Sortino, annual
   turnover, trade count, average holding period, transaction costs, best/worst
   year, positive-year percentage, rolling 1y/3y return, excess CAGR vs S&P 500,
   and excess return per unit of turnover.

Do not optimize thresholds until this frozen v0.1 has been run on a predeclared
sample and then checked on an untouched out-of-sample period.
