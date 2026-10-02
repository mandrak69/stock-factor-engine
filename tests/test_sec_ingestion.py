import copy
import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from urllib.error import HTTPError

import pytest

from stock_factor_engine.providers.sec import client as client_module
from stock_factor_engine.providers.sec.client import SecClient, decode_json, normalize_cik
from stock_factor_engine.providers.sec.ingestion import ingest_company, parse_filings
from stock_factor_engine.storage import connect_database
from stock_factor_engine.storage.financials import financial_facts_as_of
from stock_factor_engine.providers.sec.replay import ReplayClient


CIK = '0000789019'


class FixtureClient:
    def __init__(self):
        self.submissions = {'cik': 789019, 'name': 'Microsoft', 'filings': {
            'recent': {'accessionNumber': ['new'], 'form': ['10-Q/A'],
                       'reportDate': ['2020-03-31'], 'filingDate': ['2020-06-15'],
                       'acceptanceDateTime': ['2020-06-15T12:00:00Z']},
            'files': [{'name': f'CIK{CIK}-submissions-001.json'}]}}
        self.history = {'accessionNumber': ['old'], 'form': ['10-Q'],
                        'reportDate': ['2020-03-31'], 'filingDate': ['2020-05-01'],
                        'acceptanceDateTime': ['2020-05-01T12:00:00Z']}
        self.facts = {'cik': 789019, 'facts': {'us-gaap': {
            'CashAndCashEquivalentsAtCarryingValue': {'units': {'USD': [
                {'accn': 'old', 'form': '10-Q', 'filed': '2020-05-01', 'end': '2020-03-31', 'val': 100},
                {'accn': 'new', 'form': '10-Q/A', 'filed': '2020-06-15', 'end': '2020-03-31', 'val': 97},
            ]}}}}}

    def fetch(self, path):
        if 'companyfacts' in path:
            data = self.facts
        elif 'submissions-001' in path:
            data = self.history
        else:
            data = self.submissions
        return json.dumps(data).encode(), datetime(2026, 10, 2, tzinfo=UTC)


@pytest.fixture
def store(tmp_path):
    db = connect_database(tmp_path / 'engine.sqlite')
    yield db, tmp_path
    db.close()


def test_import_evidence_duplicate_and_historical_query(store):
    db, directory = store
    client = FixtureClient()
    # SEC may repeat the same observation with different frame metadata.
    observations = client.facts['facts']['us-gaap']['CashAndCashEquivalentsAtCarryingValue']['units']['USD']
    observations.append(copy.deepcopy(observations[0]))
    result = ingest_company(db, directory, CIK, client)
    assert (result['new_filings'], result['new_facts'], result['quarantined']) == (2, 2, 0)
    rows = db.execute('SELECT * FROM raw_documents').fetchall()
    assert len(rows) == 3
    for row in rows:
        assert hashlib.sha256((directory / row['relative_path']).read_bytes()).hexdigest() == row['sha256']
    def values(cutoff):
        return [fact.value for fact in financial_facts_as_of(db, company_id='sec:' + CIK, as_of=cutoff)]
    assert values(datetime(2020, 5, 1, 12, 4, tzinfo=UTC)) == []
    assert values(datetime(2020, 5, 20, tzinfo=UTC)) == [Decimal(100)]
    assert values(datetime(2020, 7, 1, tzinfo=UTC)) == [Decimal(97)]
    second = ingest_company(db, directory, CIK, client)
    assert (second['new_filings'], second['new_facts']) == (0, 0)
    assert db.execute('SELECT COUNT(*) FROM raw_documents').fetchone()[0] == 6


def test_conflict_rolls_back_and_records_failure(store):
    db, directory = store
    client = FixtureClient()
    ingest_company(db, directory, CIK, client)
    client.facts['facts']['us-gaap']['CashAndCashEquivalentsAtCarryingValue']['units']['USD'][0]['val'] = 999
    with pytest.raises(ValueError, match='Conflicting fact'):
        ingest_company(db, directory, CIK, client)
    assert db.execute('SELECT COUNT(*) FROM financial_facts').fetchone()[0] == 2
    assert db.execute("SELECT COUNT(*) FROM ingestion_runs WHERE status='failed'").fetchone()[0] == 1
    assert db.execute('SELECT COUNT(*) FROM raw_documents').fetchone()[0] == 6


def test_missing_acceptance_is_quarantined(store):
    db, directory = store
    client = FixtureClient()
    del client.history['acceptanceDateTime']
    result = ingest_company(db, directory, CIK, client)
    assert result['new_facts'] == 1
    assert result['quarantined'] == 2
    assert 'No filing' in open(result['quarantine_file'], encoding='utf-8').read()


