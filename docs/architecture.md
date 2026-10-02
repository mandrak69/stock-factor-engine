# Architecture

## 1. Architectural principle

The core invariant is:

> Every historical decision must be reproducible using only observations whose availability timestamp is not later than the decision timestamp.

The architecture therefore treats data availability/provenance as first-class domain data rather than an implementation detail.

## 2. High-level flow

```text
External Sources
  -> Collectors / importers
  -> Raw payload/evidence
  -> Normalization
  -> Canonical identity
  -> Point-in-time stores
  -> Derived financial/market metrics
  -> Hard eligibility filters
  -> Factor calculations
  -> Peer normalization
  -> Versioned score
  -> Ranking
  -> Portfolio construction
  -> Backtest
  -> Performance + explanation
```

Broker integration, when added, consumes target portfolios downstream and is not part of this flow.

## 3. Initial package layout

```text
stock_factor_engine/
  models/          canonical domain objects
  point_in_time/   availability-aware selection policies

Future slices:
  providers/
    sec/
    market_data/
  ingestion/
  fundamentals/
  screening/
  factors/
  scoring/
  ranking/
  portfolio/
  backtesting/
  performance/
  storage/
```

Packages are introduced when the first real behavior exists; empty framework layers are avoided.

## 4. Identity boundary

`Company`, `Security`, and `TickerAssignment` are distinct.

- company = issuer/business identity;
- security = tradeable listed instrument;
- ticker assignment = time-dependent symbol used to address that security.

Ticker changes therefore do not create a new company and do not mutate historical observations.

## 5. Financial availability model

`Filing` records both economic/reporting time and information-availability time.

```text
period_end
filed_date
accepted_at
available_at
```

`available_at` is the only timestamp used to decide whether the filing/fact is available to a historical strategy evaluation.

A `FinancialFact` is tied to the filing/version that made that fact available. New amendments are append-only versions rather than destructive updates.

## 6. Point-in-time query contract

Point-in-time services must expose `as_of` explicitly.

Bad:

```python
latest_financials(company_id)
```

Good:

```python
financials_as_of(company_id, as_of)
```

The system should make an accidental unbounded "latest" query difficult in research/backtest paths.

## 7. Time handling

All timestamps are timezone-aware. Internal instants are normalized to UTC.

Dates such as fiscal period end remain dates when no time-of-day meaning exists.

## 8. Restatement policy

Facts are append-only. A later filing may supersede an earlier filing for the same concept/period, but the earlier fact remains queryable for historical `as_of` dates.

The selector chooses the most recently available valid fact at or before `as_of` according to explicit keys:

```text
company
concept
unit
period_start
period_end
instant/duration shape
```

When multiple facts are available, later `available_at` wins; ties are rejected unless a deterministic source rule exists.

## 9. Testing strategy

The earliest tests target the most dangerous failure modes:

- future filing leakage;
- amendment/restatement leakage;
- ambiguous availability ties;
- timezone-naive historical query timestamps;
- ticker validity across rename boundaries.

Later tests add factor formulas, ranking invariants, portfolio constraints, and full point-in-time integration fixtures.
