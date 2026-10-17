"""Integration v0.2: exact-session inputs with fail-closed breadth.

The completion convention matches the existing SQLite price adapter: a session
becomes usable at the following New York midnight, never during that session.
"""
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Mapping, Protocol
from zoneinfo import ZoneInfo

from stock_factor_engine.factors.prices import Factor, _validate
from stock_factor_engine.models.market import DailyPrice


@dataclass(frozen=True)
class Membership:
    session: date
    security_ids: frozenset[str]
    source: str
    complete: bool


class MembershipProvider(Protocol):
    def members_on(self, session: date) -> Membership | None: ...


def completed(bars, as_of):
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError('as_of must be timezone-aware')
    _validate(bars)
    cutoff = as_of.astimezone(ZoneInfo('America/New_York')).date()
    return [bar for bar in bars if bar.trading_date < cutoff]


def window(bars, session, count, expected_dates=None):
    _validate(bars)
    selected = [bar for bar in bars if bar.trading_date <= session][-count:]
    if len(selected) != count or selected[-1].trading_date != session:
        raise ValueError(f'Need {count} observations ending exactly on {session}')
    dates = tuple(bar.trading_date for bar in selected)
    if expected_dates is not None and dates != tuple(expected_dates):
        raise ValueError('Trading dates differ; missing sessions cannot be dropped')
    if any(b - a > timedelta(days=7) for a, b in zip(dates, dates[1:])):
        raise ValueError('Price window contains a calendar gap longer than seven days')
    return selected


def relative_return(asset, benchmark, session, expected_dates):
    formula = '(asset adjusted end / start) / (benchmark adjusted end / start) - 1; 63 sessions'
    try:
        a = window(asset, session, 64, expected_dates)
        b = window(benchmark, session, 64, expected_dates)
        value = (a[-1].adjusted_close / a[0].adjusted_close) / (b[-1].adjusted_close / b[0].adjusted_close) - 1
        return Factor(value, formula, a[0].trading_date, session, 64)
    except ValueError as error:
        return Factor(None, formula, reason=str(error))


def trend_200(bars, session, expected_dates):
    formula = 'latest adjusted close / 200-session adjusted-close SMA - 1'
    try:
        used = window(bars, session, 200, expected_dates)
        sma = sum((bar.adjusted_close for bar in used), Decimal(0)) / 200
        return Factor(used[-1].adjusted_close / sma - 1, formula, used[0].trading_date, session, 200)
    except ValueError as error:
        return Factor(None, formula, reason=str(error))


def breadth(member_prices: Mapping[str, list[DailyPrice]], membership, session, expected_dates):
    formula = 'fraction of exact-date point-in-time S&P 500 members above their adjusted-close 200DMA'
    if (membership is None or membership.session != session or not membership.complete
            or not membership.source.strip() or not membership.security_ids):
        return Factor(None, formula, reason='Verified complete point-in-time membership unavailable for exact session')
    missing = []
    above = 0
    for security_id in sorted(membership.security_ids):
        result = trend_200(member_prices.get(security_id, []), session, expected_dates)
        if result.value is None:
            missing.append(security_id)
        elif result.value > 0:
            above += 1
    details = {'membership_source': membership.source, 'members': len(membership.security_ids), 'missing': missing}
    if missing:
        return Factor(None, formula, reason='At least one member has incomplete prices; partial breadth forbidden', details=details)
    return Factor(Decimal(above) / len(membership.security_ids), formula, expected_dates[0], session,
                  len(membership.security_ids), details=details)


def regime_inputs(series, *, as_of, membership=None, member_prices=None):
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError('as_of must be timezone-aware')
    series = {symbol: completed(bars, as_of) for symbol, bars in series.items()}
    spy = series.get('SPY', [])
    cutoff = as_of.astimezone(ZoneInfo('America/New_York')).date()
    definitions = ('breadth', 'rsp_spy', 'spy_trend', 'vix_spot', 'hyg_lqd')
    if not spy or cutoff - spy[-1].trading_date > timedelta(days=7):
        return None, {key: Factor(None, key, reason='No recent completed SPY reference session') for key in definitions}
    session = spy[-1].trading_date
    dates_200 = tuple(bar.trading_date for bar in spy[-200:])
    dates_64 = tuple(bar.trading_date for bar in spy[-64:])
    values = {
        'spy_trend': trend_200(spy, session, dates_200),
        'rsp_spy': relative_return(series.get('RSP', []), spy, session, dates_64),
        'hyg_lqd': relative_return(series.get('HYG', []), series.get('LQD', []), session, dates_64),
        'breadth': breadth(member_prices or {}, membership, session, dates_200),
    }
    try:
        vix = window(series.get('^VIX', []), session, 1)[-1]
        values['vix_spot'] = Factor(vix.close, 'VIX spot raw close', session, session, 1, unit='index_points')
    except ValueError as error:
        values['vix_spot'] = Factor(None, 'VIX spot raw close', reason=str(error), unit='index_points')
    return session, values
