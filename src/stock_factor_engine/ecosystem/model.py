from datetime import datetime, date
from decimal import Decimal
import json
from pathlib import Path


FINANCING = {'equity_commitment', 'reported_equity_investment', 'conditional_equity', 'financing_facility', 'equity_intent'}
PURCHASES = {'compute_commitment', 'lease_commitment', 'capacity_backstop', 'hardware_framework'}
KNOWN_STATUSES = {'historical_disclosure', 'contractual', 'conditional', 'reported', 'nonbinding', 'announced', 'settled_cash'}


def instant(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00')) if isinstance(value, str) else value
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError('An aware availability/as-of timestamp is required')
    return result


def unique(items, label):
    result = {}
    for item in items:
        if not item.get('id') or item['id'] in result:
            raise ValueError('Duplicate or missing ' + label + ' id')
        result[item['id']] = item
    return result


def validate(bundle):
    nodes = unique(bundle['entities'], 'entity')
    sources = unique(bundle['sources'], 'source')
    edges = unique(bundle['relationships'], 'relationship')
    unique(bundle['contexts'], 'context')
    aliases = {}
    for node in nodes.values():
        for value in [node['name'], *node.get('aliases', [])]:
            alias = value.strip().casefold()
            if alias in aliases and aliases[alias] != node['id']:
                raise ValueError('Alias belongs to two economic groups: ' + value)
            aliases[alias] = node['id']
    def refs(item):
        if not item.get('source_ids') or any(key not in sources for key in item['source_ids']):
            raise ValueError('Missing or unknown evidence source')
    for source in sources.values():
        if source.get('evidence_type') != 'primary' or not source['url'].startswith('https://'):
            raise ValueError('Primary HTTPS evidence is required')
        if source.get('available_at') is not None:
            instant(source['available_at'])
    for node in nodes.values():
        allowed = bundle['config'].get('company_layers')
        if node['node_type'] == 'company_group' and allowed is not None and node['layer'] not in allowed:
            raise ValueError('Company outside operating perimeter: ' + node['id'])
        refs(node)
    for edge in edges.values():
        refs(edge)
        if edge['from_id'] not in nodes or edge['to_id'] not in nodes:
            raise ValueError('Unknown counterparty')
        if edge['from_id'] == edge['to_id']:
            raise ValueError('Parent/alias self-transactions must not be double counted')
        if edge['status'] not in KNOWN_STATUSES:
            raise ValueError('Unknown relationship status')
        if edge.get('amount_usd') is not None:
            value = Decimal(edge['amount_usd'])
            if not value.is_finite() or value < 0 or not edge.get('amount_qualifier'):
                raise ValueError('A monetary amount needs a finite value and explicit basis')
        successor = edge.get('superseded_by')
        if successor and successor not in edges:
            raise ValueError('Unknown superseding disclosure')
        seen = {edge['id']}
        while successor:
            if successor in seen:
                raise ValueError('Cyclic disclosure revisions')
            seen.add(successor)
            successor = edges[successor].get('superseded_by')
        if edge.get('cash_verified'):
            if edge['status'] != 'settled_cash' or edge.get('amount_usd') is None or not edge.get('settled_on') or not edge.get('settlement_id'):
                raise ValueError('Only dated, explicitly verified settled cash is cash')
            settlement = date.fromisoformat(edge['settled_on'])
            for key in edge['source_ids']:
                if sources[key].get('available_at') is None or settlement > instant(sources[key]['available_at']).date():
                    raise ValueError('Cash evidence must not precede settlement')
    for context in bundle['contexts']:
        refs(context)
        if context['entity_id'] not in nodes:
            raise ValueError('Unknown aggregate-context entity')
    return aliases


def load_registry(directory):
    directory = Path(directory)
    bundle = {name: json.loads((directory / (name + '.json')).read_text(encoding='utf-8'))
              for name in ('config', 'entities', 'relationships', 'sources', 'contexts')}
    validate(bundle)
    return bundle


def known_at(item, sources):
    values = [sources[key].get('available_at') for key in item['source_ids']]
    return None if any(value is None for value in values) else max(instant(value) for value in values)


def view_as_of(bundle, as_of):
    validate(bundle)
    cutoff = instant(as_of)
    sources = {item['id']: item for item in bundle['sources']}
    known, unavailable = {}, []
    for edge in bundle['relationships']:
        available = known_at(edge, sources)
        if available is not None and available <= cutoff:
            known[edge['id']] = edge
        else:
            unavailable.append(edge['id'])
    active = [edge for edge in known.values() if edge.get('superseded_by') not in known]
    contexts = [item for item in bundle['contexts'] if known_at(item, sources) is not None and known_at(item, sources) <= cutoff]
    return {'as_of': cutoff.isoformat(), 'active': active, 'historical': list(known.values()),
            'unavailable_disclosures': unavailable, 'contexts': contexts}


def summarize(bundle, view):
    settled = [edge for edge in view['active'] if edge.get('cash_verified')
               and date.fromisoformat(edge['settled_on']) <= instant(view['as_of']).date()]
    if len({edge['settlement_id'] for edge in settled}) != len(settled):
        raise ValueError('Duplicate cash settlement observations cannot be added')
    # This is a subtotal of documented cash only, never full group net cash.
    subtotal = sum((Decimal(edge['amount_usd']) for edge in settled), Decimal(0)) if settled else None
    return {'as_of': view['as_of'], 'company_group_count': sum(node['node_type'] == 'company_group' for node in bundle['entities']),
            'reference_node_count': sum(node['node_type'] != 'company_group' for node in bundle['entities']),
            'active_relationship_count': len(view['active']),
            'historical_disclosure_count': len(view['historical']),
            'known_usd_amount_records': sum(edge.get('amount_usd') is not None for edge in view['active']),
            'verified_cash_record_count': len(settled), 'documented_cash_subtotal_usd': subtotal,
            'group_external_net_cash_usd': None, 'group_external_revenue_usd': None,
            'consolidated_financials_status': 'unavailable',
            'target_coverage': bundle['config']['target_coverage'], 'global_flow_coverage': None,
            'coverage_status': 'unverified: no reconciled common-basis denominator',
            'notes': 'Contract values, lease principal, intentions, facilities, warrant shares and project targets are not added or netted.'}


def reciprocal_candidates(view):
    candidates = []
    for funding in view['active']:
        if funding['kind'] not in FINANCING:
            continue
        purchases = [edge for edge in view['active'] if edge['kind'] in PURCHASES
                     and edge['from_id'] == funding['to_id'] and edge['to_id'] == funding['from_id']]
        if purchases:
            candidates.append({'funder': funding['from_id'], 'customer': funding['to_id'],
                'funding_id': funding['id'], 'purchase_ids': [edge['id'] for edge in purchases],
                'interpretation': 'Potential financing/customer dependence, not proof of same-money round-tripping or improper revenue.'})
    return candidates
