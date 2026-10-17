from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from backtester.data import Bar
from backtester.portfolio import Portfolio
from backtester.validation import require_finite_positive


class Strategy(Protocol):
    def target_position(self, history: Sequence[Bar]) -> float:
        """Target weight for the latest bar: 1.0 fully long, or 0.0 flat."""

        ...


def run_backtest(
    bars: list[Bar], starting_cash: float, strategy: Strategy
) -> list[tuple[datetime, float]]:
    """Fill each target at that bar's close and mark equity at the same close.

    The strategy sees bars up through the bar being filled, including its close.
    """
    if not bars:
        raise ValueError("bars must not be empty")
    starting_cash = require_finite_positive("starting cash", starting_cash)

    portfolio = Portfolio(starting_cash)
    curve: list[tuple[datetime, float]] = []
    for index, bar in enumerate(bars):
        target = strategy.target_position(bars[: index + 1])
        _fill_target(portfolio, bar.close, target)
        curve.append((bar.timestamp, portfolio.equity(bar.close)))
    return curve


class SmaCrossover:
    """Long when the short SMA is above the long SMA, otherwise flat.

    The average on bar t uses closes up through t and nothing after. There is
    no position until both windows are full. The backtest fills the target at
    bar t's close.
    """

    def __init__(self, short_window: int, long_window: int) -> None:
        self.short_window = _require_window("short window", short_window)
        self.long_window = _require_window("long window", long_window)
        if self.short_window >= self.long_window:
            raise ValueError("short window must be less than long window")

    def target_position(self, history: Sequence[Bar]) -> float:
        if len(history) < self.long_window:
            return 0.0
        closes = [bar.close for bar in history]
        short_average = sma(closes, self.short_window)
        long_average = sma(closes, self.long_window)
        if short_average > long_average:
            return 1.0
        return 0.0


def sma(closes: Sequence[float], window: int) -> float:
    if len(closes) < window:
        raise ValueError("not enough closes")
    total = 0.0
    for close in closes[-window:]:
        total += require_finite_positive("close", close)
    return total / window


def _require_window(name: str, value: object) -> int:
    if isinstance(value, float):
        require_finite_positive(name, value)
    # bool subclasses int, so isinstance(..., int) would accept True and False.
    if type(value) is not int:
        raise ValueError(f"{name} must be an integer")
    require_finite_positive(name, value)
    return value


def _fill_target(portfolio: Portfolio, price: float, target: float) -> None:
    if target == 1.0:
        if portfolio.cash > 0:
            portfolio.buy(price, portfolio.cash)
        return
    if target == 0.0:
        if portfolio.shares > 0:
            portfolio.sell(price, portfolio.shares)
        return
    raise ValueError("target position must be 0 or 1")