def test_bad_cik_and_malformed_payload_leave_no_normalized_rows(store):
    db, directory = store
    client = FixtureClient()
    client.facts['cik'] = 123
    with pytest.raises(ValueError, match='does not match'):
        ingest_company(db, directory, CIK, client)
    assert db.execute('SELECT COUNT(*) FROM filings').fetchone()[0] == 0
    assert db.execute('SELECT COUNT(*) FROM raw_documents').fetchone()[0] == 3


@pytest.mark.parametrize('mutation', ['unit', 'form', 'date', 'shape', 'number'])
def test_bad_observation_is_quarantined(store, mutation):
    db, directory = store
    client = FixtureClient()
    units = client.facts['facts']['us-gaap']['CashAndCashEquivalentsAtCarryingValue']['units']
    observation = units['USD'][0]
    if mutation == 'unit':
        units['EUR'] = [units['USD'].pop(0)]
    elif mutation == 'form':
        observation['form'] = '10-K'
    elif mutation == 'date':
        observation['filed'] = '2020-05-02'
    elif mutation == 'shape':
        observation['start'] = '2020-01-01'
    else:
        observation['val'] = 'NaN'
    result = ingest_company(db, directory, CIK, client)
    assert result['quarantined'] == 1
    assert result['new_facts'] == 1


def test_columns_and_json_precision():
    with pytest.raises(ValueError, match='different lengths'):
        parse_filings({'accessionNumber': ['a'], 'form': [], 'reportDate': [],
                       'filingDate': [], 'acceptanceDateTime': []}, 'x')
    assert decode_json(b'{"value": 123456789.0123456789}')['value'] == Decimal('123456789.0123456789')
    with pytest.raises(ValueError):
        decode_json(b'{"value": NaN}')
    for cik in ['../1', '0', '12345678901']:
        with pytest.raises(ValueError):
            normalize_cik(cik)


def test_client_retries_and_sets_identification(monkeypatch):
    calls, waits = [], []
    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self):
            return b'{"cik":789019}'
    def fetch(request, timeout):
        calls.append(request)
        if len(calls) == 1:
            raise HTTPError(request.full_url, 429, 'slow down', {'Retry-After': '2'}, None)
        return Response()
    monkeypatch.setattr(client_module, 'urlopen', fetch)
    monkeypatch.setattr(client_module.time, 'sleep', waits.append)
    client = SecClient('stock-factor-engine admin@example.test')
    assert client.fetch(f'/submissions/CIK{CIK}.json')[0] == b'{"cik":789019}'
    assert len(calls) == 2
    assert calls[0].get_header('User-agent') == client.user_agent
    assert 2 in waits
    with pytest.raises(ValueError):
        client.fetch('/submissions/../../secret')


def test_client_does_not_retry_forbidden(monkeypatch):
    calls = []
    def forbidden(request, timeout):
        calls.append(request)
        raise HTTPError(request.full_url, 403, 'forbidden', {}, None)
    monkeypatch.setattr(client_module, 'urlopen', forbidden)
    monkeypatch.setattr(client_module.time, 'sleep', lambda _: None)
    with pytest.raises(HTTPError):
        SecClient('stock-factor-engine admin@example.test').fetch(f'/submissions/CIK{CIK}.json')
    assert len(calls) == 1


def test_replay_verifies_hash_and_is_idempotent(store):
    db, directory = store
    result = ingest_company(db, directory, CIK, FixtureClient())
    replay = ReplayClient(db, directory, result['run_id'])
    again = ingest_company(db, directory, CIK, replay)
    assert again['new_facts'] == 0
    row = db.execute('SELECT relative_path FROM raw_documents WHERE ingestion_run_id=? LIMIT 1',
                     (result['run_id'],)).fetchone()
    (directory / row[0]).write_bytes(b'corrupted')
    with pytest.raises(ValueError, match='hash mismatch'):
        ingest_company(db, directory, CIK, replay)


def test_duration_fact_and_ambiguity_fail_closed(store):
    from stock_factor_engine.point_in_time.financials import AmbiguousFinancialFactError
    db, directory = store
    client = FixtureClient()
    taxonomy = client.facts['facts']['us-gaap']
    observation = {'accn': 'old', 'form': '10-Q', 'filed': '2020-05-01',
                   'start': '2020-01-01', 'end': '2020-03-31', 'val': 42}
    taxonomy['Revenues'] = {'units': {'USD': [observation]}}
    taxonomy['SalesRevenueNet'] = {'units': {'USD': [{**observation, 'val': 43}]}}
    ingest_company(db, directory, CIK, client)
    with pytest.raises(AmbiguousFinancialFactError):
        financial_facts_as_of(db, company_id='sec:' + CIK, as_of=datetime(2020, 5, 20, tzinfo=UTC))
