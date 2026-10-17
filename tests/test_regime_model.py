from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal as D

import pytest

from stock_factor_engine.factors.prices import Factor
from stock_factor_engine.regime.model import (
    COMPONENT_WEIGHTS, EXPOSURES, SCORE_ANCHORS, VixFrontMonth,
    apply_exposure, component_score, evaluate_market_regime,
)


SESSION = date(2024, 10, 7)


def inputs(**overrides):
    values = dict(breadth=D('.50'), rsp_spy=D(0), spy_trend=D(0),
                  vix_spot=D('22.5'), hyg_lqd=D(0))
    values.update({key: D(value) if value is not None else None for key, value in overrides.items()})
    return {key: Factor(value, key, period_end=SESSION) for key, value in values.items()}


def vx(close='20'):
    return VixFrontMonth(SESSION, D(close), 'VX concrete test contract', SESSION + timedelta(days=20),
                         'verified test provider fixture')


@pytest.mark.parametrize('name,low,mid,high', [
    ('breadth', '.30', '.50', '.70'), ('rsp_spy', '-.05', '0', '.05'),
    ('spy_trend', '-.10', '0', '.10'), ('vix_spot', '30', '22.5', '15'),
    ('hyg_lqd', '-.03', '0', '.03'),
])
def test_approved_anchor_scores_and_clamping(name, low, mid, high):
    assert component_score(name, D(low)) == 0
    assert component_score(name, D(mid)) == 50
    assert component_score(name, D(high)) == 100
    direction = D(high) - D(low)
    assert component_score(name, D(low) - direction) == 0
    assert component_score(name, D(high) + direction) == 100


def test_weighted_score_uses_fixed_weights():
    # Breadth alone contributes 35 points; the four midpoint inputs add 32.5.
    result = evaluate_market_regime(inputs(breadth='.70'))
    assert result['score'] == D('67.5')
    assert result['regime'] == 'RISK_ON' and result['equity_exposure'] == 1
    assert sum(COMPONENT_WEIGHTS.values()) == 1


@pytest.mark.parametrize('score,regime,exposure', [
    ('0', 'RISK_OFF', '.25'), ('39.999', 'RISK_OFF', '.25'),
    ('40', 'NEUTRAL', '.75'), ('64.999', 'NEUTRAL', '.75'),
    ('65', 'RISK_ON', '1'), ('100', 'RISK_ON', '1'),
])
def test_decision_thresholds_are_inclusive(score, regime, exposure):
    # Keep every component at this same score to exercise exact final boundaries.
    values = {name: low + (high - low) * D(score) / 100
              for name, (low, high) in SCORE_ANCHORS.items()}
    result = evaluate_market_regime(inputs(**values))
    assert result['score'] == D(score)
    assert result['regime'] == regime
    assert result['equity_exposure'] == D(exposure)


@pytest.mark.parametrize('missing', COMPONENT_WEIGHTS)
def test_missing_input_prevents_decision_even_when_narrow_condition_exists(missing):
    data = inputs(breadth='.40', spy_trend='.02', rsp_spy='-.01')
    data[missing] = replace(data[missing], value=None)
    result = evaluate_market_regime(data)
    assert result['status'] == 'unavailable'
    assert result['missing_inputs'] == [missing]
    assert result['score'] is None and result['equity_exposure'] is None
    with pytest.raises(ValueError, match='unavailable'):
        apply_exposure({'AAA': D(1)}, result)


@pytest.mark.parametrize('name,value', [('breadth', 'NaN'), ('breadth', '1.01'),
    ('breadth', '-.01'), ('rsp_spy', 'Infinity'), ('vix_spot', '0')])
def test_invalid_input_fails_closed(name, value):
    assert evaluate_market_regime(inputs(**{name: value}))['missing_inputs'] == [name]


