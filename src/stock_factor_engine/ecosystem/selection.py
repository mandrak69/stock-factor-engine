"""Size filter for the AI report only; never changes CompoundRank selection."""
from copy import deepcopy
from datetime import date
from decimal import Decimal as D
import csv
import hashlib
import json
from pathlib import Path

from .model import instant, validate


FIELDS = ['entity_id', 'company', 'status', 'market_value_usd', 'currency', 'valuation_basis',
          'observed_on', 'available_at', 'native_currency', 'native_market_value', 'source_url',
          'point_in_time_status', 'reason']


def evaluate_size(row, *, as_of, minimum, allow_private_proxy=True, private_max_age_days=365):
    cutoff = instant(as_of)
    amount = row.get('market_value_usd')
    if amount is None:
        return {**row, 'status': 'unavailable', 'reason': row.get('reason') or 'No reliable equity valuation; not assumed zero'}
    value, threshold = D(str(amount)), D(str(minimum))
    if not value.is_finite() or value <= 0 or not threshold.is_finite() or threshold <= 0:
        raise ValueError('Equity market values and threshold must be finite positive values')
    if row.get('currency') != 'USD' or not row.get('source_url', '').startswith('https://'):
        raise ValueError('USD equity value and source URL required')
    observed = date.fromisoformat(row['observed_on'])
    if observed > cutoff.date() or (row.get('available_at') and instant(row['available_at']) > cutoff):
        return {**row, 'status': 'unavailable', 'reason': 'Valuation not known by decision cutoff'}
    basis = row['valuation_basis']
    if basis == 'public_equity_market_cap':
        if observed != cutoff.date() or instant(row['observation_at']) > cutoff:
            return {**row, 'status': 'unavailable', 'reason': 'No exact decision-date completed-close market cap'}
        if row.get('available_at') is None and not row.get('point_in_time_status', '').startswith('retrospective vendor snapshot'):
            raise ValueError('Missing availability needs explicit retrospective-vintage qualification')
        native = D(row['native_market_value'])
        if not native.is_finite() or native <= 0:
            raise ValueError('Invalid native equity capitalization')
        if row['native_currency'] != 'USD':
            fx = row['fx']
            rate = D(fx['native_per_usd'])
            if not rate.is_finite() or rate <= 0 or instant(fx['completed_at']) > cutoff:
                raise ValueError('FX must be positive and completed before decision time')
            if date.fromisoformat(fx['observation_date']) > observed or native / rate != value:
                raise ValueError('Native equity value / FX does not equal USD value')
        elif native != value:
            raise ValueError('USD native and filtered values disagree')
    elif basis == 'private_round_proxy':
        if not allow_private_proxy or not row.get('available_at') or (cutoff.date() - observed).days > private_max_age_days:
            return {**row, 'status': 'unavailable', 'reason': 'Private funding proxy disallowed, unavailable or stale'}
    else:
        raise ValueError('Only equity capitalization or labeled private equity proxy is valid; no EV/revenue/backlog')
    return {**row, 'status': 'included' if value >= threshold else 'below_threshold',
            'reason': row.get('reason', '') if value >= threshold else 'Equity value below USD ' + str(threshold)}


def select_report_bundle(bundle, registry):
    """Keep excluded operators in the source corpus, outside the selected boundary."""
    policy = bundle['config'].get('report_size_filter')
    if not policy:
        return bundle, []
    rows = json.loads((Path(registry) / 'market-values.json').read_text(encoding='utf-8'))
    by_id = {}
    for row in rows:
        if row['entity_id'] in by_id:
            raise ValueError('Duplicate issuer market value')
        by_id[row['entity_id']] = row
    decisions = []
    for entity in bundle['entities']:
        if entity['node_type'] != 'company_group':
            continue
        row = by_id.get(entity['id'], {'entity_id': entity['id'], 'market_value_usd': None})
        decisions.append({**evaluate_size(row, as_of=bundle['config']['as_of'], minimum=policy['minimum_usd'],
            allow_private_proxy=policy['allow_private_proxy'], private_max_age_days=policy['private_max_age_days']),
            'company': entity['name']})
    kept = {r['entity_id'] for r in decisions if r['status'] == 'included'}
    result = deepcopy(bundle)
    result['entities'] = [e for e in result['entities'] if e['node_type'] != 'company_group' or e['id'] in kept]
    ids = {e['id'] for e in result['entities']}
    result['relationships'] = [r for r in result['relationships'] if r['from_id'] in ids and r['to_id'] in ids]
    result['contexts'] = [r for r in result['contexts'] if r['entity_id'] in ids]
    validate(result)
    return result, decisions


def export_size_selection(output, decisions):
    output = Path(output)
    for name, rows in [('market-values.csv', [r for r in decisions if r['status'] == 'included']),
                       ('size-exclusions.csv', [r for r in decisions if r['status'] != 'included'])]:
        with (output / name).open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(rows)


def verify_local_captures(rows, folder):
    """Optional raw-capture audit; curated observations remain usable in clean CI."""
    checked, missing = [], []
    for row in rows:
        references = [row] + ([row['fx']] if row.get('fx') else [])
        for ref in references:
            if not ref.get('evidence_file'):
                continue
            path = Path(folder) / ref['evidence_file']
            if path.name != ref['evidence_file']:
                raise ValueError('Market-value evidence must have a plain filename')
            if not path.exists():
                missing.append(path.name)
            elif hashlib.sha256(path.read_bytes()).hexdigest() != ref['sha256']:
                raise ValueError('Market-value evidence hash mismatch')
            else:
                checked.append(path.name)
    return {'checked': sorted(set(checked)), 'missing_local_captures': sorted(set(missing)),
            'point_in_time_status': 'Vendor close snapshots reconstructed retrospectively; dissemination/share-count vintage not independently archived'}
