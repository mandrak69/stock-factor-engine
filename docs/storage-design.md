# Local storage v0.1

## Scope and layout

Use SQLite for normalized data and immutable JSON files for source evidence.
No database server is required. Initialize from the project root:

```bash
python -m stock_factor_engine.storage --database data/engine.sqlite
```

```text
data/
  engine.sqlite
  raw/sec/<cik>/<endpoint>/<run-id>-<sha256>.json
```

`data/` is excluded from Git. Back up the database and raw directory together;
use SQLite's backup API rather than copying a database during writes.
Raw document paths are relative to the data directory. Ingestion must validate
that paths remain inside it, write payloads atomically before committing their
database references, and verify SHA-256 when replaying. An interrupted import
can leave an unreferenced raw file, but must never commit a missing-file reference.
These importer behaviors are implemented in the SEC ingestion slice; see
[`sec-ingestion.md`](sec-ingestion.md).

## Tables and relationships

| Table | Identity / responsibility |
| --- | --- |
| companies | Stable internal ID; unique optional 10-digit SEC CIK |
| securities | Instrument ID, company, exchange, currency, active dates |
| ticker_assignments | Security alias with inclusive validity dates |
| ingestion_runs | Source, parser version, start/end timestamps, status, error |
| raw_documents | Retrieval observation, source URL, hash, file path, run |
| filings | Unique SEC accession, company, form, dates, availability, raw evidence |
| financial_facts | Immutable filing-backed value, period, unit, XBRL origin, evidence |
| schema_migrations | Applied migration versions and application times |

Each fact's company must match its filing. Filing and fact evidence may reference
different documents: submissions provides filing metadata; companyfacts provides
the reported values. Companies and security reference data are not yet a complete
historical universe store. Current sector or ticker data must not be treated as
historical evidence by a future backtest; temporal classifications and universe
membership require a later migration.

## Time and value contract

- Fiscal and filing dates: ISO `YYYY-MM-DD`.
- All persisted instants: UTC `YYYY-MM-DDTHH:MM:SS.ffffffZ`, fixed precision.
  The importer must parse timezone-aware values and normalize before insert.
  SQLite TEXT ordering requires this common representation; arbitrary offset
  strings must not be inserted. Database checks alone do not validate timestamps.
- `retrieved_at` records when we downloaded the response, not when the market
  could know the filing. It is never the historical cutoff field.
- `available_at` records justified public availability and is never before
  filing acceptance. Unknown acceptance/publication times are quarantined until
  resolved; do not invent midnight from a date-only `filed` field.
- Financial values use `value_decimal` TEXT converted with `Decimal`, never
  SQLite REAL. Import must reject NaN/infinity. Financial arithmetic belongs
  in Python until a precision-safe database backend is introduced.
- Preserve original taxonomy, XBRL concept, unit and original JSON. `concept`
  stores the canonical mapping. Parser version is tracked through ingestion runs.

Historical snapshots downloaded today cannot by themselves prove that all
contents existed unchanged on an earlier date. The SEC importer must associate
each observation with its originating accession, retain restatements, and
document the limitations of aggregate companyfacts snapshots.

## Versioning, duplicates, and queries

Filings, facts and raw document metadata reject UPDATE and DELETE. Corrections
from later filings append new versions. Reimporting a fact with the same filing,
canonical concept, unit, period, availability and XBRL origin matches a unique
key, including instant facts with a NULL start date. The importer must compare
existing values: identical duplicates are skipped; conflicts fail explicitly.
Do not use INSERT OR REPLACE or silently ignore conflicting amounts.

Point-in-time fact identity is company + concept + unit + start/end period.
Retrieve rows with `available_at <= as_of` and feed decoded `FinancialFact`
objects into the existing `facts_as_of` selector. Keep all eligible versions;
equal-time conflicting versions must raise, not be hidden by SQL LIMIT 1.
The persistent decoder is `storage.financials.financial_facts_as_of`.

Ticker intervals are inclusive, matching existing models. The identity importer
must reject overlapping assignments for the same security; the current schema
only enforces exact duplicate and invalid-range checks.

## Migrations

Opening via `connect_database` enables foreign keys and applies pending versions
inside a single transaction. Applied migrations are immutable. Append migrations
for schema changes; unknown/non-contiguous histories fail closed. Reopening an
up-to-date database is safe and preserves stored data. Connections returned by
this function belong to the caller and must be closed explicitly.

The storage release introduces persistence schema and initialization. Prices,
derived metrics, strategy versions and backtest results need later migrations.