def test_narrow_market_has_priority_over_low_score():
    result = evaluate_market_regime(inputs(breadth='.20', spy_trend='.001', rsp_spy='-.10',
                                          hyg_lqd='-.10', vix_spot='40'))
    assert result['score'] < 40
    assert result['regime'] == 'NARROW_MARKET' and result['equity_exposure'] == D('.60')


@pytest.mark.parametrize('override', [{'breadth': '.50'}, {'spy_trend': '0'}, {'rsp_spy': '0'}])
def test_narrow_market_uses_strict_inequalities(override):
    values = dict(breadth='.40', spy_trend='.02', rsp_spy='-.01')
    values.update(override)
    assert evaluate_market_regime(inputs(**values))['regime'] != 'NARROW_MARKET'


def test_vix_penalty_affects_only_vix_component_and_at_most_2_5_total_points():
    unpenalized = evaluate_market_regime(inputs())
    penalized = evaluate_market_regime(inputs(), session=SESSION, vix_front_month=vx())
    assert penalized['component_scores']['vix_spot'] == 25
    assert penalized['vix_component_penalty'] == 25
    assert unpenalized['score'] - penalized['score'] == D('2.5')
    for name in COMPONENT_WEIGHTS:
        if name != 'vix_spot':
            assert penalized['component_scores'][name] == unpenalized['component_scores'][name]
    assert unpenalized['vix_front_month_status'] == 'unavailable'


def test_vix_penalty_cannot_make_component_negative_and_equality_is_unpenalized():
    stressed = evaluate_market_regime(inputs(vix_spot='29'), session=SESSION, vix_front_month=vx('28'))
    assert stressed['component_scores']['vix_spot'] == 0
    assert 0 < stressed['vix_component_penalty'] < 25
    equal = evaluate_market_regime(inputs(vix_spot='20'), session=SESSION, vix_front_month=vx('20'))
    assert equal['vix_component_penalty'] == 0


def test_vx_requires_exact_date_expiry_and_provenance():
    with pytest.raises(ValueError, match='exact regime session'):
        evaluate_market_regime(inputs(), session=SESSION + timedelta(days=1), vix_front_month=vx())
    with pytest.raises(ValueError, match='expired'):
        replace(vx(), expiry=SESSION)
    with pytest.raises(ValueError, match='contract identifier and source'):
        replace(vx(), source='')
    with pytest.raises(ValueError, match='finite and positive'):
        replace(vx(), close=D('NaN'))


@pytest.mark.parametrize('regime,exposure', EXPOSURES.items())
def test_overlay_keeps_selected_names_and_relative_allocations(regime, exposure):
    original = {'AAA': D('.50'), 'BBB': D('.30'), 'CCC': D('.20')}
    before = original.copy()
    result = apply_exposure(original, {'status': 'available', 'equity_exposure': exposure})
    assert original == before
    assert set(result['equity_weights']) == set(original)
    for symbol in original:
        assert result['equity_weights'][symbol] == original[symbol] * exposure
    assert sum(result['equity_weights'].values()) + result['cash_weight'] == 1


def test_overlay_rejects_non_normalized_targets_and_preserves_empty_cash_portfolio():
    decision = {'status': 'available', 'equity_exposure': D('.75')}
    with pytest.raises(ValueError, match='sum to one'):
        apply_exposure({'AAA': D('.50')}, decision)
    assert apply_exposure({}, decision) == {'equity_weights': {}, 'cash_weight': D(1)}


def test_evaluator_rejects_mixed_signal_sessions():
    data = inputs()
    data['rsp_spy'] = replace(data['rsp_spy'], period_end=SESSION - timedelta(days=1))
    result = evaluate_market_regime(data, session=SESSION)
    assert result['status'] == 'unavailable' and result['missing_inputs'] == ['rsp_spy']


def test_no_vix_penalty_when_front_month_is_above_spot():
    result = evaluate_market_regime(inputs(), session=SESSION, vix_front_month=vx('25'))
    assert result['score'] == 50 and result['vix_component_penalty'] == 0
