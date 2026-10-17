from datetime import datetime

from backtester.data import Bar
from backtester.strategy import run_backtest


class BuyAndHold:
    """Always fully long, so the runner buys on the first close."""

    def target_position(self, history: list[Bar]) -> float:
        return 1.0


def run_buy_and_hold(
    bars: list[Bar], starting_cash: float
) -> list[tuple[datetime, float]]:
    return run_backtest(bars, starting_cash, BuyAndHold())
