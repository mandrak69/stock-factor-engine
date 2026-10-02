# System Design & Product Specification

**Project:** stock-factor-engine  
**Status:** Living specification  
**Initial strategy:** Conservative Compounder v0.1

## 1. Purpose

Build an explainable stock-selection and backtesting system that can answer, for any historical evaluation date:

> Which stocks were eligible, how were they scored, what portfolio would the strategy have constructed, and what information was actually public at that time?

The first product is a research/backtesting engine, not an automated trading bot.

## 2. Primary goals

The system must:

1. maintain canonical company and security identity independently of ticker changes;
2. ingest market, reference, and financial-statement data with provenance;
3. preserve point-in-time availability so future information cannot leak into historical decisions;
4. calculate transparent fundamental and market-derived metrics;
5. implement versioned hard filters, factors, scoring, ranking, and portfolio rules;
6. explain every score down to raw values, normalization, source data, and timestamps;
7. backtest using only data available as of each rebalance decision;
8. model delistings, splits, dividends, transaction costs, and benchmark returns before results are treated as credible;
9. compare strategy variants without silently modifying previous versions;
10. keep eventual broker execution outside the research core.

## 3. Non-goals for V1

V1 does not aim to:

- predict next-day prices;
- perform high-frequency or intraday trading;
- use machine learning to select stocks;
- execute real-money orders;
- support every global exchange or asset class;
- treat a present-day index constituent list as a valid historical universe;
- optimize weights with a black-box portfolio optimizer.

## 4. Initial universe

Conservative Compounder v0.1 targets US-listed large/mid-cap common equities.

Initial exclusions:

- financial companies;
- REITs;
- penny stocks;
- securities without sufficient price history;
- securities that fail liquidity, profitability, cash-flow, leverage, or interest-coverage filters.

Financials and REITs require domain-specific accounting rules and will be introduced as separate strategy/universe variants rather than forced through inappropriate generic ratios.

## 5. Conservative Compounder v0.1

### 5.1 Hard filters

Before scoring, a security must satisfy:

- market cap >= USD 5 billion;
- price >= USD 5;
- 60-day average daily dollar volume >= USD 20 million;
- at least 3 years of price history;
- TTM EBIT > 0;
- TTM operating cash flow > 0;
- net debt / EBITDA <= 4x, or net cash;
- EBIT / interest expense >= 3x;
- not in the initial excluded industry groups.

A failed hard filter makes the security ineligible. A strong factor score cannot override it.

### 5.2 Score composition

| Component | Weight |
|---|---:|
| Quality | 40% |
| Value | 25% |
| Momentum | 20% |
| Risk | 15% |

### 5.3 Factors

Quality (40%):

- ROIC 8%;
- gross profitability 5%;
- FCF margin 6%;
- operating-margin stability 4%;
- earnings stability 4%;
- 5-year revenue CAGR 5%;
- net debt / EBITDA 4%;
- interest coverage 4%.

Value (25%):

- FCF yield 9%;
- earnings yield 6%;
- EV / EBITDA 5%;
- valuation relative to own history 5%.

Momentum (20%):

- 12-1 month momentum 10%;
- 6-1 month momentum 5%;
- relative strength versus benchmark 5%.

Risk (15%):

- 1-year realized volatility 5%;
- 3-year maximum drawdown 5%;
- downside volatility 5%.

### 5.4 Normalization

Factor raw values are not combined directly.

For each evaluation date:

1. determine the eligible comparison universe using only point-in-time information;
2. winsorize extreme factor values according to the strategy version;
3. normalize metrics within an appropriate peer group (initially sector where applicable);
4. convert the metric to a 0-100 percentile score;
5. reverse scores for metrics where lower is better;
6. persist raw, adjusted, percentile, score, peer group, and strategy version.

### 5.5 Portfolio construction

Initial rules:

- rebalance quarterly;
- 20 positions;
- equal-weight target portfolio;
- normal target weight approximately 5%;
- maximum single-security weight 7.5%;
- maximum sector weight 25%;
- entry requires score >= 70 and top 10% rank;
- existing position can remain while in top 25%;
- exit when below top 30% or when a hard filter fails.

The difference between entry and exit thresholds deliberately reduces turnover.

## 6. Point-in-time correctness

Point-in-time correctness is a product requirement, not a backtest optimization.

For every financial filing distinguish at minimum:

- `period_end`: when the reported economic period ended;
- `filed_date`: filing date assigned by EDGAR;
- `accepted_at`: time EDGAR accepted the submission;
- `available_at`: earliest timestamp at which our research system is permitted to use the filing.

`available_at` must never be earlier than `accepted_at`. It may be later when the data source has a dissemination/import delay or when conservative availability rules require it.

Historical queries use:

```text
available_at <= as_of
```

not `period_end <= as_of`.

A filing about June 30 results that became public in August cannot influence a July portfolio.

### 6.1 Amendments and restatements

Later amendments/restatements do not rewrite history. They become new versions with their own `available_at` and supersession/provenance metadata.

A backtest before the restatement sees the older public value. A backtest after the restatement may see the newer value according to the fact-selection policy.

## 7. Identity

Ticker is not company identity.

Canonical layers:

```text
Company
  -> Security
       -> TickerAssignment history
```

A company has a stable internal ID and SEC CIK when available. A security represents a listed instrument. Ticker symbols are time-bounded aliases of a security.

Historical resolution must be able to answer:

> Which ticker represented this security on the evaluation date?

without rewriting older observations when a ticker changes later.

## 8. Data-source policy

Initial source priorities:

- SEC EDGAR: authoritative US filing/submission and XBRL source;
- a market-data provider: daily OHLCV, corporate actions, delistings, and adjusted/total-return support;
- optional secondary financial-data provider: convenience and reconciliation, never silent replacement of SEC provenance.

Every imported record retains provider/source identifiers and retrieval metadata.

## 9. Strategy versioning

A strategy version is immutable once used for a formal backtest.

Changing any material rule creates a new version, including:

- factor formula;
- factor weight;
- hard filter;
- winsorization rule;
- peer-group normalization;
- entry/hold/exit threshold;
- rebalance schedule;
- portfolio constraint.

`conservative_compounder_v0_1` is never retroactively changed to make historical results look better.

## 10. Backtest requirements

A credible backtest must eventually model:

- historical security universe rather than today's survivors;
- delistings;
- ticker changes;
- splits and other corporate actions;
- dividends/total return;
- point-in-time financial availability;
- realistic rebalance timing;
- transaction costs and slippage;
- benchmark total return;
- no same-close execution when the signal itself requires that close unless execution timing explicitly permits it.

Primary metrics:

- CAGR;
- total return;
- annualized volatility;
- maximum drawdown;
- Sharpe ratio;
- Sortino ratio;
- worst calendar year;
- drawdown recovery time;
- turnover;
- rolling 1/3/5-year relative performance.

## 11. Safety boundary: signal is not an order

The research engine produces rankings and target portfolios.

Future architecture, if paper trading is introduced:

```text
Research / Ranking
      -> Target Portfolio
      -> Portfolio Diff
      -> Risk Manager
      -> Order Intent
      -> Broker Adapter
```

Broker execution must never be called directly from factor calculation or ranking code.

## 12. V1 delivery sequence

1. project skeleton and domain model;
2. SEC point-in-time filing/fact ingestion model;
3. daily market-data ingestion;
4. derived fundamental metrics;
5. hard filters;
6. 18 factor calculations;
7. normalization and scoring;
8. ranking/explain command;
9. point-in-time backtest engine;
10. benchmark/performance analytics.
