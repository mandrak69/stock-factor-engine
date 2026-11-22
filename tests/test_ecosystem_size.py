from copy import deepcopy
from decimal import Decimal as D
import csv
import json
from pathlib import Path

import pytest

from stock_factor_engine.ecosystem.model import load_registry
from stock_factor_engine.ecosystem.selection import evaluate_size, select_report_bundle
from stock_factor_engine.ecosystem.report import build_report


REGISTRY=Path(__file__).resolve().parents[1]/'research/ai-ecosystem'
ASOF='2026-11-20T21:30:00Z'
MINIMUM='50000000000'


def public(amount):
    return {'entity_id':'example','market_value_usd':str(amount),'currency':'USD',
        'valuation_basis':'public_equity_market_cap','observed_on':'2026-11-20',
        'observation_at':'2026-11-20T21:00:00Z','available_at':None,
        'native_currency':'USD','native_market_value':str(amount),
        'source_url':'https://example.test/dated-cap',
        'point_in_time_status':'retrospective vendor snapshot; vintage unverified'}


@pytest.mark.parametrize('amount,status', [('49999999999','below_threshold'),('50000000000','included'),('50000000001','included')])
def test_threshold_is_inclusive_and_uses_equity_value(amount,status):
    assert evaluate_size(public(amount),as_of=ASOF,minimum=MINIMUM)['status']==status


def test_enterprise_value_and_revenue_do_not_qualify_as_market_cap():
    row=public('90000000000'); row['valuation_basis']='enterprise_value'
    with pytest.raises(ValueError,match='no EV/revenue/backlog'):
        evaluate_size(row,as_of=ASOF,minimum=MINIMUM)


def test_unknown_valuation_is_not_assumed_to_be_zero_or_below_threshold():
    assert evaluate_size({'market_value_usd':None},as_of=ASOF,minimum=MINIMUM)['status']=='unavailable'


def test_native_currency_billions_do_not_pass_usd_threshold_without_conversion():
    row=public('30000000000')
    row.update(native_currency='TWD',native_market_value='960000000000')
    row['fx']={'native_per_usd':'32','observation_date':'2026-11-19','completed_at':'2026-11-20T00:00:00Z'}
    assert evaluate_size(row,as_of=ASOF,minimum=MINIMUM)['status']=='below_threshold'
    row['market_value_usd']='960000000000'
    with pytest.raises(ValueError,match='FX does not equal'):
        evaluate_size(row,as_of=ASOF,minimum=MINIMUM)


def test_future_fx_bar_cannot_be_used_for_usd_conversion():
    row=public('30000000000')
    row.update(native_currency='TWD',native_market_value='960000000000')
    row['fx']={'native_per_usd':'32','observation_date':'2026-11-20','completed_at':'2026-11-21T00:00:00Z'}
    with pytest.raises(ValueError,match='completed before'):
        evaluate_size(row,as_of=ASOF,minimum=MINIMUM)


def test_future_or_wrong_date_public_valuation_is_not_used():
    row=public('90000000000'); row['observed_on']='2026-11-21'
    assert evaluate_size(row,as_of=ASOF,minimum=MINIMUM)['status']=='unavailable'
    row=public('90000000000'); row['observed_on']='2026-11-19'
    assert evaluate_size(row,as_of=ASOF,minimum=MINIMUM)['status']=='unavailable'
    row=public('90000000000'); row['available_at']='2026-11-21T00:00:00Z'
    assert evaluate_size(row,as_of=ASOF,minimum=MINIMUM)['status']=='unavailable'


def test_private_proxy_is_labeled_can_be_disabled_and_expires():
    row=public('852000000000')
    row.update(valuation_basis='private_round_proxy',observed_on='2026-03-31',available_at='2026-04-02T00:00:00Z')
    assert evaluate_size(row,as_of=ASOF,minimum=MINIMUM)['status']=='included'
    assert evaluate_size(row,as_of=ASOF,minimum=MINIMUM,allow_private_proxy=False)['status']=='unavailable'
    row['observed_on']='2025-01-01'
    assert evaluate_size(row,as_of=ASOF,minimum=MINIMUM)['status']=='unavailable'


def test_size_filter_preserves_source_corpus_and_removes_dangling_relationships():
    bundle=load_registry(REGISTRY); original=deepcopy(bundle)
    selected,decisions=select_report_bundle(bundle,REGISTRY)
    assert bundle==original
    ids={e['id'] for e in selected['entities']}
    assert len([e for e in selected['entities'] if e['node_type']=='company_group'])==18
    assert not ids & {'fluidstack','lambda','nscale','coreweave','nebius','supermicro','fabrinet','lenovo','quanta','wiwynn','wistron'}
    assert all(r['from_id'] in ids and r['to_id'] in ids for r in selected['relationships'])
    assert len([d for d in decisions if d['status']=='below_threshold'])==8
    assert len([d for d in decisions if d['status']=='unavailable'])==3


def test_main_map_exports_only_selected_companies_and_separate_exclusion_audit(tmp_path):
    result=build_report(REGISTRY,tmp_path)
    assert result['company_group_count']==18
    with (tmp_path/'participants.csv').open(encoding='utf-8-sig') as stream:
        rows=list(csv.DictReader(stream))
    assert not {r['ID'] for r in rows} & {'lambda','fluidstack','coreweave','nebius'}
    with (tmp_path/'size-exclusions.csv').open(encoding='utf-8-sig') as stream:
        excluded=list(csv.DictReader(stream))
    assert len(excluded)==11
    assert next(r for r in excluded if r['entity_id']=='lambda')['status']=='unavailable'
