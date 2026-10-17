# CompoundRank Market Regime v0.1 / integration v0.2

Project hypotheses approved and frozen on 2026-10-17, before evaluating this
overlay's historical returns. These thresholds were newly agreed in the chat;
they are not a recovered copy of the unavailable earlier patch files.
Stock-selection Strategy v0.1 remains byte-for-byte unchanged.

## Scoring

Each input receives a 0–100 score, interpolated linearly between the outer
anchors and clamped outside them. Inputs are ratios, not percentage numbers.

| Component | Weight | Score 0 | Score 50 | Score 100 |
| --- | ---: | ---: | ---: | ---: |
| Breadth above adjusted-close 200DMA | 35% | 30% | 50% | 70% |
| RSP/SPY relative return over 63 sessions | 25% | -5% | 0% | +5% |
| SPY adjusted-close distance to 200DMA | 20% | -10% | 0% | +10% |
| VIX spot raw close | 10% | 30 | 22.5 | 15 |
| HYG/LQD relative return over 63 sessions | 10% | -3% | 0% | +3% |

Relative return = `(asset_end / asset_start) / (benchmark_end / benchmark_start) - 1`,
using adjusted close, 64 observations and all 64 identical dates aligned to SPY.
No intersection join or fallback to different start/end dates is permitted.
SPY trend = latest adjusted close / mean of 200 adjusted closes - 1.
The completion convention matches SQLite research reports: only sessions before
the as-of New York calendar date are available. No same-session fills are implied.
The latest SPY session is the reference date; all market inputs must end on it.
A reference price older than seven calendar days is unavailable.

## Decision precedence

1. Any missing/nonfinite required input: `unavailable`, no score or exposure.
   Do not redistribute its weight or substitute zero. Execution must stop.
2. SPY trend > 0 AND breadth < 0.50 AND RSP/SPY < 0: `NARROW_MARKET`, exposure 0.60.
3. Otherwise score >= 65: `RISK_ON`, exposure 1.00.
4. Otherwise score >= 40: `NEUTRAL`, exposure 0.75.
5. Otherwise: `RISK_OFF`, exposure 0.25.

Narrow-market precedence applies even if the weighted score is below 40.
Equality at 50% breadth, zero SPY trend or zero relative return is not narrow.

## Optional VX observation

There is no built-in verified VX front-month provider. No continuous ticker is
invented. An optional caller-supplied observation must name the actual contract,
expiry, source and exact signal session, with a finite positive close and an
expiry strictly after that session. The caller must verify it is the true
front-month; supplying metadata alone does not independently certify the source.

When spot VIX > supplied VX close, subtract 25 from the VIX component score,
floored at zero. This removes at most 2.5 points from the weighted total.
This is a spot/front-month stress comparison, not a measurement of the slope
between two futures maturities. Without VX the spot-only VIX component remains
available and the optional observation is explicitly marked unavailable.

## Membership and price provenance

Breadth uses exact-date, independently verified complete S&P 500 membership.
Every member must have all 200 dates matching the SPY window; one missing
member or missing observation makes the entire breadth unavailable. Securities
outside that membership are ignored. No curated five-stock list, present-day
constituents, sector exclusions or stock-selection eligibility filters apply.

`MembershipProvider.members_on(session)` returns a `Membership` or None.
The JSON adapter is a manual import contract, not an independently verified
historical provider. Its input is:

```json
{
  "session": "2024-10-07",
  "source": "independently verified historical source and evidence reference",
  "complete": true,
  "security_ids": ["stable security IDs already present in engine.sqlite"]
}
```

The date is the reference signal session, not the as-of timestamp. A file for
another date fails closed. The caller must provide the actual complete list;
the shape example above is not an investable universe. Ingestion of constituent
prices is separate from the five market instruments. Reports select only market
snapshots downloaded by as-of and expose the snapshots used, including member
prices. Downloading prices today does not create historically known vintages.

Still required for a defensible historical backtest: a verified membership
source with effective intervals, completeness/evidence and revision history;
historical security/ticker mappings; prices for delisted/renamed members and
complete windows; and a documented policy for historical provider vintages.
There is no automatic current-membership fallback.

## CLI and integration

```powershell
python -m stock_factor_engine.regime ingest --data-dir data
python -m stock_factor_engine.regime report --database data/engine.sqlite --as-of 2026-10-17T18:00:00+00:00
python -m stock_factor_engine.regime report --database data/engine.sqlite --as-of 2026-10-17T18:00:00+00:00 --constituents-json work/verified-membership.json
```

Optional VX flags must be supplied together: `--vix-front-month`, `--vix-session`,
`--vix-contract`, `--vix-expiry`, `--vix-source`. No VX input is downloaded.
The report opens SQLite read-only. Ingest archives Yahoo evidence and reuses
existing replay/versioned storage. SPY/RSP/HYG/LQD are ETFs; ^VIX is an index
whose dates use America/Chicago. Its raw close is retained even without an
adjusted-close column, and its spot input never uses total-return calculations.

`evaluate_market_regime` is independent of stock ranking. `apply_exposure`
scales the strategy's normalized stock target weights to the allowed exposure
and leaves the rest in cash. It cannot change ranks, components, eligibility or
relative stock allocations. An unavailable decision raises rather than issuing
targets. The caller owns next-session-open scheduling; there is no broker or
historical overlay backtest runner in this integration.

## Validation protocol

Do not optimize these thresholds to maximize historical CAGR. Before any
backtest, predeclare development/untouched evaluation periods. Measure drawdown,
missed upside, exposure, regime transitions, turnover and costs, and examine
small threshold perturbations for stability without choosing the best CAGR.
Full five-component historical validation is pending the membership provider.
