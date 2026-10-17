"""Frozen project hypotheses approved 2026-10-17; no stock ranking dependencies."""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from types import MappingProxyType


D = Decimal
SPEC_VERSION = 'market-regime-v0.1-approved-2026-10-17'
COMPONENT_WEIGHTS = MappingProxyType({
    'breadth': D('.35'), 'rsp_spy': D('.25'), 'spy_trend': D('.20'),
    'vix_spot': D('.10'), 'hyg_lqd': D('.10'),
})
# (input receiving score 0, input receiving score 100), linear and clamped.
SCORE_ANCHORS = MappingProxyType({
    'breadth': (D('.30'), D('.70')), 'rsp_spy': (D('-.05'), D('.05')),
    'spy_trend': (D('-.10'), D('.10')), 'vix_spot': (D('30'), D('15')),
    'hyg_lqd': (D('-.03'), D('.03')),
})
EXPOSURES = MappingProxyType({
    'RISK_ON': D('1.00'), 'NEUTRAL': D('.75'),
    'NARROW_MARKET': D('.60'), 'RISK_OFF': D('.25'),
})
RISK_ON_THRESHOLD = D(65)
NEUTRAL_THRESHOLD = D(40)
VIX_COMPONENT_PENALTY = D(25)


@dataclass(frozen=True)
class VixFrontMonth:
    session: date
    close: Decimal
    contract: str
    expiry: date
    source: str

    def __post_init__(self):
        if not self.close.is_finite() or self.close <= 0:
            raise ValueError('VX close must be finite and positive')
        if not self.contract.strip() or not self.source.strip():
            raise ValueError('VX requires a real contract identifier and source')
        if self.expiry <= self.session:
            raise ValueError('VX contract must not have expired on the observation session')


def component_score(name, value):
    low, high = SCORE_ANCHORS[name]
    return max(D(0), min(D(100), (value - low) / (high - low) * 100))


def narrow_market(inputs):
    keys = ('spy_trend', 'breadth', 'rsp_spy')
    values = {key: inputs.get(key).value if inputs.get(key) is not None else None for key in keys}
    if any(value is None or not value.is_finite() for value in values.values()):
        return None
    return values['spy_trend'] > 0 and values['breadth'] < D('.50') and values['rsp_spy'] < 0


def evaluate_market_regime(inputs, *, session=None, vix_front_month=None):
    missing = []
    for name in COMPONENT_WEIGHTS:
        factor = inputs.get(name)
        value = factor.value if factor is not None else None
        if (value is None or not value.is_finite()
                or (name == 'breadth' and not D(0) <= value <= D(1))
                or (name == 'vix_spot' and value <= 0)
                or (session is not None and factor.period_end != session)):
            missing.append(name)
    result = {'spec_version': SPEC_VERSION, 'status': 'unavailable', 'regime': None,
              'equity_exposure': None, 'score': None, 'missing_inputs': missing,
              'component_scores': {}, 'vix_component_penalty': D(0),
              'vix_front_month_status': 'unavailable', 'narrow_market_condition': None}
    if vix_front_month is not None:
        if session != vix_front_month.session:
            raise ValueError('VX front-month observation must match the exact regime session')
        result['vix_front_month_status'] = 'available'
    if missing:
        result['reason'] = 'Required inputs unavailable; weights are not redistributed'
        return result
    scores = {name: component_score(name, inputs[name].value) for name in COMPONENT_WEIGHTS}
    if vix_front_month is not None and inputs['vix_spot'].value > vix_front_month.close:
        penalized = max(D(0), scores['vix_spot'] - VIX_COMPONENT_PENALTY)
        result['vix_component_penalty'] = scores['vix_spot'] - penalized
        scores['vix_spot'] = penalized
    total = sum((scores[name] * weight for name, weight in COMPONENT_WEIGHTS.items()), D(0))
    narrow = narrow_market(inputs)
    if narrow:
        regime = 'NARROW_MARKET'
    elif total >= RISK_ON_THRESHOLD:
        regime = 'RISK_ON'
    elif total >= NEUTRAL_THRESHOLD:
        regime = 'NEUTRAL'
    else:
        regime = 'RISK_OFF'
    result.update(status='available', regime=regime, equity_exposure=EXPOSURES[regime],
                  score=total, component_scores=scores, narrow_market_condition=narrow, reason=None)
    return result


def apply_exposure(weights, decision):
    """Scale existing normalized stock targets only; cash receives the remainder.

    A caller must pass the decision from the signal session and execute no
    earlier than the next session open. Unavailable decisions stop execution.
    """
    if decision['status'] != 'available':
        raise ValueError('Cannot construct targets from an unavailable regime')
    exposure = decision['equity_exposure']
    if not exposure.is_finite() or not D(0) <= exposure <= D(1):
        raise ValueError('Invalid equity exposure')
    if any(not weight.is_finite() or weight < 0 for weight in weights.values()):
        raise ValueError('Stock weights must be finite and nonnegative')
    if not weights:
        return {'equity_weights': {}, 'cash_weight': D(1)}
    if sum(weights.values(), D(0)) != 1:
        raise ValueError('Stock selection weights must sum to one')
    scaled = {}
    running = D(0)
    items = list(weights.items())
    for symbol, weight in items[:-1]:
        scaled[symbol] = weight * exposure
        running += scaled[symbol]
    scaled[items[-1][0]] = exposure - running
    return {'equity_weights': scaled, 'cash_weight': D(1) - exposure}
