from copy import deepcopy
import hashlib
from pathlib import Path

import pytest

from stock_factor_engine.ecosystem.supplemental import verify_ttm_bridge


@pytest.fixture
def bridge(tmp_path):
    evidence = tmp_path / 'supplemental-evidence'
    evidence.mkdir()
    annual = tmp_path / 'evidence'
    annual.mkdir()
    content = b'<p>Revenue $ 100</p>'
    (annual / 'annual.html').write_bytes(content)
    row = {'amount': '130', 'currency': 'USD', 'period_start': '2025-10-01', 'period_end': '2026-09-30',
        'ttm_bridge': {'unit': 'USD',
            'annual': {'period_start': '2025-01-01', 'period_end': '2025-12-31', 'value_usd': '100',
                'available_at': '2026-02-01T00:00:00Z', 'evidence_file': 'annual.html',
                'sha256': hashlib.sha256(content).hexdigest(), 'anchor': 'Revenue $ 100'},
            'prior_ytd': {'period_start': '2025-01-01', 'period_end': '2025-09-30', 'value_usd': '60'},
            'current_ytd': {'period_start': '2026-01-01', 'period_end': '2026-09-30', 'value_usd': '90'}}}
    return row, evidence


def test_ttm_bridge_uses_annual_minus_prior_ytd_plus_current_ytd(bridge):
    row, evidence = bridge
    verify_ttm_bridge(row, evidence, '2026-11-20T21:30:00Z')
    row['amount'] = '250'
    with pytest.raises(ValueError, match='arithmetic mismatch'):
        verify_ttm_bridge(row, evidence, '2026-11-20T21:30:00Z')


def test_ttm_bridge_does_not_mix_reporting_periods(bridge):
    row, evidence = bridge
    row['period_start'] = '2025-07-01'
    with pytest.raises(ValueError, match='contiguous'):
        verify_ttm_bridge(row, evidence, '2026-11-20T21:30:00Z')


def test_ttm_bridge_checks_annual_source_availability_and_hash(bridge):
    row, evidence = bridge
    row['ttm_bridge']['annual']['available_at'] = '2026-11-21T00:00:00Z'
    with pytest.raises(ValueError, match='not available'):
        verify_ttm_bridge(row, evidence, '2026-11-20T21:30:00Z')
    row['ttm_bridge']['annual']['available_at'] = '2026-02-01T00:00:00Z'
    (evidence.parent / 'evidence/annual.html').write_text('changed')
    with pytest.raises(ValueError, match='hash/path mismatch'):
        verify_ttm_bridge(row, evidence, '2026-11-20T21:30:00Z')
