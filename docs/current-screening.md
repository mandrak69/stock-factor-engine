# Current CompoundRank screening

The current adapter reuses the frozen Strategy v0.1 kernel and the approved
Market Regime v0.1 scoring model. It does not alter their thresholds or weights.
All new code is in `stock_factor_engine.current`; the legacy local `main` branch
remains separate and preserved. No static five-company registry is used as an
S&P membership substitute.

## Decision and source timing

For the first requested report the decision is 2026-11-20 21:30 UTC / 16:30 New
York. The comparison decision is 2026-11-13 21:30 UTC. The current adapter has an
explicit completed-close mode, allowing the decision day's prices after 16:15
New York to cover both equities and the VIX close. Existing SQLite/regime
callers retain their conservative next-midnight default. No next-session fills
or actual trades are simulated here.

SEC submissions provide `accepted_at`; existing parser policy sets `available_at`
to acceptance plus five minutes. Required historical submissions pages are merged
with recent submissions to preserve original acceptance evidence. Only available filing-backed fact versions
and financial periods ending by the decision session are used. Later filings
cannot rewrite an earlier view. Raw responses, retrieval times and SHA-256 hashes
are saved outside Git. The input source vintage is downloaded retrospectively,
so this is not a claim of a complete contemporaneously archived data snapshot.
Current-only API market-cap fields and undated current-constituent lists are not
used. No original SEC source is inferred from a mere fiscal period ending date.

Membership is an explicit dated manifest with publication time, effective date,
verified-through date, source revision and members (ticker/company/GICS sector/CIK).
For this run a November 8 Wikipedia revision is checked against the November 4
official S&P DJI change and its subsequent release archive. This community
roster is not a licensed S&P constituent feed. The old local historical CSV
ending in August is not used for November. Future publication times or dates
outside the manifest coverage stop the run.

## Exact factors

The universe excludes Financials and Utilities, price below $5, fewer than 252
completed sessions, nonpositive TTM EBIT and nonpositive Capital Employed.
There is no market-cap cutoff. A name with exactly 252 price observations still
lacks the 253 prices required by the 252-session momentum interval, so that
factor is explicitly unavailable.

- Operating NWC = (current assets - cash) - (current liabilities - current debt).
- Capital Employed = Operating NWC + net PP&E. No invested-capital/ROIC proxy.
- ROC = TTM EBIT / Capital Employed.
- FCF margin = (TTM CFO - TTM CapEx) / TTM revenue.
- EBITDA = TTM operating income + TTM depreciation/depletion/amortization.
  Only an explicit combined D&A fact or complete separate depreciation and
  intangible-amortization facts are used. Missing D&A is not zero, and a tag
  including accretion is not silently treated as exact D&A.
- Net debt / EBITDA = (total debt - cash) / TTM EBITDA.
- EV = market-cap estimate + total debt - cash.
- Earnings yield = TTM EBIT / EV; FCF yield = TTM FCF / market-cap estimate.
- Market-cap estimate = latest publicly available actual outstanding shares
  times decision-session raw close. Split events between share observation and
  decision reconcile units. Provider close is also restored for splits after a
  historical decision session. Weighted-average shares are never substituted.
  Issuers with multiple listed classes are unavailable without a justified
  company capitalization; one class price is not multiplied by aggregate shares.
- Momentum 12-1 = P[t-21]/P[t-252]-1, 6-1 = P[t-21]/P[t-126]-1.
- vol63 = sample standard deviation of the last 63 adjusted-close simple
  daily returns times sqrt(252), requiring 64 prices.
- DD252 = worst running-peak drawdown within the last 252 adjusted prices.

TTM accounting windows must match. The latest available income/revenue/cash-flow
reporting end anchors the calculation; an older EBIT period is never substituted
when the latest period is incomplete. Ambiguities outside contributing windows
do not block an unrelated factor. Explicit debt totals and complete components
must agree. Ambiguous facts, nonpositive ratio
denominators, missing short debt and incomplete price windows are explicit
unavailable reasons; no zero assumptions or partial-date intersections are used.
Percentiles and 1%/99% winsorization are owned solely by the existing kernel.
Risk orientation remains higher = less volatility/drawdown.

## Report and portfolio semantics

```powershell
python -m stock_factor_engine.current --evidence-dir data/current-2026-11-20 --output data/reports/current-2026-11-20
python -m pytest
```

The evidence folder must contain `membership.json` and raw gzip responses plus
metadata matching the provider URLs and SHA-256 hashes. The evidence acquisition
helper `EvidenceStore` restricts provider requests to the corresponding HTTPS
host and rate-limits SEC to fewer than two starts per second. Yahoo requests
use a generic User-Agent with no contact email. Any identifying SEC contact
must be explicitly authorized before the downloader is invoked with it.

Outputs: full eligible ranking CSV, previous ranking CSV, exclusion CSV, separate
paper-rotation CSV, initial model portfolio CSV, Quant500 comparison CSV, readable
Markdown, summary JSON and detailed factor/source audit JSON. The audit is not
committed because it contains large provider responses/derived local data.

No real portfolio was provided. Main Action assumes an initially empty portfolio:
BUY at rank <=20, otherwise WATCH. Paper rotation separately treats previous
Top20 as hypothetical holdings only when at least 20 prior names are scoreable,
giving KEEP through rank 35 and SELL above 35
or when unscored. Neither list is an executed position record. Rank Change is
previous rank minus current rank, unavailable without both ranks.

Breadth includes all dated members, including Financials/Utilities and names
excluded from stock selection. One member without the full matching 200-session
window makes breadth and the combined regime unavailable. No equity/cash
allocation is published from that unavailable decision or when fewer than 20
current names are scoreable. A 75% exposure example
is illustrative only: 20 equal weights would be 3.75% each and 25% cash.

Quant500's supplied list is an external reference, not a calibration target.
For scored reference names, weighted component deficits against our Top20 mean
describe our ranking. Without Quant500 component values they cannot establish
the cause of its ranking. Without our ranking the overlap is unavailable, not
zero. Parameters are never changed to improve agreement.


## Coverage findings for the first run

All 508 market series and 393 non-excluded issuers' submissions/companyfacts
were downloaded, plus four relevant archived submissions pages, without network
errors. Exact mapped accounting facts remain incomplete for most issuers.
This is a source-coverage limitation, not a valid full S&P 500 Top20 result.
Partial-cohort percentiles must not be interpreted as whole-universe percentiles.
Ranking CSV rows expose this in the Rank Scope column. If fewer than 20 names
are scoreable, Top20 overlap, model allocations and prior-Top20 paper holdings
remain unavailable rather than being silently reduced to a smaller portfolio.
A complete report requires verified missing-tag/filing mappings or a reconciled
point-in-time fundamental provider. Restricted cash, nonproduction-only D&A,
lease-inclusive balances with a different scope and weighted-average shares
are not silently substituted to increase the number of ranked names.
