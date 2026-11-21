# Analytical AI boundary accounts v0.1

Cutoff: 2026-11-20 21:30 UTC. Map: 32 issuer/group references; Wiwynn is folded
into its controlling parent Wistron, leaving 31 candidate accounting units.
controls.json pins the primary Note 7(a) evidence. Full legal/control review is
still required; no assumption of complete independent group coverage is made.
Structural projects/pools are not extra issuers. This is an
analytical aggregation of independent companies, not statutory consolidation
or a finding of incorrect revenue recognition.

Run from the repository root:

```powershell
python research/ai-ecosystem/acquire_financials.py
python -m stock_factor_engine.ecosystem.accounts_report
python -m pytest
```

Acquisition reuses screening SEC archives and downloads missing feeds. The
already-authorized SEC_USER_AGENT from .env goes only to SEC, with cross-domain
redirects blocked. Corporate requests use a generic identifier. Evidence stays
under ignored data/ directories. Changed corporate pages cannot replace pinned
historical evidence: they are saved as unreviewed and need re-review or the
archived original. Companyfacts is retrospective; acceptance checks do not
establish complete contemporaneous data-vintage coverage.

## Outputs

data/reports/ai-financials-2026-11-20 contains:

- financial-report.md: methodology, issuer tables and qualifications.
- parent-financials.csv: all 32 companies, exact TTM dates, USD figures and gaps.
- supplemental-statements.csv: newer NVIDIA release and foreign/6-K statements
  in their actual quarter/YTD periods and original currencies; never summed with
  the TTM rows. PP&E plus intangibles is distinct from PP&E-only.
  PDF figures are manually reviewed by page/column and protected by original
  file hash; they are not automatically parsed. Wistron's short primary-source
  web excerpt is explicitly labeled, not presented as an original HTML archive.
- financing-disclosures.csv and purchase-obligations.csv: different future
  minima, caps, intentions, reported investments and credit facilities; no total.
- cash-eliminations.csv and sales-eliminations.csv: actual transaction inputs;
  header-only until documented bilateral observations are supplied.
- data-gaps.csv: issuer-level limitations.
- metric-evidence.csv, financial-audit.json, summary.json and manifest.json:
  TTM components, accession, availability and input/code/output hashes.

Selected generated outputs are versioned in reports/2026-11-20 for review.
Detailed audits/raw captures remain local. Regeneration after commit updates
the local manifest's commit reference. CompoundRank/Market Regime are unchanged.

## Inputs and calculations

Existing SEC availability and TTM functions supply parent context. Ambiguity
fails closed per metric; absent debt is not zero. Latest standardized 10-Qs may
lag an earnings release, as explicitly flagged for NVIDIA. reviewed-statements.json
pins manually inspected Anthropic/Nscale S-1 tables, units, amounts and
annual-minus-prior-YTD-plus-current-YTD bridges, with hash/amount checks. The
stock screening parser is not weakened to admit unsupported filings.

accounts.json targets January–September 2026. Empty cash/sales arrays mean
unavailable, not zero. Each observation requires economic_id, canonical
payer/payee, nonnegative amount_usd, USD currency, source_urls, available_at,
period_start/end and basis. Cash basis must be settled_cash; sales basis must
be recognized_revenue. Cash categories: operating, capex, financing,
distribution, investing_other. Unknown counterparties remain unresolved;
confirmed outsiders must be declared in external_counterparties. Explicit
evidenced FX conversion is required before a non-USD observation is entered.

Internal transactions eliminate once; boundary-crossing cash keeps direction.
Complete totals require one evidenced period-matched coverage attestation per
nonoverlapping accounting unit per ledger, a complete perimeter_review, and
opening cash + external net cash + FX = closing cash. Subsidiary statements
already included by a parent must not be added again; their already-eliminated
internal purchases must not be deducted a second time.
Attestations represent reviewed reconciliations, not automatic inferences from
having public financial statements. CFO/capex ratios additionally require an
evidenced category_review: internally manufactured equipment requires cost
capitalization and cash-category reclassification, not just deleting capex.

External revenue/net cash are withheld until complete. Self-funding coverage =
external operating cash / gross external infrastructure capex. Financing gap =
gross external infrastructure capex minus external operating cash. Acquisitions,
financing, distributions and asset sales remain separate. Profit requires
internal asset margins, depreciation, costs, tax and equity-method eliminations.
The straight-line asset helper uses supplied assumptions; it does not infer
unreported issuer costs. Runway needs unrestricted cash and a supported forward
monthly schedule, so remains unavailable.

## Evidence limits

Parent financials include non-AI businesses and intra-network sales. Customer
advances can support CFO while creating future service obligations; Nscale and
Nebius working-capital movements are shown explicitly. The archived Anthropic
document contains an unresolved USD50m difference between cash-statement closing
cash and balance-sheet cash plus restricted cash; no clean liquidity inference
is made from it.

Neither global 95% coverage nor a fraud score is inferred. Exact external AI
demand requires bilateral settlements, recognition timing, receivables/payables,
legal/control perimeter, principal/agent treatment and AI allocations that the
public aggregate statements do not fully disclose.

NVIDIA latest revenue TTM is separately verified as USD361.808bn through
2026-10-25: FY2026 USD215.938bn minus prior 9M USD147.811bn plus current
9M USD293.681bn. Both source hashes, amount anchors, USD units, availability
and contiguous periods are checked. This supplemental TTM must not be mixed
with July-ended TTM CFO/capex or treated as external group revenue.
