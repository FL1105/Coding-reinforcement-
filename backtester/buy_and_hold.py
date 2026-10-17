from datetime import datetime

from backtester.data import Bar
from backtester.portfolio import Portfolio
from backtester.validation import require_finite_positive


def run_buy_and_hold(
    bars: list[Bar], starting_cash: float
) -> list[tuple[datetime, float]]:
    if not bars:
        raise ValueError("bars must not be empty")
    starting_cash = require_finite_positive("starting cash", starting_cash)

    portfolio = Portfolio(starting_cash)
    portfolio.buy(bars[0].close, portfolio.cash)
    return [(bar.timestamp, portfolio.equity(bar.close)) for bar in bars]
