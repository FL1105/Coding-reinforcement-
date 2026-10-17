from backtester.validation import (
    require_finite_non_negative,
    require_finite_positive,
)


class Portfolio:
    def __init__(self, cash: float, shares: float = 0.0) -> None:
        self.cash = require_finite_non_negative("cash", cash)
        self.shares = require_finite_non_negative("shares", shares)

    def buy(self, price: float, cash_amount: float) -> None:
        price = require_finite_positive("price", price)
        cash_amount = require_finite_positive("amount", cash_amount)
        if cash_amount > self.cash:
            raise ValueError("insufficient cash")
        self.shares += cash_amount / price
        self.cash -= cash_amount

    def sell(self, price: float, shares: float) -> None:
        price = require_finite_positive("price", price)
        shares = require_finite_positive("amount", shares)
        if shares > self.shares:
            raise ValueError("insufficient shares")
        self.shares -= shares
        self.cash += shares * price

    def equity(self, price: float) -> float:
        price = require_finite_positive("price", price)
        return self.cash + self.shares * price
