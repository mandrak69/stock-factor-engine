from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import json

import pytest

from stock_factor_engine.storage import connect_database
from stock_factor_engine.providers.market import ingestion as market_ingestion
from stock_factor_engine.universe.ingestion import ingest_universe
from stock_factor_engine.universe.registry import DEFAULT_SYMBOLS, IDENTITIES, selected_symbols
from stock_factor_engine.universe.report import comparison_report, markdown_table

AS_OF = datetime(2025, 10, 2, 18, tzinfo=UTC)


class CompanyClient:
    def __init__(self, fail_cik=None):
        self.calls = []
        self.fail_cik = fail_cik

    def fetch(self, path):
        cik = path.split('CIK')[1][:10]
        self.calls.append(path)
        if cik == self.fail_cik:
            raise ValueError('Fixture provider unavailable')
        accession = cik + '-annual'
        if 'companyfacts' not in path:
            payload = {'cik': int(cik), 'name': 'Fixture ' + cik, 'filings': {'files': [], 'recent': {
                'accessionNumber': [accession], 'form': ['10-K'], 'reportDate': ['2025-06-30'],
                'filingDate': ['2025-08-01'], 'acceptanceDateTime': ['2025-08-01T12:00:00Z']}}}
        else:
            concepts = {}
            for concept, unit, value in [('Revenues', 'USD', 1000), ('OperatingIncomeLoss', 'USD', 200),
                                         ('NetCashProvidedByUsedInOperatingActivities', 'USD', 120),
                                         ('PaymentsToAcquirePropertyPlantAndEquipment', 'USD', 20),
                                         ('EarningsPerShareDiluted', 'USD/shares', 2),
                                         ('CommonStockSharesOutstanding', 'shares', 100)]:
                observations = []
                for start, end, scale in [('2023-07-01', '2024-06-30', 1), ('2024-07-01', '2025-06-30', 2)]:
                    observation = {'accn': accession, 'form': '10-K', 'filed': '2025-08-01',
                                   'end': end, 'val': value * scale}
                    if concept != 'CommonStockSharesOutstanding':
                        observation['start'] = start
                    observations.append(observation)
                concepts[concept] = {'units': {unit: observations}}
            payload = {'cik': int(cik), 'facts': {'us-gaap': concepts}}
        return json.dumps(payload).encode(), AS_OF


def market_response(symbol):
    epochs = []
    day = date(2024, 1, 1)
    while day < AS_OF.date():
        if day.weekday() < 5:
            epochs.append(int(datetime(day.year, day.month, day.day, 16, tzinfo=UTC).timestamp()))
        day += timedelta(days=1)
    values = [10] * len(epochs)
    payload = {'chart': {'error': None, 'result': [{
        'meta': {'symbol': symbol, 'currency': 'USD', 'instrumentType': IDENTITIES[symbol]['instrument_type'],
                 'exchangeTimezoneName': 'America/New_York'}, 'timestamp': epochs,
        'indicators': {'quote': [{**{name: values for name in ('open', 'high', 'low', 'close')},
                                 'volume': [1000] * len(values)}], 'adjclose': [{'adjclose': values}]}}]}}
    return json.dumps(payload).encode(), AS_OF, 'https://query1.finance.yahoo.com/v8/finance/chart/' + symbol


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(market_ingestion, 'fetch', market_response)
    connection = connect_database(tmp_path / 'engine.sqlite')
    yield connection, tmp_path
    connection.close()


def test_batch_import_and_comparison_keep_distinct_issuer_and_class_identities(store):
    connection, root = store
    client = CompanyClient()
    result = ingest_universe(connection, root, DEFAULT_SYMBOLS, sec_client=client)
    assert result['status'] == 'succeeded'
    assert len(result['instruments']) == 6
    assert connection.execute('SELECT COUNT(*) FROM companies').fetchone()[0] == 6
    assert len(client.calls) == 10
    report = comparison_report(connection, symbols=DEFAULT_SYMBOLS, as_of=AS_OF)
    rows = {row['symbol']: row for row in report['companies']}
    for symbol in ('MSFT', 'AAPL', 'AMZN'):
        assert rows[symbol]['metrics']['market_cap_estimate']['value'] == '2000'
        assert rows[symbol]['metrics']['pe_diluted_annual']['value'] == '2.5'
        assert rows[symbol]['status'] == 'available'
    for symbol in ('GOOGL', 'META'):
        row = rows[symbol]
        assert row['status'] == 'partial'
        assert row['metrics']['market_cap_estimate']['value'] is None
        assert 'multiple share classes' in row['metrics']['pe_diluted_annual']['reason']
        assert row['metrics']['operating_margin']['status'] == 'available'
        assert row['metrics']['momentum_12_1']['value'] == 0
    table = markdown_table(report)
    assert '| GOOGL |' in table and 'multiple share classes' in table
    again = ingest_universe(connection, root, DEFAULT_SYMBOLS, sec_client=client)
    assert all(row['market']['result']['new_bars'] == 0 for row in again['instruments'])
    assert all(row['sec']['result']['new_facts'] == 0 for row in again['instruments'][:-1])


