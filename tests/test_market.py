import copy
from datetime import UTC, datetime
from decimal import Decimal
import json
import sqlite3

import pytest

from stock_factor_engine.models.market import total_return
from stock_factor_engine.providers.market.ingestion import ingest_market, replay_response
from stock_factor_engine.providers.market.yahoo import parse
from stock_factor_engine.storage import connect_database
from stock_factor_engine.storage.market import market_report
from stock_factor_engine.storage import database


RETRIEVED = datetime(2024, 3, 13, 18, tzinfo=UTC)


def payload():
    # First OHLC already reflects a 2:1 split, and adjusted close reflects the dividend.
    epochs = [1709908200, 1710163800, 1710250200, 1710336600]
    return {'chart': {'error': None, 'result': [{
        'meta': {'symbol': 'MSFT', 'currency': 'USD', 'instrumentType': 'EQUITY',
                 'exchangeTimezoneName': 'America/New_York'},
        'timestamp': epochs,
        'indicators': {'quote': [{'open': [50, 50, 49, 50], 'high': [51, 51, 50, 51],
                                  'low': [49, 49, 48, 49], 'close': [50, 50, 49, 50],
                                  'volume': [1000, 2000, 1500, 100]}],
                       'adjclose': [{'adjclose': [49, 49, 49, 50]}]},
        'events': {'splits': {'split': {'date': epochs[1], 'numerator': 2, 'denominator': 1}},
                   'dividends': {'div': {'date': epochs[2], 'amount': 1}}},
    }]}}


def response(value=None):
    return json.dumps(value or payload()).encode(), RETRIEVED, 'https://query1.finance.yahoo.com/v8/finance/chart/MSFT'


@pytest.fixture
def store(tmp_path):
    connection = connect_database(tmp_path / 'engine.sqlite')
    connection.execute("INSERT INTO companies VALUES ('sec:0000789019','Microsoft','0000789019',NULL,NULL)")
    connection.commit()
    yield connection, tmp_path
    connection.close()


def test_parse_dates_partial_session_and_no_double_adjustment():
    bars, actions, rejected, _ = parse(response()[0], 'MSFT', RETRIEVED)
    assert [str(bar.trading_date) for bar in bars] == ['2024-03-08', '2024-03-11', '2024-03-12']
    assert len(actions) == 2
    assert rejected == []
    assert actions[0].value == 2
    # Applying the split to an already split-adjusted series would incorrectly double wealth.
    assert total_return(bars[0], bars[1]) == 0
    # Adding the cash dividend again to adjusted close would double-count it.
    assert total_return(bars[1], bars[2]) == 0


def test_import_repeat_and_replay_preserve_one_observation(store):
    connection, root = store
    first = ingest_market(connection, root, response=response())
    assert (first['new_bars'], first['new_actions'], first['quarantined']) == (3, 2, 0)
    replay = replay_response(connection, root, first['snapshot_id'])
    second = ingest_market(connection, root, response=replay)
    assert (second['new_bars'], second['new_actions']) == (0, 0)
    assert connection.execute('SELECT COUNT(*) FROM snapshot_prices').fetchone()[0] == 6
    report = market_report(connection, snapshot_id=first['snapshot_id'], as_of=RETRIEVED)
    assert report['splits'] == report['dividends'] == 1
    assert report['last_session_adjusted_return'] == '0'


def test_corrected_adjustment_is_new_vintage_not_overwrite(store):
    connection, root = store
    first = ingest_market(connection, root, response=response())
    changed = payload()
    changed['chart']['result'][0]['indicators']['adjclose'][0]['adjclose'][2] = 50
    second = ingest_market(connection, root, response=response(changed))
    assert second['new_bars'] == 1
    old = market_report(connection, snapshot_id=first['snapshot_id'], as_of=RETRIEVED)
    new = market_report(connection, snapshot_id=second['snapshot_id'], as_of=RETRIEVED)
    assert old['last_adjusted_close'] == '49'
    assert new['last_adjusted_close'] == '50'


def test_bad_columns_record_failed_run_and_evidence(store):
    connection, root = store
    bad = payload()
    bad['chart']['result'][0]['indicators']['quote'][0]['volume'].pop()
    with pytest.raises(ValueError, match='different lengths'):
        ingest_market(connection, root, response=response(bad))
    assert connection.execute('SELECT COUNT(*) FROM daily_prices').fetchone()[0] == 0
    assert connection.execute("SELECT COUNT(*) FROM ingestion_runs WHERE status='failed'").fetchone()[0] == 1
    assert connection.execute('SELECT COUNT(*) FROM raw_documents').fetchone()[0] == 1


def test_invalid_bar_is_quarantined_and_action_without_bar_fails():
    bad = payload()
    bad['chart']['result'][0]['indicators']['quote'][0]['volume'][0] = -1
    bars, _, rejected, _ = parse(response(bad)[0], 'MSFT', RETRIEVED)
    assert len(bars) == 2 and len(rejected) == 1
    bad['chart']['result'][0]['indicators']['quote'][0]['close'][1] = None
    with pytest.raises(ValueError, match='no valid bar'):
        parse(response(bad)[0], 'MSFT', RETRIEVED)


def test_cutoff_is_next_local_midnight_and_vintage_is_explicit(store):
    connection, root = store
    first = ingest_market(connection, root, response=response())
    report = market_report(connection, snapshot_id=first['snapshot_id'],
                           as_of=datetime(2024, 3, 12, 20, tzinfo=UTC))
    assert report['last_date'] == '2024-03-11'
    assert report['snapshot_known_at_as_of'] is False
    with pytest.raises(ValueError, match='timezone-aware'):
        market_report(connection, snapshot_id=first['snapshot_id'], as_of=datetime(2024, 3, 12))


def test_raw_hash_detects_corruption(store):
    connection, root = store
    first = ingest_market(connection, root, response=response())
    row = connection.execute('SELECT relative_path FROM raw_documents').fetchone()
    (root / row[0]).write_bytes(b'corruption')
    with pytest.raises(ValueError, match='hash mismatch'):
        replay_response(connection, root, first['snapshot_id'])


def test_market_rows_are_append_only(store):
    connection, root = store
    ingest_market(connection, root, response=response())
    with pytest.raises(sqlite3.IntegrityError, match='append-only'):
        connection.execute("UPDATE daily_prices SET close_decimal='99'")


def test_upgrade_from_v1_keeps_financial_data(tmp_path, monkeypatch):
    migrations = database.MIGRATIONS
    monkeypatch.setattr(database, 'MIGRATIONS', migrations[:1])
    path = tmp_path / 'engine.sqlite'
    connection = connect_database(path)
    connection.execute("INSERT INTO companies VALUES ('c','Company',NULL,NULL,NULL)")
    connection.commit()
    connection.close()
    monkeypatch.setattr(database, 'MIGRATIONS', migrations)
    connection = connect_database(path)
    try:
        assert connection.execute('SELECT id FROM companies').fetchone()[0] == 'c'
        assert connection.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0] == 2
        assert connection.execute('SELECT COUNT(*) FROM daily_prices').fetchone()[0] == 0
    finally:
        connection.close()
