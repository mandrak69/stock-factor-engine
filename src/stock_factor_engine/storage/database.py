from __future__ import annotations

import sqlite3
from pathlib import Path


# Migrations are immutable once released. Append a new version for changes.
MIGRATIONS = ((1, (
    """CREATE TABLE companies (
        id TEXT PRIMARY KEY, legal_name TEXT NOT NULL,
        cik TEXT UNIQUE CHECK(cik IS NULL OR
            (length(cik) = 10 AND cik NOT GLOB '*[^0-9]*')),
        sector TEXT, industry TEXT)""",
    """CREATE TABLE securities (
        id TEXT PRIMARY KEY, company_id TEXT NOT NULL REFERENCES companies(id),
        exchange TEXT NOT NULL, currency TEXT NOT NULL,
        security_type TEXT NOT NULL, active_from TEXT, active_to TEXT,
        CHECK(active_to IS NULL OR active_from IS NULL OR active_to >= active_from))""",
    """CREATE TABLE ticker_assignments (
        id INTEGER PRIMARY KEY, security_id TEXT NOT NULL REFERENCES securities(id),
        symbol TEXT NOT NULL, valid_from TEXT NOT NULL, valid_to TEXT,
        UNIQUE(security_id, symbol, valid_from),
        CHECK(valid_to IS NULL OR valid_to >= valid_from))""",
    """CREATE TABLE ingestion_runs (
        id TEXT PRIMARY KEY, source TEXT NOT NULL, parser_version TEXT NOT NULL,
        started_at TEXT NOT NULL, finished_at TEXT,
        status TEXT NOT NULL CHECK(status IN ('running', 'succeeded', 'failed')),
        error TEXT)""",
    """CREATE TABLE raw_documents (
        id TEXT PRIMARY KEY, ingestion_run_id TEXT NOT NULL REFERENCES ingestion_runs(id),
        source TEXT NOT NULL, source_url TEXT NOT NULL, retrieved_at TEXT NOT NULL,
        relative_path TEXT NOT NULL UNIQUE, sha256 TEXT NOT NULL CHECK(length(sha256) = 64),
        media_type TEXT NOT NULL DEFAULT 'application/json')""",
    """CREATE TABLE filings (
        accession_number TEXT PRIMARY KEY, company_id TEXT NOT NULL REFERENCES companies(id),
        form_type TEXT NOT NULL, period_end TEXT NOT NULL, filed_date TEXT NOT NULL,
        accepted_at TEXT NOT NULL, available_at TEXT NOT NULL, source TEXT NOT NULL,
        amendment_of TEXT REFERENCES filings(accession_number),
        raw_document_id TEXT NOT NULL REFERENCES raw_documents(id),
        UNIQUE(accession_number, company_id),
        CHECK(filed_date >= period_end), CHECK(available_at >= accepted_at))""",
    """CREATE TABLE financial_facts (
        id INTEGER PRIMARY KEY, company_id TEXT NOT NULL REFERENCES companies(id),
        filing_accession_number TEXT NOT NULL, concept TEXT NOT NULL,
        value_decimal TEXT NOT NULL, unit TEXT NOT NULL,
        period_start TEXT, period_end TEXT NOT NULL, available_at TEXT NOT NULL,
        source_taxonomy TEXT NOT NULL, source_concept TEXT NOT NULL,
        raw_document_id TEXT NOT NULL REFERENCES raw_documents(id),
        FOREIGN KEY(filing_accession_number, company_id)
            REFERENCES filings(accession_number, company_id),
        CHECK(period_start IS NULL OR period_end >= period_start))""",
    # SQLite NULL values are distinct in UNIQUE constraints. COALESCE handles instant facts.
    """CREATE UNIQUE INDEX fact_version_unique ON financial_facts (
        company_id, filing_accession_number, concept, unit,
        COALESCE(period_start, ''), period_end, available_at,
        source_taxonomy, source_concept)""",
    """CREATE INDEX fact_as_of ON financial_facts
        (company_id, concept, unit, available_at, period_end)""",
    """CREATE TRIGGER fact_availability_guard BEFORE INSERT ON financial_facts
        WHEN NEW.available_at < (SELECT available_at FROM filings
            WHERE accession_number = NEW.filing_accession_number)
        BEGIN SELECT RAISE(ABORT, 'fact cannot precede filing availability'); END""",
    *tuple(
        f"""CREATE TRIGGER {table}_no_{action.lower()} BEFORE {action} ON {table}
        BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END"""
        for table in ('filings', 'financial_facts', 'raw_documents')
        for action in ('UPDATE', 'DELETE')
    ),
)), (2, (
    """CREATE TABLE market_snapshots (
        id TEXT PRIMARY KEY, security_id TEXT NOT NULL REFERENCES securities(id),
        raw_document_id TEXT NOT NULL REFERENCES raw_documents(id),
        source TEXT NOT NULL, retrieved_at TEXT NOT NULL, price_basis TEXT NOT NULL)""",
    """CREATE TABLE daily_prices (
        id INTEGER PRIMARY KEY, security_id TEXT NOT NULL REFERENCES securities(id),
        source TEXT NOT NULL, trading_date TEXT NOT NULL, observation_hash TEXT NOT NULL,
        open_decimal TEXT NOT NULL, high_decimal TEXT NOT NULL, low_decimal TEXT NOT NULL,
        close_decimal TEXT NOT NULL, adjusted_close_decimal TEXT NOT NULL,
        volume INTEGER NOT NULL CHECK(volume >= 0),
        raw_document_id TEXT NOT NULL REFERENCES raw_documents(id),
        UNIQUE(security_id, source, trading_date, observation_hash))""",
    """CREATE TABLE corporate_actions (
        id INTEGER PRIMARY KEY, security_id TEXT NOT NULL REFERENCES securities(id),
        source TEXT NOT NULL, event_date TEXT NOT NULL,
        kind TEXT NOT NULL CHECK(kind IN ('dividend', 'split')),
        value_decimal TEXT NOT NULL, observation_hash TEXT NOT NULL,
        raw_document_id TEXT NOT NULL REFERENCES raw_documents(id),
        UNIQUE(security_id, source, event_date, kind, observation_hash))""",
    """CREATE TABLE snapshot_prices (
        snapshot_id TEXT NOT NULL REFERENCES market_snapshots(id),
        price_id INTEGER NOT NULL REFERENCES daily_prices(id),
        PRIMARY KEY(snapshot_id, price_id))""",
    """CREATE TABLE snapshot_actions (
        snapshot_id TEXT NOT NULL REFERENCES market_snapshots(id),
        action_id INTEGER NOT NULL REFERENCES corporate_actions(id),
        PRIMARY KEY(snapshot_id, action_id))""",
    *tuple(
        f"""CREATE TRIGGER {table}_no_{action.lower()} BEFORE {action} ON {table}
        BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END"""
        for table in ('market_snapshots', 'daily_prices', 'corporate_actions', 'snapshot_prices', 'snapshot_actions')
        for action in ('UPDATE', 'DELETE')
    ),
)))


def migrate(connection: sqlite3.Connection) -> None:
    """Apply pending migrations atomically; reject databases from a newer release."""
    if connection.in_transaction:
        raise ValueError('migrate requires a connection without an active transaction')
    connection.execute('BEGIN IMMEDIATE')
    try:
        connection.execute('''CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)''')
        versions = [row[0] for row in connection.execute(
            'SELECT version FROM schema_migrations ORDER BY version')]
        expected = [version for version, _ in MIGRATIONS]
        if versions != expected[:len(versions)]:
            raise ValueError('Unknown or non-contiguous database schema versions')
        for version, statements in MIGRATIONS[len(versions):]:
            for statement in statements:
                connection.execute(statement)
            connection.execute(
                "INSERT INTO schema_migrations VALUES (?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))",
                (version,),
            )
        connection.commit()
    except BaseException:
        connection.rollback()
        raise


def connect_database(path: str | Path) -> sqlite3.Connection:
    """Open a local database, enforce foreign keys, and apply migrations."""
    if str(path) != ':memory:':
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA foreign_keys = ON')
    try:
        migrate(connection)
    except BaseException:
        connection.close()
        raise
    return connection
