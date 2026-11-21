# AI ecosystem evidence registry v0.1

This is an analyst-curated seed map, not consolidated accounts, a fraud finding,
or a claim of 95% global cash-flow coverage. It covers 29 operating company/group references
plus three non-company project/contract-pool references as of 2026-11-20 21:30 UTC.
Fluidstack, Wistron and Fabrinet were added after tracing primary disclosures.

The five JSON files own participant aliases, source availability, observations,
aggregate context and coverage gaps. Dollar amounts are exact decimal strings;
unknown amounts remain null. A reported investment is not silently certified as
a cash settlement. Contract values, future minimums/caps, lease principal,
nonbinding intentions, credit capacity, shares and GW are different measures.
No grand total is produced from them. Pool assignments and amendments are not
counted as new purchases. The old USD 30bn Azure announcement is retained only
in history once its amended disclosure is available.

Each source is primary and has an availability policy. SEC acceptance + 5 minutes
is used where verified. Date-only publications use a conservative two-day lag.
Corporate webpages were reviewed retrospectively; this does not establish a
complete contemporaneous web archive. Old announcements do not prove current
executed balances. Current entity/ownership aliases are specific to this curated
snapshot; an earlier or later report needs a reviewed perimeter and provenance.

The lease pool contains partly unidentified assignees; its full USD 161.2bn is
not allocated to Broadcom. BlackRock/GIP fund-management affiliations do not
justify consolidating managed funds onto BlackRock's own balance sheet. Other
group labels need legal entity/control reconciliation before financial totals.

```powershell
python -m stock_factor_engine.ecosystem --registry research/ai-ecosystem --output data/reports/ai-ecosystem-2026-11-20
python -m pytest
```

The output contains a Markdown map, Mermaid source, active relationships CSV,
disclosure history CSV, participant/source CSVs, JSON network, summary and hash
manifest. The original CompoundRank ranking and Market Regime models are not
imported, altered or recalibrated by this module.

Next required work is a common-period cash ledger, matching original receipts,
receivables/payables and legal counterparties, followed by elimination of internal
sales, asset margins and depreciation. Whole-parent liquidity and AI-specific
external demand are separate analyses. Neither complete external revenue nor
net external cash can be inferred from contract headlines.

Active means latest included disclosure, not a verified current outstanding
balance or a complete search of all later amendments. Original source captures
are stored locally under data/ai-ecosystem-2026-11-20/evidence and excluded from
Git. All 14 registry sources were archived with SHA-256 evidence references.

Pure-financier scope update: SoftBank Group, MGX and BlackRock/GIP are outside
the active operating group and its financial/participant exports. Hardware
suppliers and operating companies with investment activity remain inside.
Confirmed payments from excluded financiers are external financing, not revenue.
Prior broad-scope records remain available in Git history.
