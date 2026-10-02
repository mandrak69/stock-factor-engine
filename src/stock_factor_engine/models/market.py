from dataclasses import dataclass
from datetime import date
from decimal import Decimal, localcontext


@dataclass(frozen=True)
class DailyPrice:
    trading_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    adjusted_close: Decimal
    volume: int

    def __post_init__(self):
        for value in (self.open, self.high, self.low, self.close, self.adjusted_close):
            if not value.is_finite() or value <= 0:
                raise ValueError('Prices must be finite and positive')
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close) or self.low > self.high:
            raise ValueError('Inconsistent OHLC range')
        if isinstance(self.volume, bool) or not isinstance(self.volume, int) or self.volume < 0:
            raise ValueError('Volume must be a nonnegative integer')


@dataclass(frozen=True)
class CorporateAction:
    event_date: date
    kind: str
    value: Decimal

    def __post_init__(self):
        if self.kind not in ('dividend', 'split'):
            raise ValueError('Unsupported corporate action')
        if not self.value.is_finite() or self.value <= 0:
            raise ValueError('Corporate-action value must be positive')


def total_return(previous: DailyPrice, current: DailyPrice) -> Decimal:
    """Provider-adjusted return; dividends and splits must not be applied again."""
    if current.trading_date <= previous.trading_date:
        raise ValueError('Prices must be ordered by trading date')
    with localcontext() as context:
        context.prec = 34
        return current.adjusted_close / previous.adjusted_close - 1