def test_alphabet_two_classes_share_company_but_never_share_price_snapshot(store):
    connection, root = store
    client = CompanyClient()
    result = ingest_universe(connection, root, ['GOOGL', 'GOOG'], sec_client=client, include_benchmark=False)
    assert result['status'] == 'succeeded'
    assert len(client.calls) == 2
    assert connection.execute('SELECT COUNT(*) FROM companies').fetchone()[0] == 1
    assert connection.execute('SELECT COUNT(*) FROM securities').fetchone()[0] == 2
    assert IDENTITIES['GOOGL']['security_id'] != IDENTITIES['GOOG']['security_id']
    assert result['instruments'][0]['sec']['result']['run_id'] == result['instruments'][1]['sec']['result']['run_id']


def test_one_company_failure_preserves_successes_and_continues(store):
    connection, root = store
    result = ingest_universe(connection, root, DEFAULT_SYMBOLS,
                             sec_client=CompanyClient(IDENTITIES['AAPL']['cik']))
    assert result['status'] == 'partial_failure'
    rows = {row['symbol']: row for row in result['instruments']}
    assert rows['AAPL']['sec']['status'] == rows['AAPL']['market']['status'] == 'failed'
    assert rows['META']['status'] == rows['SPY']['status'] == 'succeeded'
    report = comparison_report(connection, symbols=DEFAULT_SYMBOLS, as_of=AS_OF)
    assert report['companies'][1]['status'] == 'unavailable'
    assert report['companies'][0]['status'] == 'available'


def test_future_vintages_never_automatically_enter_report(store):
    connection, root = store
    ingest_universe(connection, root, ['MSFT'], sec_client=CompanyClient())
    report = comparison_report(connection, symbols=['MSFT'], as_of=AS_OF - timedelta(seconds=1))
    row = report['companies'][0]
    assert row['snapshot'] is None
    assert row['metrics']['momentum_12_1']['status'] == 'unavailable'
    assert row['metrics']['revenue_growth_yoy']['status'] == 'available'
    assert report['benchmark']['snapshot'] is None


def test_missing_benchmark_does_not_block_asset_factors(store):
    connection, root = store
    ingest_universe(connection, root, ['MSFT'], sec_client=CompanyClient(), include_benchmark=False)
    row = comparison_report(connection, symbols=['MSFT'], as_of=AS_OF)['companies'][0]
    assert row['metrics']['momentum_12_1']['status'] == 'available'
    assert row['metrics']['return_252_excess']['status'] == 'unavailable'


@pytest.mark.parametrize('symbols', [[], ['MSFT', 'MSFT'], ['UNKNOWN'], ['SPY']])
def test_invalid_selection_fails_before_provider_calls(store, symbols):
    connection, root = store
    with pytest.raises(ValueError):
        ingest_universe(connection, root, symbols, sec_client=CompanyClient())
    assert connection.execute('SELECT COUNT(*) FROM ingestion_runs').fetchone()[0] == 0


def test_market_only_requires_existing_company_and_reports_failure(store):
    connection, root = store
    result = ingest_universe(connection, root, ['AAPL'], market_only=True, include_benchmark=False)
    assert result['status'] == 'partial_failure'
    assert 'Import AAPL SEC' in result['instruments'][0]['market']['error']


def test_cli_json_table_and_explicit_multi_class_valuation(store, monkeypatch, capsys):
    import sys
    from stock_factor_engine.universe.__main__ import main
    from stock_factor_engine.fundamentals.__main__ import main as valuation_main
    connection, root = store
    ingest_universe(connection, root, ['GOOGL', 'GOOG'], sec_client=CompanyClient())
    args = ['universe', 'report', '--database', str(root / 'engine.sqlite'), '--symbols', 'GOOGL',
            '--as-of', AS_OF.isoformat()]
    monkeypatch.setattr(sys, 'argv', args + ['--format', 'json'])
    main()
    assert json.loads(capsys.readouterr().out)['companies'][0]['symbol'] == 'GOOGL'
    output = root / 'comparison.md'
    monkeypatch.setattr(sys, 'argv', args + ['--output', str(output)])
    main()
    assert '| GOOGL |' in output.read_text(encoding='utf-8')
    monkeypatch.setattr(sys, 'argv', ['fundamentals', '--database', str(root / 'engine.sqlite'),
                                     '--valuation', '--symbol', 'GOOG', '--as-of', AS_OF.isoformat()])
    valuation_main()
    report = json.loads(capsys.readouterr().out)
    assert report['snapshot']['security_id'] == IDENTITIES['GOOG']['security_id']
    assert report['metrics']['market_cap_estimate']['value'] is None
