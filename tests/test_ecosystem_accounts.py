from copy import deepcopy
from decimal import Decimal as D
import json
from pathlib import Path
import hashlib
import gzip

import pytest

from stock_factor_engine.ecosystem.ledger import calculate_accounts, internal_asset_adjustment
from stock_factor_engine.ecosystem.reviewed import reviewed_financials
from stock_factor_engine.ecosystem.supplemental import supplemental_statements
from stock_factor_engine.ecosystem.financials import read_cached
from stock_factor_engine.ecosystem.perimeter import accounting_perimeter


ASOF = '2026-11-20T21:30:00Z'
START, END = '2026-01-01', '2026-09-30'
SOURCE = ['https://example.test/primary-statement']


def transaction(key, payer, payee, amount, category='operating', basis='settled_cash'):
    return {'economic_id': key, 'payer': payer, 'payee': payee, 'amount_usd': str(amount),
            'currency': 'USD', 'source_urls': SOURCE, 'available_at': '2026-10-30T12:00:00Z',
            'period_start': START, 'period_end': END, 'category': category, 'basis': basis}


def compute(payload, members=('msft', 'openai', 'nvda')):
    return calculate_accounts(payload, members=members, as_of=ASOF, period_start=START, period_end=END)


def full_example():
    # Group manufactures equipment for its own use; the original external
    # production outlay is classified as group capex after reviewed adjustment.
    payload = {'external_counterparties': ['outside_supplier', 'outside_customer', 'outside_investor'],
        'cash': [transaction('funding', 'msft', 'openai', 100, 'financing'),
        transaction('cloud', 'openai', 'msft', 80), transaction('gpu', 'msft', 'nvda', 60, 'capex'),
        transaction('manufacturing', 'nvda', 'outside_supplier', 35, 'capex'),
        transaction('customers', 'outside_customer', 'openai', 50)],
        'sales': [transaction('cloud_invoice', 'openai', 'msft', 80, basis='recognized_revenue'),
                  transaction('gpu_invoice', 'msft', 'nvda', 60, basis='recognized_revenue'),
                  transaction('customer_invoice', 'outside_customer', 'openai', 50, basis='recognized_revenue')],
        'coverage': [{'entity_id': e, 'ledger': name, 'complete': True, 'period_start': START,
                      'period_end': END, 'available_at': ASOF, 'source_urls': SOURCE}
                     for e in ('msft', 'openai', 'nvda') for name in ('cash', 'sales')],
        'cash_reconciliation': {'opening_usd': '0', 'closing_usd': '15', 'fx_usd': '0',
            'period_start': START, 'period_end': END, 'available_at': ASOF, 'source_urls': SOURCE},
        'category_review': {'complete': True, 'period_start': START, 'period_end': END,
                            'available_at': ASOF, 'source_urls': SOURCE},
        'perimeter_review': {'complete': True, 'period_start': START, 'period_end': END,
                            'available_at': ASOF, 'source_urls': SOURCE}}
    return payload


def test_internal_investment_cloud_and_hardware_do_not_create_external_demand():
    result = compute(full_example())
    assert result['status'] == 'complete'
    assert result['external_revenue_usd'] == D(50)
    assert result['external_net_cash_usd'] == D(15)
    assert result['external_operating_cash_usd'] == D(50)
    assert result['external_gross_capex_usd'] == D(35)
    assert result['financing_gap_usd'] == D(-15)
    assert result['self_funding_coverage'] == D(50) / 35
    assert result['profit_usd'] is None


def test_changing_boundary_changes_what_is_external():
    result = compute({'external_counterparties': ['nvda'], 'cash': [transaction('gpu', 'msft', 'nvda', 60, 'capex')]}, members=('msft',))
    assert result['documented_external_cash_by_category_usd']['capex'] == D(-60)
    assert result['external_net_cash_usd'] is None


def test_empty_registry_is_unknown_not_zero():
    result = compute({})
    assert result['external_net_cash_usd'] is None
    assert result['external_revenue_usd'] is None
    assert result['documented_external_revenue_usd'] is None
    assert all(v is None for v in result['documented_external_cash_by_category_usd'].values())


def test_incomplete_single_member_prevents_group_total():
    payload = full_example()
    payload['coverage'].pop()
    result = compute(payload)
    assert result['status'] == 'unavailable'
    assert result['external_net_cash_usd'] is None
    assert result['documented_external_revenue_usd'] == D(50)


def test_future_filing_is_excluded_and_invalidates_complete_attestation():
    payload = full_example()
    payload['cash'][-1]['available_at'] = '2026-11-21T00:00:00Z'
    assert compute(payload)['external_net_cash_usd'] is None
    assert compute(payload)['excluded'][0]['id'] == 'customers'


