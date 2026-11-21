"""Hash-locked, explicitly reviewed S-1 bridge; no general S-1 inference."""
from datetime import date, timedelta
from decimal import Decimal as D
from html.parser import HTMLParser
import hashlib
import re
from .model import instant


class Tables(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables, self.stack = [], []

    def handle_starttag(self, tag, attrs):
        if tag == 'table':
            self.stack.append([])

    def handle_endtag(self, tag):
        if tag == 'table' and self.stack:
            self.tables.append(re.sub(r'\s+', ' ', ' '.join(self.stack.pop())))

    def handle_data(self, data):
        for table in self.stack:
            table.append(data.strip())


def reviewed_financials(entity, review, source, evidence_dir, as_of):
    if review['entity_id'] != entity['id'] or source['id'] != review['source_id']:
        raise ValueError('Reviewed source/entity mismatch')
    if instant(source['available_at']) > instant(as_of):
        raise ValueError('Reviewed statement not available at cutoff')
    path = evidence_dir / review['relative_file']
    if path.name != review['relative_file']:
        raise ValueError('Reviewed evidence filename must not contain a path')
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != review['sha256']:
        raise ValueError('Reviewed statement SHA-256 mismatch; re-review extraction')
    tables = Tables()
    tables.feed(content.decode('utf-8', errors='replace'))
    for check in [*review['metrics'].values(), *review.get('additional_checks', [])]:
        if check['required_text'] not in tables.tables[check['table_index']]:
            raise ValueError('Reviewed table/amount anchor changed')
    annual, prior, current = [(date.fromisoformat(a), date.fromisoformat(b)) for a, b in review['periods']]
    if (annual[0] != prior[0] or annual[1] != date(annual[0].year, 12, 31)
            or current[0] != annual[1] + timedelta(days=1)
            or (prior[1].month, prior[1].day) != (current[1].month, current[1].day)
            or (prior[1] + timedelta(days=1)).isoformat() != review['ttm_start']
            or current[1].isoformat() != review['ttm_end'] or current[1] > instant(as_of).date()):
        raise ValueError('Reviewed TTM bridge periods are not contiguous')
    result = {'entity_id': entity['id'], 'company': entity['name'], 'cik': None,
        'scope': 'whole issuer; manually reviewed S-1, not external group accounts',
        'status': 'partial', 'reporting_end': review['ttm_end'], 'sources': [source],
        'metrics': {}, 'reasons': ['Cash/debt/net PP&E balance reconciliation not complete'],
        'reviewed_period_context': review['latest_period_context_millions'],
        'reviewed_period': review['periods'][2], 'review_notes': review['notes']}
    for name, metric in review['metrics'].items():
        values = [D(str(x)) * 1000000 for x in metric['values_millions']]
        if len(values) != 3 or any(not x.is_finite() for x in values):
            raise ValueError('Invalid reviewed statement amount')
        result['metrics'][name] = {'value': values[0] - values[1] + values[2],
            'status': 'available', 'period_start': review['ttm_start'], 'period_end': review['ttm_end'],
            'method': 'reviewed_annual_minus_prior_YTD_plus_current_YTD',
            'basis': 'reported_parent_TTM', 'source_url': source['url'], 'available_at': source['available_at'],
            'sha256': review['sha256'], 'terms': [{'period': period, 'coefficient': coefficient, 'value_usd': value}
                for period, coefficient, value in zip(review['periods'], (1, -1, 1), values)],
            'anchor': metric['required_text'], 'table_index': metric['table_index']}
    cfo, capex = [result['metrics'][k]['value'] for k in ('operating_cash_flow', 'capital_expenditure')]
    result['reported_parent_cash_after_ppe_usd'] = cfo - capex
    result['reported_parent_cfo_to_ppe_ratio'] = cfo / capex if capex > 0 else None
    c = {key: D(str(value)) for key, value in review['latest_period_context_millions'].items()}
    delta = c['operating_cash_flow'] + c['investing_cash_flow'] + c['financing_cash_flow'] + c['fx']
    result['cash_statement_reconciliation_millions'] = c['opening_cash_including_restricted'] + delta - c['closing_cash_including_restricted']
    if result['cash_statement_reconciliation_millions'] != 0:
        result['reasons'].append('Reported statement cash reconciliation fails')
    return result
