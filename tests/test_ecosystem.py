from copy import deepcopy
from decimal import Decimal
from pathlib import Path
import csv
import json

import pytest

from stock_factor_engine.ecosystem.model import load_registry, validate, view_as_of, summarize, reciprocal_candidates
from stock_factor_engine.ecosystem.report import build_report


REGISTRY = Path(__file__).resolve().parents[1] / 'research/ai-ecosystem'


@pytest.fixture
def bundle():
    return load_registry(REGISTRY)


def current(bundle):
    return view_as_of(bundle, bundle['config']['as_of'])


def test_seed_map_is_not_claimed_as_95_percent_or_consolidated_accounts(bundle):
    result = summarize(bundle, current(bundle))
    assert result['company_group_count'] == 32
    assert result['reference_node_count'] == 3
    assert result['global_flow_coverage'] is None
    assert result['group_external_net_cash_usd'] is None
    assert result['documented_cash_subtotal_usd'] is None
    assert result['known_usd_amount_records'] > 0


def test_announcements_and_credit_capacity_are_not_settled_cash(bundle):
    result = summarize(bundle, current(bundle))
    assert result['verified_cash_record_count'] == 0
    for edge in current(bundle)['active']:
        assert edge['cash_verified'] is False


def test_azure_amendment_replaces_old_amount_without_lookahead(bundle):
    now = {edge['id'] for edge in current(bundle)['active']}
    assert 'anthropic_azure_2026' in now and 'anthropic_azure_2025' not in now
    past = {edge['id'] for edge in view_as_of(bundle, '2026-01-01T00:00:00Z')['active']}
    assert 'anthropic_azure_2025' in past and 'anthropic_azure_2026' not in past


def test_future_or_unjustified_availability_is_not_used(bundle):
    key = 'amazon_q3'
    for source in bundle['sources']:
        if source['id'] == key:
            source['available_at'] = None
    view = current(bundle)
    assert 'amazon_openai_investment' in view['unavailable_disclosures']
    assert not any(key in edge['source_ids'] for edge in view['active'])


def test_aliases_do_not_double_count_cloud_parents_or_share_classes(bundle):
    aliases = validate(bundle)
    assert aliases['azure'] == aliases['microsoft']
    assert aliases['aws'] == aliases['amazon']
    assert aliases['goog'] == aliases['googl'] == aliases['google'] == 'alphabet'
    assert aliases['lambda inc.'] != aliases['aws']


def test_alias_collision_and_self_transaction_are_rejected(bundle):
    altered = deepcopy(bundle)
    altered['entities'][0]['aliases'].append('AWS')
    with pytest.raises(ValueError, match='two economic groups'):
        validate(altered)
    bundle['relationships'][0]['to_id'] = bundle['relationships'][0]['from_id']
    with pytest.raises(ValueError, match='self-transactions'):
        validate(bundle)


def test_unknown_counterparty_and_duplicate_observation_are_rejected(bundle):
    altered = deepcopy(bundle)
    altered['relationships'][0]['to_id'] = 'invented'
    with pytest.raises(ValueError, match='Unknown counterparty'):
        validate(altered)
    bundle['relationships'].append(deepcopy(bundle['relationships'][0]))
    with pytest.raises(ValueError, match='Duplicate'):
        validate(bundle)


def test_invalid_usd_number_or_unsourced_claim_is_rejected(bundle):
    altered = deepcopy(bundle)
    altered['relationships'][0]['amount_usd'] = 'NaN'
    with pytest.raises(ValueError, match='finite value'):
        validate(altered)
    bundle['relationships'][0]['source_ids'] = []
    with pytest.raises(ValueError, match='evidence source'):
        validate(bundle)


def test_revision_cycles_cannot_hide_disclosures(bundle):
    records = {edge['id']: edge for edge in bundle['relationships']}
    records['anthropic_azure_2026']['superseded_by'] = 'anthropic_azure_2025'
    with pytest.raises(ValueError, match='Cyclic'):
        validate(bundle)


def cash_edge(bundle, value='0'):
    edge = deepcopy(bundle['relationships'][0])
    edge.update(id='cash_example', kind='cash_payment', status='settled_cash', amount_usd=value,
                cash_verified=True, settled_on='2025-11-18', settlement_id='single-bank-settlement',
                amount_qualifier='verified_settlement')
    edge.pop('superseded_by',None)
    return edge


def test_real_verified_zero_cash_is_distinct_from_missing_cash(bundle):
    bundle['relationships'].append(cash_edge(bundle))
    validate(bundle)
    result = summarize(bundle, current(bundle))
    assert result['verified_cash_record_count'] == 1
    assert result['documented_cash_subtotal_usd'] == Decimal(0)
    assert result['group_external_net_cash_usd'] is None


def test_same_settlement_cannot_be_summed_twice(bundle):
    first = cash_edge(bundle,'10')
    second = deepcopy(first)
    second['id'] = 'another_disclosure_same_payment'
    bundle['relationships'].extend([first,second])
    with pytest.raises(ValueError, match='Duplicate cash settlement'):
        summarize(bundle,current(bundle))


def test_cash_claim_requires_date_and_proof_not_just_a_flag(bundle):
    bundle['relationships'][0]['cash_verified'] = True
    with pytest.raises(ValueError, match='explicitly verified settled cash'):
        validate(bundle)


def test_financing_customer_pairs_do_not_treat_lease_pool_as_broadcom(bundle):
    pairs = reciprocal_candidates(current(bundle))
    names = {(item['funder'],item['customer']) for item in pairs}
    assert ('amazon','anthropic') in names
    assert ('microsoft','anthropic') in names
    assert ('alphabet','anthropic') in names
    assert ('broadcom','anthropic') not in names


def test_export_labels_unknowns_and_excludes_obsolete_azure_amount(tmp_path):
    result = build_report(REGISTRY,tmp_path)
    with (tmp_path/'relationships.csv').open(encoding='utf-8-sig') as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == result['active_relationship_count']
    assert not any(row['ID']=='anthropic_azure_2025' for row in rows)
    assert all(row['Aggregation permitted']=='False' for row in rows)
    unknown = next(row for row in rows if row['ID']=='microsoft_nscale')
    assert unknown['USD amount'] == ''
    report = (tmp_path/'ecosystem.md').read_text(encoding='utf-8')
    assert '95% nije dokazana' in report
    assert 'unavailable' in report
    manifest = json.loads((tmp_path/'manifest.json').read_text())
    assert 'relationships.csv' in manifest['output_sha256']


def test_historical_report_requires_historical_entity_perimeter(tmp_path):
    with pytest.raises(ValueError, match='Refresh entity perimeter'):
        build_report(REGISTRY,tmp_path,'2025-01-01T00:00:00Z')
