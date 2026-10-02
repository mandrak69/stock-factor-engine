from __future__ import annotations

import calendar
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, localcontext
from zoneinfo import ZoneInfo

from stock_factor_engine.models.market import DailyPrice, total_return


@dataclass(frozen=True)
class Factor:
    value: Decimal | None
    formula: str
    period_start: date | None = None
    period_end: date | None = None
    observations: int = 0
    reason: str | None = None
    unit: str = 'ratio'
    details: dict | None = None

    def payload(self):
        result = asdict(self)
        result['status'] = 'available' if self.value is not None else 'unavailable'
        return result


def month_end_before(on_date: date) -> date:
    return on_date.replace(day=1) - timedelta(days=1)


def shift_month_end(on_date: date, months: int) -> date:
    serial = on_date.year * 12 + on_date.month - 1 + months
    year, zero_month = divmod(serial, 12)
    return date(year, zero_month + 1, calendar.monthrange(year, zero_month + 1)[1])


def _anchor(bars: list[DailyPrice], target: date):
    eligible = [bar for bar in bars if bar.trading_date <= target]
    if not eligible or (target - eligible[-1].trading_date).days > 7:
        raise ValueError(f'No sufficiently recent price for calendar anchor {target}')
    return eligible[-1]


def _window(bars, required=253):
    if len(bars) < required:
        raise ValueError(f'Need {required} completed-session prices')
    window = bars[-required:]
    if any(b.trading_date - a.trading_date > timedelta(days=7) for a, b in zip(window, window[1:])):
        raise ValueError('Price window contains a calendar gap longer than seven days')
    if not 330 <= (window[-1].trading_date - window[0].trading_date).days <= 400:
        raise ValueError('253-price window does not span approximately one trading year')
    return window


def _validate(bars):
    if len({bar.trading_date for bar in bars}) != len(bars):
        raise ValueError('Duplicate trading dates')
    if any(a.trading_date >= b.trading_date for a, b in zip(bars, bars[1:])):
        raise ValueError('Prices must be strictly chronological')


def price_factors(bars: list[DailyPrice], *, as_of: datetime):
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError('as_of must be timezone-aware')
    _validate(bars)
    local_date = as_of.astimezone(ZoneInfo('America/New_York')).date()
    bars = [bar for bar in bars if bar.trading_date < local_date]
    definitions = {
        'momentum_12_1': 'adjusted close at (month-end - 1 month) / adjusted close at (month-end - 12 months) - 1',
        'volatility_252': 'sample standard deviation of 252 simple daily adjusted returns * sqrt(252)',
        'max_drawdown_252': 'minimum adjusted close / running peak - 1 over 253 prices',
        'return_252': 'last adjusted close / first adjusted close - 1 over 253 prices',
    }
    if not bars or (local_date - bars[-1].trading_date).days > 7:
        return {name: Factor(None, formula, reason='No sufficiently recent completed-session price')
                for name, formula in definitions.items()}
    results = {}
    try:
        reference = month_end_before(local_date)
        start_target, end_target = shift_month_end(reference, -12), shift_month_end(reference, -1)
        start, end = _anchor(bars, start_target), _anchor(bars, end_target)
        used = [bar for bar in bars if start.trading_date <= bar.trading_date <= end.trading_date]
        if len(used) < 200 or any(b.trading_date - a.trading_date > timedelta(days=7) for a, b in zip(used, used[1:])):
            raise ValueError('Insufficient 12-1 coverage or long calendar gaps')
        results['momentum_12_1'] = Factor(total_return(start, end), definitions['momentum_12_1'],
                                          start.trading_date, end.trading_date, len(used), details={
                                              'reference_month_end': reference, 'start_calendar_anchor': start_target,
                                              'end_calendar_anchor': end_target,
                                              'start_adjusted_close': start.adjusted_close, 'end_adjusted_close': end.adjusted_close})
    except ValueError as error:
        results['momentum_12_1'] = Factor(None, definitions['momentum_12_1'], reason=str(error))
    try:
        window = _window(bars)
        returns = [total_return(a, b) for a, b in zip(window, window[1:])]
        with localcontext() as context:
            context.prec = 34
            mean = sum(returns, Decimal(0)) / len(returns)
            variance = sum(((value - mean) ** 2 for value in returns), Decimal(0)) / (len(returns) - 1)
            volatility = variance.sqrt() * Decimal(252).sqrt()
            peak = window[0].adjusted_close
            peak_date = window[0].trading_date
            minimum = Decimal(0)
            drawdown_peak = trough = peak_date
            for bar in window:
                if bar.adjusted_close > peak:
                    peak, peak_date = bar.adjusted_close, bar.trading_date
                decline = bar.adjusted_close / peak - 1
                if decline < minimum:
                    minimum, drawdown_peak, trough = decline, peak_date, bar.trading_date
        results['volatility_252'] = Factor(volatility, definitions['volatility_252'],
                                           window[0].trading_date, window[-1].trading_date, len(returns))
        results['max_drawdown_252'] = Factor(minimum, definitions['max_drawdown_252'],
                                             window[0].trading_date, window[-1].trading_date, len(window),
                                             details={'peak_date': drawdown_peak, 'trough_date': trough})
        results['return_252'] = Factor(total_return(window[0], window[-1]), definitions['return_252'],
                                      window[0].trading_date, window[-1].trading_date, len(window))
    except ValueError as error:
        for name in ('volatility_252', 'max_drawdown_252', 'return_252'):
            results[name] = Factor(None, definitions[name], reason=str(error))
    return results


def benchmark_comparison(asset, benchmark, *, as_of: datetime):
    """Require exact date alignment; never conceal missing days through an inner join."""
    _validate(asset)
    _validate(benchmark)
    local_date = as_of.astimezone(ZoneInfo('America/New_York')).date()
    asset, benchmark = ([bar for bar in series if bar.trading_date < local_date] for series in (asset, benchmark))
    asset_results, benchmark_results = price_factors(asset, as_of=as_of), price_factors(benchmark, as_of=as_of)
    results = {}
    for name in ('return_252', 'momentum_12_1'):
        a, b = asset_results[name], benchmark_results[name]
        reason = None
        if a.value is None or b.value is None:
            reason = 'Asset or benchmark factor unavailable'
        elif (a.period_start, a.period_end) != (b.period_start, b.period_end):
            reason = 'Asset and benchmark period boundaries differ'
        else:
            dates_a = {bar.trading_date for bar in asset if a.period_start <= bar.trading_date <= a.period_end}
            dates_b = {bar.trading_date for bar in benchmark if b.period_start <= bar.trading_date <= b.period_end}
            if dates_a != dates_b:
                reason = 'Asset and benchmark trading dates differ; missing observations are not dropped'
        with localcontext() as context:
            context.prec = 34
            difference = None if reason else a.value - b.value
        results[name + '_excess'] = Factor(difference,
                                         'asset return - SPY return (percentage-point difference)',
                                         a.period_start, a.period_end, a.observations, reason,
                                         details={'asset': a.value, 'benchmark': b.value})
    return asset_results, benchmark_results, results
