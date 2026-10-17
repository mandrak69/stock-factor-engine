"""SQLite integration; never substitute the curated present-day universe."""
from stock_factor_engine.storage.research import price_context
from stock_factor_engine.universe.registry import IDENTITIES, MARKET_SYMBOLS
from .inputs import regime_inputs
from .model import COMPONENT_WEIGHTS, EXPOSURES, evaluate_market_regime, narrow_market


def regime_report(connection, *, as_of, membership_provider=None, vix_front_month=None):
    series, snapshots, errors = {}, {}, {}
    for symbol in MARKET_SYMBOLS:
        try:
            meta, bars, _, _ = price_context(connection, security_id=IDENTITIES[symbol]['security_id'], as_of=as_of)
            series[symbol], snapshots[symbol] = bars, meta
        except ValueError as error:
            series[symbol], errors[symbol] = [], str(error)
    session, inputs = regime_inputs(series, as_of=as_of)
    membership = None
    member_snapshots = {}
    if membership_provider is not None and session is not None:
        try:
            membership = membership_provider.members_on(session)
            member_prices = {}
            if membership is not None and membership.session == session and membership.complete:
                for security_id in sorted(membership.security_ids):
                    try:
                        meta, bars, _, _ = price_context(connection, security_id=security_id, as_of=as_of)
                        member_prices[security_id], member_snapshots[security_id] = bars, meta
                    except ValueError as error:
                        errors[security_id] = str(error)
            session, inputs = regime_inputs(series, as_of=as_of, membership=membership, member_prices=member_prices)
        except ValueError as error:
            errors['membership'] = str(error)
    result = evaluate_market_regime(inputs, session=session, vix_front_month=vix_front_month)
    result.update(as_of=as_of.isoformat(), session=session,
                  inputs={key: value.payload() for key, value in inputs.items()},
                  component_weights=dict(COMPONENT_WEIGHTS), exposures=dict(EXPOSURES),
                  snapshots=snapshots, member_snapshots=member_snapshots, errors=errors,
                  membership_source=membership.source if membership is not None else None)
    if vix_front_month is not None:
        result['vix_front_month'] = {'session': vix_front_month.session, 'close': vix_front_month.close,
                                     'contract': vix_front_month.contract, 'expiry': vix_front_month.expiry,
                                     'source': vix_front_month.source}
    return result