def test_unknown_counterparty_cannot_be_assumed_external():
    payload = full_example()
    payload['cash'][-1]['payer'] = None
    result = compute(payload)
    assert result['external_net_cash_usd'] is None
    assert any('Unresolved counterparty' in g for g in result['gaps'])


def test_unrecognized_counterparty_spelling_is_not_automatically_outside_group():
    payload = full_example()
    payload['cash'][-1]['payer'] = 'misspelled_company'
    assert compute(payload)['external_net_cash_usd'] is None


@pytest.mark.parametrize('basis', ['announced', 'credit_limit', 'contract_notional', 'reported_equity_investment'])
def test_contracts_and_facilities_are_not_settled_cash(basis):
    with pytest.raises(ValueError, match='settled cash'):
        compute({'cash': [transaction('not_cash', 'msft', 'openai', 100, basis=basis)]})


def test_same_transfer_cannot_be_added_from_both_parties():
    payload = full_example()
    payload['cash'].append(deepcopy(payload['cash'][-1]))
    with pytest.raises(ValueError, match='Duplicate'):
        compute(payload)


def test_cash_reconciliation_and_fx_are_required():
    payload = full_example()
    payload['cash_reconciliation']['closing_usd'] = '16'
    assert compute(payload)['external_net_cash_usd'] is None
    payload['cash_reconciliation']['fx_usd'] = '1'
    assert compute(payload)['external_net_cash_usd'] == D(15)


def test_asset_category_review_required_for_self_funding_ratio():
    payload = full_example()
    payload.pop('category_review')
    result = compute(payload)
    assert result['external_net_cash_usd'] == D(15)
    assert result['self_funding_coverage'] is None
    assert result['external_operating_cash_usd'] is None


def test_actual_financing_crossing_boundary_is_not_operating_revenue():
    payload = full_example()
    payload['cash'].append(transaction('external_equity', 'outside_investor', 'openai', 200, 'financing'))
    payload['cash_reconciliation']['closing_usd'] = '215'
    result = compute(payload)
    assert result['external_net_cash_usd'] == D(215)
    assert result['external_revenue_usd'] == D(50)
    assert result['external_operating_cash_usd'] == D(50)


def test_profit_requires_internal_asset_margin_and_depreciation_adjustments():
    result = internal_asset_adjustment(transfer_price=100, group_cost=60, useful_life_years=5, elapsed_years=1)
    assert result['original_internal_margin_usd'] == D(40)
    assert result['remaining_internal_margin_usd'] == D(32)
    assert result['annual_depreciation_reduction_usd'] == D(8)
    assert result['group_net_book_value_usd'] == D(48)


@pytest.mark.parametrize('amount', ['NaN', 'Infinity', '-1'])
def test_nonfinite_or_negative_cash_is_rejected(amount):
    with pytest.raises(ValueError):
        compute({'cash': [transaction('bad', 'outside', 'openai', amount)]})


def test_non_usd_amount_requires_explicit_conversion_before_entry():
    row = transaction('bad', 'outside', 'openai', 10)
    row['currency'] = 'TWD'
    with pytest.raises(ValueError, match='USD'):
        compute({'cash': [row]})


def test_reviewed_statement_hash_and_availability_are_enforced(tmp_path):
    registry = Path(__file__).resolve().parents[1] / 'research/ai-ecosystem'
    review = json.loads((registry / 'reviewed-statements.json').read_text())[0]
    sources = json.loads((registry / 'sources.json').read_text())
    source = next(s for s in sources if s['id'] == review['source_id'])
    entity = {'id': 'anthropic', 'name': 'Anthropic'}
    with pytest.raises(ValueError, match='not available'):
        reviewed_financials(entity, review, source, tmp_path, '2026-01-01T00:00:00Z')
    (tmp_path / review['relative_file']).write_text('modified statement')
    with pytest.raises(ValueError, match='SHA-256'):
        reviewed_financials(entity, review, source, tmp_path, ASOF)


def test_supplemental_currency_period_and_hash_do_not_become_ttm(tmp_path):
    content = b'<p>Revenue 30.2</p>'
    (tmp_path / 'release.html').write_bytes(content)
    row = {'entity_id': 'lenovo', 'metric': 'revenue', 'period_start': '2026-07-01',
        'period_end': '2026-09-30', 'available_at': '2026-11-20T12:00:00Z',
        'evidence_file': 'release.html', 'sha256': hashlib.sha256(content).hexdigest(),
        'anchor': 'Revenue 30.2', 'amount': '30200000000', 'currency': 'USD'}
    result = supplemental_statements([row], tmp_path, ASOF, {'lenovo'})
    assert result[0]['amount'] == D('30200000000')
    assert result[0]['period_start'] == '2026-07-01'
    assert supplemental_statements([row], tmp_path, '2026-11-19T21:30:00Z', {'lenovo'}) == []
    with pytest.raises(ValueError, match='Duplicate'):
        supplemental_statements([row, row], tmp_path, ASOF, {'lenovo'})
    row['anchor'] = 'Revenue 40.2'
    with pytest.raises(ValueError, match='anchor changed'):
        supplemental_statements([row], tmp_path, ASOF, {'lenovo'})


