"""Reviewed same-period disclosures supplement the standardized TTM feed."""
from datetime import date, timedelta
from decimal import Decimal
from html.parser import HTMLParser
import hashlib
import re

from .model import instant


class Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def supplemental_statements(rows, evidence_dir, as_of, members):
    result, keys = [], set()
    for row in rows:
        key = (row['entity_id'], row['metric'], row['period_start'], row['period_end'])
        if key in keys:
            raise ValueError('Duplicate supplemental observation')
        keys.add(key)
        if row['entity_id'] not in members or date.fromisoformat(row['period_start']) > date.fromisoformat(row['period_end']):
            raise ValueError('Invalid supplemental entity/period')
        if instant(row['available_at']) > instant(as_of):
            continue
        if date.fromisoformat(row['period_end']) > instant(row['available_at']).date():
            raise ValueError('Supplemental evidence precedes reporting period')
        path = evidence_dir / row['evidence_file']
        if path.name != row['evidence_file']:
            raise ValueError('Evidence filename must not contain a path')
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != row['sha256']:
            raise ValueError('Supplemental evidence hash mismatch')
        if row.get('evidence_format') == 'reviewed_pdf':
            if not content.startswith(b'%PDF') or not isinstance(row.get('reviewed_page_index'), int) or row['reviewed_page_index'] < 0 or not row.get('locator'):
                raise ValueError('PDF needs explicitly reviewed page/column and original PDF bytes')
        else:
            text = Text()
            text.feed(content.decode('utf-8', errors='replace'))
            normalized = re.sub(r'\s+', ' ', ' '.join(text.parts).replace('\u200b', ''))
            if row['anchor'] not in normalized:
                raise ValueError('Supplemental amount anchor changed: ' + str(key))
        amount = Decimal(str(row['amount']))
        if not amount.is_finite():
            raise ValueError('Nonfinite supplemental amount')
        if row.get('ttm_bridge'):
            verify_ttm_bridge(row, evidence_dir, as_of)
        result.append({**row, 'amount': amount,
            'basis': 'reported issuer, no internal eliminations; never external AI-only cash'})
    return result


def verify_ttm_bridge(row, evidence_dir, as_of):
    """Annual minus prior YTD plus current YTD, with both source captures pinned."""
    bridge = row['ttm_bridge']
    annual, prior, current = [bridge[k] for k in ('annual', 'prior_ytd', 'current_ytd')]
    if row['currency'] != 'USD' or bridge['unit'] != 'USD':
        raise ValueError('TTM bridge requires consistent USD units')
    if instant(annual['available_at']) > instant(as_of):
        raise ValueError('Annual bridge evidence not available at cutoff')
    path = evidence_dir.parent / 'evidence' / annual['evidence_file']
    if path.name != annual['evidence_file'] or hashlib.sha256(path.read_bytes()).hexdigest() != annual['sha256']:
        raise ValueError('Annual bridge evidence hash/path mismatch')
    text = Text()
    text.feed(path.read_text(encoding='utf-8', errors='replace'))
    if annual['anchor'] not in re.sub(r'\s+', ' ', ' '.join(text.parts)):
        raise ValueError('Annual bridge amount anchor changed')
    d = date.fromisoformat
    if (annual['period_start'] != prior['period_start']
            or d(annual['period_end']) + timedelta(days=1) != d(current['period_start'])
            or d(prior['period_end']) + timedelta(days=1) != d(row['period_start'])
            or current['period_end'] != row['period_end']
            or not d(prior['period_start']) <= d(prior['period_end']) < d(annual['period_end']) < d(current['period_end'])
            or not 350 <= (d(row['period_end']) - d(row['period_start'])).days + 1 <= 380):
        raise ValueError('TTM bridge periods do not form a contiguous trailing year')
    amounts = [Decimal(str(term['value_usd'])) for term in (annual, prior, current)]
    if any(not value.is_finite() or value < 0 for value in amounts) or amounts[0] - amounts[1] + amounts[2] != Decimal(row['amount']):
        raise ValueError('TTM bridge arithmetic mismatch')
