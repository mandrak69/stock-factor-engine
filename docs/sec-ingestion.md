# SEC ingestion v0.1

## Run locally

Install the project with `python -m pip install -e '.[dev]'`, then in PowerShell:

```powershell
$env:SEC_USER_AGENT = 'stock-factor-engine/0.1 your-contact@example.com'
python -m stock_factor_engine.providers.sec --cik 0000789019 --data-dir data
```

Replace the example with your actual contact address. The importer does not read
`.env` automatically; this variable applies to the current shell. No SEC API key
is required. The output reports new filings/facts, rejected observations and the
quarantine report path. Microsoft is the default CIK. Connections are closed when
the command finishes. A failed command records an ingestion run with its error.

The client requests JSON from `data.sec.gov`, uses an identifying User-Agent,
spaces requests by at least 0.5 seconds, and retries transient 429/5xx/network
errors at most three times. It stops on 403. Run one importer at a time; the
request limit is per client, not a cross-process rate limiter.

## Evidence and parsing

The importer fetches current submissions, every historical page referenced in
`filings.files`, and companyfacts. Historical filenames must match the requested
CIK. Both primary payloads must agree with that company identity. Original bytes
are saved atomically under `data/raw/sec/<cik>/` before normalized insertion,
with SHA-256, source URL and retrieval timestamp recorded in SQLite. A crash
before evidence metadata is committed can leave an orphan file.

This slice supports 10-K, 10-Q and their amendments, and an explicit subset of
US-GAAP USD concepts: revenue, operating income, net income, operating cash flow,
capital expenditure, cash, assets and equity. Unmapped concepts and other forms
remain in raw evidence but are not normalized. Revenue aliases remain distinct
observations; ambiguous conflicting aliases cause historical queries to fail
closed. No automatic debt totals or accounting-derived metrics are produced.

Financial facts are joined by accession, never by reporting date alone. Fact
form and filing date must match submissions. Instant and duration shapes are
validated. Missing/naive acceptance timestamps and unmatched fact accessions are
quarantined. The quarantine report retains rejected observations and reasons.
Amendment lineage is not inferred; each amendment retains its own accession.

## Availability policy and limitations

For parser `sec-v0.1.0`, `available_at = accepted_at + 5 minutes`. This is an
explicit research convention and does not prove exact public dissemination time.
API acceptance timestamps with explicit offsets are normalized to UTC. Date-only
filing timestamps are never converted into guessed midnight availability.
The chosen policy version is preserved through each filing's original raw run.
Changing the policy requires a planned migration/rebuild; existing filings are
immutable and mismatches fail.

Companyfacts is a present-day aggregate of filing observations. Linking an
observation to a historic accession reduces future leakage but does not prove
that the aggregate included it unchanged on that date. This foundation is not
yet a validated historical backtest dataset. Archived original filing/XBRL
verification and historical universe membership remain future work.

Normalized rows commit together. Identical repeat imports add retrieval evidence
without duplicating filings/facts. Different values for the same version raise
and roll back all normalized inserts from that run. At least one valid mapped
fact is required for success; a successful run may still have quarantined rows.

## Replay and historical query

Replay a prior run without network access:

```powershell
python -m stock_factor_engine.providers.sec --cik 0000789019 --data-dir data --replay-run <run_id>
```

Every response is hash-checked and paths must remain inside the data directory.
Replay records a new run while retaining original retrieval times.

```python
from datetime import UTC, datetime
from stock_factor_engine.storage import connect_database
from stock_factor_engine.storage.financials import financial_facts_as_of

db = connect_database('data/engine.sqlite')
try:
    facts = financial_facts_as_of(
        db, company_id='sec:0000789019',
        as_of=datetime(2020, 5, 20, tzinfo=UTC),
    )
finally:
    db.close()
```

Queries reconstruct exact Decimal values and use the existing point-in-time
selector, preserving amendment history and rejecting ambiguous availability ties.

## References

- [SEC data API documentation](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
- [SEC developer guidance](https://www.sec.gov/about/developer-resources)