def test_reviewed_ttm_bridge_and_cash_reconciliation(tmp_path):
    content = b'<table>Revenue 100 60 90</table><table>CFO -10 -5 20</table>'
    (tmp_path / 'statement.html').write_bytes(content)
    review = {'entity_id': 'issuer', 'source_id': 'source', 'relative_file': 'statement.html',
        'sha256': hashlib.sha256(content).hexdigest(),
        'periods': [['2025-01-01', '2025-12-31'], ['2025-01-01', '2025-09-30'], ['2026-01-01', '2026-09-30']],
        'ttm_start': '2025-10-01', 'ttm_end': '2026-09-30', 'notes': [],
        'metrics': {
            'revenue': {'values_millions': [100, 60, 90], 'table_index': 0, 'required_text': 'Revenue 100 60 90'},
            'operating_cash_flow': {'values_millions': [-10, -5, 20], 'table_index': 1, 'required_text': 'CFO -10 -5 20'},
            'capital_expenditure': {'values_millions': [10, 5, 20], 'table_index': 0, 'required_text': 'Revenue'}},
        'latest_period_context_millions': {'opening_cash_including_restricted': 10,
            'closing_cash_including_restricted': 30, 'operating_cash_flow': 20,
            'investing_cash_flow': -5, 'financing_cash_flow': 5, 'fx': 0}}
    source = {'id': 'source', 'url': SOURCE[0], 'available_at': ASOF}
    entity = {'id': 'issuer', 'name': 'Issuer'}
    result = reviewed_financials(entity, review, source, tmp_path, ASOF)
    assert result['metrics']['revenue']['value'] == D('130000000')
    assert result['metrics']['operating_cash_flow']['value'] == D('15000000')
    assert result['cash_statement_reconciliation_millions'] == 0
    review['ttm_start'] = '2025-09-30'
    with pytest.raises(ValueError, match='contiguous'):
        reviewed_financials(entity, review, source, tmp_path, ASOF)


def test_flat_sec_evidence_is_hash_checked(tmp_path):
    content = b'{"cik": 123}'
    (tmp_path / 'facts_123.json.gz').write_bytes(gzip.compress(content))
    (tmp_path / 'facts_123.meta.json').write_text(json.dumps({'sha256': hashlib.sha256(content).hexdigest()}))
    assert read_cached([tmp_path], 'facts_123')[0] == content
    (tmp_path / 'facts_123.json.gz').write_bytes(gzip.compress(b'{"cik": 999}'))
    with pytest.raises(ValueError, match='SHA-256'):
        read_cached([tmp_path], 'facts_123')


def test_control_folds_subsidiary_without_adding_parent_and_child_twice(tmp_path):
    content = b'%PDF reviewed note: parent controls subsidiary'
    (tmp_path / 'note.pdf').write_bytes(content)
    row = {'parent_id': 'parent', 'subsidiary_id': 'child', 'reported_control': True,
        'reported_ownership': '0.3371', 'period_start': START, 'period_end': END,
        'available_at': ASOF, 'evidence_file': 'note.pdf', 'sha256': hashlib.sha256(content).hexdigest()}
    result = accounting_perimeter({'parent', 'child'}, [row], tmp_path,
                                  as_of=ASOF, period_start=START, period_end=END)
    assert result['members'] == ['parent']
    assert result['canonical']['child'] == 'parent'
    row['reported_control'] = False
    with pytest.raises(ValueError, match='ownership alone'):
        accounting_perimeter({'parent', 'child'}, [row], tmp_path,
                             as_of=ASOF, period_start=START, period_end=END)


def test_future_control_disclosure_does_not_rewrite_old_perimeter(tmp_path):
    row = {'parent_id': 'parent', 'subsidiary_id': 'child', 'available_at': '2026-11-21T00:00:00Z'}
    result = accounting_perimeter({'parent', 'child'}, [row], tmp_path,
                                  as_of=ASOF, period_start=START, period_end=END)
    assert result['members'] == ['child', 'parent']


def test_full_cash_reconciliation_cannot_replace_control_perimeter_review():
    payload = full_example()
    payload.pop('perimeter_review')
    assert compute(payload)['external_net_cash_usd'] is None
