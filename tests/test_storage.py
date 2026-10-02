import sqlite3

import pytest

from stock_factor_engine.storage import connect_database, migrate
from stock_factor_engine.storage import database


@pytest.fixture
def db():
    connection = connect_database(':memory:')
    connection.execute("INSERT INTO companies VALUES ('msft', 'Microsoft', '0000789019', NULL, NULL)")
    connection.execute("INSERT INTO companies VALUES ('other', 'Other', NULL, NULL, NULL)")
    connection.execute("INSERT INTO ingestion_runs VALUES ('run', 'sec', '1', '2020-05-01T00:00:00.000000Z', NULL, 'running', NULL)")
    connection.execute("INSERT INTO raw_documents VALUES ('raw', 'run', 'sec', 'https://example.test', '2026-10-02T00:00:00.000000Z', 'raw/sec/a.json', ?, 'application/json')", ('a' * 64,))
    for accession, available in [('original', '2020-05-01'), ('amended', '2020-06-15')]:
        instant = available + 'T12:00:00.000000Z'
        connection.execute('INSERT INTO filings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                           (accession, 'msft', '10-Q', '2020-03-31', available,
                            instant, instant, 'sec', None, 'raw'))
    connection.commit()
    yield connection
    connection.close()


def insert_fact(db, accession='original', available='2020-05-01T12:00:00.000000Z', company='msft', value='10000000000.01'):
    db.execute('''INSERT INTO financial_facts
        (company_id, filing_accession_number, concept, value_decimal, unit,
         period_start, period_end, available_at, source_taxonomy, source_concept, raw_document_id)
        VALUES (?, ?, 'cash', ?, 'USD', NULL, '2020-03-31', ?, 'us-gaap', 'Cash', 'raw')''',
        (company, accession, value, available))


def test_reopen_preserves_data_and_version(tmp_path):
    path = tmp_path / 'nested' / 'engine.sqlite'
    db = connect_database(path)
    db.execute("INSERT INTO companies VALUES ('x', 'X', NULL, NULL, NULL)")
    db.commit()
    db.close()
    db = connect_database(path)
    try:
        assert db.execute('SELECT COUNT(*) FROM companies').fetchone()[0] == 1
        assert db.execute('SELECT COUNT(*) FROM schema_migrations').fetchone()[0] == len(database.MIGRATIONS)
        assert db.execute('PRAGMA foreign_keys').fetchone()[0] == 1
    finally:
        db.close()


def test_versions_and_exact_decimal_are_preserved(db):
    insert_fact(db)
    insert_fact(db, 'amended', '2020-06-15T12:00:00.000000Z', value='9700000000.01')
    rows = db.execute('SELECT value_decimal FROM financial_facts WHERE available_at <= ?',
                      ('2020-05-20T00:00:00.000000Z',)).fetchall()
    assert [row[0] for row in rows] == ['10000000000.01']
    assert db.execute('SELECT COUNT(*) FROM financial_facts').fetchone()[0] == 2


def test_instant_duplicate_is_rejected(db):
    insert_fact(db)
    with pytest.raises(sqlite3.IntegrityError):
        insert_fact(db)


@pytest.mark.parametrize('company,available', [
    ('other', '2020-05-01T12:00:00.000000Z'),
    ('msft', '2020-04-01T12:00:00.000000Z'),
])
def test_invalid_filing_link_or_availability_is_rejected(db, company, available):
    with pytest.raises(sqlite3.IntegrityError):
        insert_fact(db, company=company, available=available)


@pytest.mark.parametrize('table', ['filings', 'financial_facts', 'raw_documents'])
@pytest.mark.parametrize('action', ['UPDATE', 'DELETE'])
def test_evidence_is_append_only(db, table, action):
    insert_fact(db)
    statement = f'DELETE FROM {table}' if action == 'DELETE' else f'UPDATE {table} SET available_at = available_at'
    if action == 'UPDATE' and table == 'raw_documents':
        statement = 'UPDATE raw_documents SET source = source'
    with pytest.raises(sqlite3.IntegrityError, match='append-only'):
        db.execute(statement)


def test_failed_migration_rolls_back(tmp_path, monkeypatch):
    db = connect_database(tmp_path / 'engine.sqlite')
    original_version = database.MIGRATIONS[-1][0]
    monkeypatch.setattr(database, 'MIGRATIONS', database.MIGRATIONS + ((original_version + 1, (
        'CREATE TABLE temporary_table (id INTEGER)', 'INVALID SQL',
    )),))
    with pytest.raises(sqlite3.OperationalError):
        migrate(db)
    assert db.execute("SELECT name FROM sqlite_master WHERE name = 'temporary_table'").fetchone() is None
    assert db.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0] == original_version
    db.close()


def test_unknown_schema_is_rejected(db):
    db.execute("INSERT INTO schema_migrations VALUES (99, 'future')")
    db.commit()
    with pytest.raises(ValueError, match='schema versions'):
        migrate(db)
