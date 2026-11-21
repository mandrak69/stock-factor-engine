"""Traceable parent-company context, deliberately separate from boundary accounts."""
from dataclasses import asdict
from datetime import timedelta
from decimal import Decimal as D
import json
import gzip
import hashlib
from pathlib import Path

from stock_factor_engine.current.report import load_evidence
from stock_factor_engine.providers.sec.ingestion import parse_filings, parse_facts
from stock_factor_engine.point_in_time.financials import facts_as_of
from stock_factor_engine.fundamentals.ttm import calculate_ttm
from .model import instant


ISSUERS = {
    'nvidia': '0001045810', 'amd': '0000002488', 'broadcom': '0001730168',
    'microsoft': '0000789019', 'amazon': '0001018724', 'alphabet': '0001652044',
    'meta': '0001326801', 'oracle': '0001341439', 'coreweave': '0001769628',
    'nebius': '0001513845', 'nscale': '0002110365', 'anthropic': '0002130357',
    'micron': '0000723125', 'dell': '0001571996', 'hpe': '0001645590',
    'supermicro': '0001375365', 'blackrock': '0002012383', 'fabrinet': '0001408710',
    'tsmc': '0001046179',
}
METRICS = ('revenue', 'operating_income', 'operating_cash_flow', 'capital_expenditure')


def read_cached(roots, key):
    for root in roots:
        if (Path(root) / 'raw' / (key + '.json.gz')).exists():
            return load_evidence(Path(root), key)
        location = Path(root) / (key + '.json.gz')
        if location.exists():
            content = gzip.decompress(location.read_bytes())
            meta = json.loads(location.with_name(key + '.meta.json').read_text(encoding='utf-8'))
            if hashlib.sha256(content).hexdigest() != meta['sha256']:
                raise ValueError('Evidence SHA-256 mismatch: ' + key)
            return content, meta
    raise FileNotFoundError('No archived evidence: ' + key)


def issuer_financials(entity, roots, as_of):
    cik = ISSUERS.get(entity['id'])
    result = {'entity_id': entity['id'], 'company': entity['name'], 'cik': cik,
              'scope': 'whole parent; includes non-AI and within-network business',
              'status': 'unavailable', 'metrics': {}, 'reasons': [], 'sources': []}
    if cik is None:
        if entity['id'] == 'quanta':
            result['reasons'].append('Official Q3 2026 IR presentation listing found, but download redirected to bot challenge; no verified numerical statement capture. https://www.quantatw.com/Quanta/english/investment/financials_icp.aspx')
        else:
            result['reasons'].append('No validated standardized USD TTM feed or complete same-period cash/revenue statements established in this evidence set; no inference from annualized revenue, funding announcements or missing data')
        return result
    try:
        subraw, submeta = read_cached(roots, 'submissions_' + cik)
        raw, meta = read_cached(roots, 'facts_' + cik)
        submissions, facts_payload = json.loads(subraw), json.loads(raw, parse_float=D)
        if any(str(p['cik']).zfill(10) != cik for p in (submissions, facts_payload)):
            raise ValueError('CIK mismatch')
        result['sources'] = [submeta, meta]
        filings, rejected = parse_filings(submissions['filings']['recent'], entity['id'])
        # Cached historical pages may add older accepted timestamps. Never infer
        # intraday availability from a filing date when a page lacks acceptance.
        for page in submissions['filings'].get('files', []):
            name = page['name']
            if '/' in name or '\\' in name or not name.startswith('CIK' + cik + '-'):
                raise ValueError('Invalid submissions archive name')
            try:
                content, archive_meta = read_cached(roots, 'archive_' + name[:-5])
            except FileNotFoundError:
                continue
            older, issues = parse_filings(json.loads(content), entity['id'])
            filings.extend(older)
            rejected.extend(issues)
            result['sources'].append(archive_meta)
        cutoff = instant(as_of)
        mapping = {}
        for filing in filings:
            if filing.accession_number in mapping and mapping[filing.accession_number] != filing:
                raise ValueError('Conflicting filing availability')
            mapping[filing.accession_number] = filing
        visible_filings = [f for f in mapping.values() if f.available_at <= cutoff and f.period_end <= cutoff.date()]
        if not visible_filings:
            raise ValueError('No accepted 10-Q/10-K with justified availability; IPO S-1/foreign 20-F/6-K requires a separate reviewed parser')
        end = max(f.period_end for f in visible_filings)
        result['reporting_end'] = end.isoformat()
        latest = max((f for f in visible_filings if f.period_end == end), key=lambda f: f.available_at)
        result['latest_filing'] = asdict(latest)
        parsed, issues = parse_facts(facts_payload, entity['id'], mapping)
        result['parser_quarantine_count'] = len(issues)
        facts = [f for f, _ in parsed if f.available_at <= cutoff and f.period_end <= end]
        for concept in METRICS:
            try:
                relevant = [f for f in facts if f.concept == concept and not f.is_instant
                            and end - timedelta(days=400) <= f.period_end <= end]
                selected = facts_as_of(relevant, company_id=entity['id'], as_of=cutoff)
                metric = calculate_ttm(selected, concept, end)
                if concept == 'capital_expenditure' and metric.value < 0:
                    raise ValueError('Negative gross cash capex')
                result['metrics'][concept] = {**asdict(metric), 'status': 'available', 'basis': 'reported_parent_TTM'}
            except ValueError as error:
                result['metrics'][concept] = {'status': 'unavailable', 'reason': str(error), 'value': None}
                result['reasons'].append(concept + ': ' + str(error))
        for concept in ('cash', 'total_debt', 'net_ppe'):
            try:
                selected = facts_as_of([f for f in facts if f.concept == concept and f.is_instant and f.period_end == end],
                                       company_id=entity['id'], as_of=cutoff)
                if not selected or len({f.value for f in selected}) != 1 or selected[-1].value < 0:
                    raise ValueError('Missing, ambiguous or negative exact-period standardized balance; no zero/debt-component assumption')
                result['metrics'][concept] = {'status': 'available', 'value': selected[-1].value,
                                              'period_end': end, 'evidence': asdict(selected[-1])}
            except ValueError as error:
                result['metrics'][concept] = {'status': 'unavailable', 'value': None, 'reason': str(error)}
                result['reasons'].append(concept + ': ' + str(error))
        cfo, capex = [result['metrics'][k] for k in ('operating_cash_flow', 'capital_expenditure')]
        if cfo['value'] is not None and capex['value'] is not None:
            if (cfo['period_start'], cfo['period_end']) == (capex['period_start'], capex['period_end']):
                result['reported_parent_cash_after_ppe_usd'] = cfo['value'] - capex['value']
                result['reported_parent_cfo_to_ppe_ratio'] = cfo['value'] / capex['value'] if capex['value'] > 0 else None
            else:
                result['reasons'].append('CFO/capex TTM periods differ; ratio withheld')
        result['status'] = 'partial' if result['reasons'] else 'available'
    except (OSError, ValueError, KeyError) as error:
        result['reasons'].append(type(error).__name__ + ': ' + str(error))
    return result
