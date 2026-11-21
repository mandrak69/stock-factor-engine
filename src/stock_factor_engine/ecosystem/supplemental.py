"""Reviewed same-period disclosures supplement the standardized TTM feed."""
from datetime import date
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
        result.append({**row, 'amount': amount,
            'basis': 'reported issuer, no internal eliminations; never external AI-only cash'})
    return result
