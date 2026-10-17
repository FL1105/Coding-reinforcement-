class Portfolio:
    def __init__(self, cash: float, shares: float = 0.0) -> None:
        self.cash = cash
        self.shares = shares

    def buy(self, price: float, cash_amount: float) -> None:
        _require_positive(price, "price")
        _require_positive(cash_amount, "amount")
        if cash_amount > self.cash:
            raise ValueError("insufficient cash")
        self.shares += cash_amount / price
        self.cash -= cash_amount

    def sell(self, price: float, shares: float) -> None:
        _require_positive(price, "price")
        _require_positive(shares, "amount")
        if shares > self.shares:
            raise ValueError("insufficient shares")
        self.shares -= shares
        self.cash += shares * price

    def equity(self, price: float) -> float:
        _require_positive(price, "price")
        return self.cash + self.shares * price


def _require_positive(value: float, name: str) -> None:
    if value <= 0:
        raise ValueError(f"{name} must be positive")
