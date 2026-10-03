from dataclasses import asdict
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from stock_factor_engine.storage.time import timestamp
from .yahoo import PRICE_BASIS, SOURCE, fetch, parse
from .identities import IDENTITIES


def digest(value):
    return hashlib.sha256(json.dumps(value, default=str, sort_keys=True).encode()).hexdigest()


def ingest_market(db, data_dir: Path, *, symbol='MSFT', response=None):
    """Import an explicitly configured instrument; preserve immutable evidence."""
    identity = IDENTITIES.get(symbol)
    if identity is None:
        raise ValueError('Other instruments need explicit identity configuration')
    if db.in_transaction:
        raise ValueError('Ingestion requires no active transaction')
    company_id, security_id = identity['company_id'], identity['security_id']
    if identity['requires_sec'] and not db.execute('SELECT 1 FROM companies WHERE id=?', (company_id,)).fetchone():
        raise ValueError(f'Import {symbol} SEC data before prices')
    run_id, raw_id = uuid4().hex, uuid4().hex
    root = Path(data_dir).resolve()
    db.execute('INSERT INTO ingestion_runs VALUES (?, ?, ?, ?, NULL, ?, NULL)',
               (run_id, SOURCE, 'yahoo-v0.2.0', timestamp(datetime.now(UTC)), 'running'))
    db.commit()
    raw_record = None
    try:
        content, retrieved_at, url = response or fetch(symbol)
        sha = hashlib.sha256(content).hexdigest()
        relative = Path('raw') / 'market' / SOURCE / symbol / f'{run_id}-{sha}.json'
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix('.tmp')
        temporary.write_bytes(content)
        temporary.replace(target)
        raw_record = (raw_id, run_id, SOURCE, url, timestamp(retrieved_at), relative.as_posix(), sha, 'application/json')
        bars, actions, rejected, meta = parse(content, symbol, retrieved_at)
        report_path = target.with_name(f'{run_id}-quarantine.json')
        report_path.write_text(json.dumps(rejected, indent=2), encoding='utf-8')
        snapshot_id = uuid4().hex
        new_bars = new_actions = 0
        with db:
            db.execute('INSERT INTO raw_documents VALUES (?, ?, ?, ?, ?, ?, ?, ?)', raw_record)
            company = db.execute('SELECT cik FROM companies WHERE id=?', (company_id,)).fetchone()
            if company is None:
                db.execute('INSERT INTO companies (id, legal_name, cik) VALUES (?, ?, ?)',
                           (company_id, identity['legal_name'], identity['cik']))
            elif company[0] != identity['cik']:
                raise ValueError('Company identity conflict')
            existing = db.execute('SELECT company_id, currency, security_type, exchange FROM securities WHERE id=?', (security_id,)).fetchone()
            if existing is None:
                db.execute('INSERT INTO securities VALUES (?, ?, ?, ?, ?, ?, NULL)',
                           (security_id, company_id, identity['exchange'], 'USD', identity['security_type'], bars[0].trading_date.isoformat()))
                db.execute('INSERT INTO ticker_assignments (security_id, symbol, valid_from) VALUES (?, ?, ?)',
                           (security_id, symbol, bars[0].trading_date.isoformat()))
            elif tuple(existing) != (company_id, 'USD', identity['security_type'], identity['exchange']):
                raise ValueError('Security identity conflict')
            db.execute('INSERT INTO market_snapshots VALUES (?, ?, ?, ?, ?, ?)',
                       (snapshot_id, security_id, raw_id, SOURCE, timestamp(retrieved_at), PRICE_BASIS))
            for bar in bars:
                observation_hash = digest(asdict(bar))
                existing = db.execute('''SELECT id FROM daily_prices WHERE security_id=? AND source=?
                    AND trading_date=? AND observation_hash=?''',
                    (security_id, SOURCE, str(bar.trading_date), observation_hash)).fetchone()
                if existing:
                    price_id = existing[0]
                else:
                    cursor = db.execute('''INSERT INTO daily_prices
                        (security_id, source, trading_date, observation_hash, open_decimal, high_decimal,
                         low_decimal, close_decimal, adjusted_close_decimal, volume, raw_document_id)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                        (security_id, SOURCE, str(bar.trading_date), observation_hash, str(bar.open),
                         str(bar.high), str(bar.low), str(bar.close), str(bar.adjusted_close), bar.volume, raw_id))
                    price_id = cursor.lastrowid
                    new_bars += 1
                db.execute('INSERT INTO snapshot_prices VALUES (?, ?)', (snapshot_id, price_id))
            for action in actions:
                observation_hash = digest(asdict(action))
                existing = db.execute('''SELECT id FROM corporate_actions WHERE security_id=? AND source=?
                    AND event_date=? AND kind=? AND observation_hash=?''',
                    (security_id, SOURCE, str(action.event_date), action.kind, observation_hash)).fetchone()
                if existing:
                    action_id = existing[0]
                else:
                    cursor = db.execute('''INSERT INTO corporate_actions
                        (security_id, source, event_date, kind, value_decimal, observation_hash, raw_document_id)
                        VALUES (?, ?, ?, ?, ?, ?, ?)''',
                        (security_id, SOURCE, str(action.event_date), action.kind, str(action.value), observation_hash, raw_id))
                    action_id = cursor.lastrowid
                    new_actions += 1
                db.execute('INSERT INTO snapshot_actions VALUES (?, ?)', (snapshot_id, action_id))
            db.execute('UPDATE ingestion_runs SET status=?, finished_at=? WHERE id=?',
                       ('succeeded', timestamp(datetime.now(UTC)), run_id))
        return {'run_id': run_id, 'snapshot_id': snapshot_id, 'security_id': security_id,
                'bars_in_snapshot': len(bars), 'new_bars': new_bars,
                'actions_in_snapshot': len(actions), 'new_actions': new_actions,
                'first_date': str(bars[0].trading_date), 'last_date': str(bars[-1].trading_date),
                'quarantined': len(rejected), 'quarantine_file': str(report_path), 'price_basis': PRICE_BASIS}
    except Exception as error:
        db.rollback()
        with db:
            if raw_record:
                db.execute('INSERT INTO raw_documents VALUES (?, ?, ?, ?, ?, ?, ?, ?)', raw_record)
            db.execute('UPDATE ingestion_runs SET status=?, finished_at=?, error=? WHERE id=?',
                       ('failed', timestamp(datetime.now(UTC)), str(error), run_id))
        raise


def replay_response(db, data_dir: Path, snapshot_id: str):
    row = db.execute('''SELECT r.* FROM raw_documents r JOIN market_snapshots s
        ON r.id=s.raw_document_id WHERE s.id=?''', (snapshot_id,)).fetchone()
    if row is None:
        raise ValueError('Unknown market snapshot')
    root = Path(data_dir).resolve()
    location = (root / row['relative_path']).resolve()
    if not location.is_relative_to(root):
        raise ValueError('Raw path escapes data directory')
    content = location.read_bytes()
    if hashlib.sha256(content).hexdigest() != row['sha256']:
        raise ValueError('Raw market evidence hash mismatch')
    return content, datetime.fromisoformat(row['retrieved_at']), row['source_url']
