import pytest

from backtester.portfolio import Portfolio


def test_buy_converts_cash_into_fractional_shares():
    portfolio = Portfolio(cash=100.0, shares=0.0)
    portfolio.buy(price=8.5, cash_amount=85.0)
    assert portfolio.cash == pytest.approx(15.0)
    assert portfolio.shares == pytest.approx(10.0)
    assert portfolio.equity(8.5) == pytest.approx(100.0)
    assert portfolio.equity(10.0) == pytest.approx(115.0)


def test_buy_can_spend_all_cash():
    portfolio = Portfolio(cash=50.0, shares=2.0)
    portfolio.buy(price=4.0, cash_amount=50.0)
    assert portfolio.cash == pytest.approx(0.0)
    assert portfolio.shares == pytest.approx(14.5)
    assert portfolio.equity(4.0) == pytest.approx(58.0)


def test_sell_converts_shares_into_cash():
    portfolio = Portfolio(cash=15.0, shares=10.0)
    portfolio.sell(price=11.0, shares=4.0)
    assert portfolio.shares == pytest.approx(6.0)
    assert portfolio.cash == pytest.approx(59.0)
    assert portfolio.equity(11.0) == pytest.approx(125.0)


def test_sell_can_close_the_whole_position():
    portfolio = Portfolio(cash=0.0, shares=10.0)
    portfolio.sell(price=6.0, shares=10.0)
    assert portfolio.shares == pytest.approx(0.0)
    assert portfolio.cash == pytest.approx(60.0)
    assert portfolio.equity(6.0) == pytest.approx(60.0)


@pytest.mark.parametrize("cash", [float("nan"), float("inf"), float("-inf"), -1.0])
def test_portfolio_rejects_non_finite_or_negative_cash(cash):
    with pytest.raises(ValueError, match="cash must be non-negative"):
        Portfolio(cash=cash, shares=10.0)


@pytest.mark.parametrize(
    "shares", [float("nan"), float("inf"), float("-inf"), -1.0]
)
def test_portfolio_rejects_non_finite_or_negative_shares(shares):
    with pytest.raises(ValueError, match="shares must be non-negative"):
        Portfolio(cash=1.0, shares=shares)


def test_buy_rejects_more_cash_than_available():
    portfolio = Portfolio(cash=10.0, shares=1.0)
    with pytest.raises(ValueError, match="insufficient cash"):
        portfolio.buy(price=2.0, cash_amount=10.01)
    assert portfolio.cash == pytest.approx(10.0)
    assert portfolio.shares == pytest.approx(1.0)


def test_sell_rejects_more_shares_than_held():
    portfolio = Portfolio(cash=10.0, shares=1.0)
    with pytest.raises(ValueError, match="insufficient shares"):
        portfolio.sell(price=2.0, shares=1.01)
    assert portfolio.cash == pytest.approx(10.0)
    assert portfolio.shares == pytest.approx(1.0)


@pytest.mark.parametrize(
    "price", [float("nan"), float("inf"), float("-inf"), 0.0, -1.0]
)
def test_buy_rejects_non_positive_price(price):
    portfolio = Portfolio(cash=10.0, shares=1.0)
    with pytest.raises(ValueError, match="price must be positive"):
        portfolio.buy(price=price, cash_amount=5.0)
    assert portfolio.cash == pytest.approx(10.0)
    assert portfolio.shares == pytest.approx(1.0)


@pytest.mark.parametrize("amount", [0.0, -1.0])
def test_buy_rejects_non_positive_amount(amount):
    portfolio = Portfolio(cash=10.0, shares=1.0)
    with pytest.raises(ValueError, match="amount must be positive"):
        portfolio.buy(price=2.0, cash_amount=amount)
    assert portfolio.cash == pytest.approx(10.0)
    assert portfolio.shares == pytest.approx(1.0)


@pytest.mark.parametrize(
    "price", [float("nan"), float("inf"), float("-inf"), 0.0, -1.0]
)
def test_sell_rejects_non_positive_price(price):
    portfolio = Portfolio(cash=10.0, shares=1.0)
    with pytest.raises(ValueError, match="price must be positive"):
        portfolio.sell(price=price, shares=0.5)
    assert portfolio.cash == pytest.approx(10.0)
    assert portfolio.shares == pytest.approx(1.0)


@pytest.mark.parametrize("shares", [0.0, -1.0])
def test_sell_rejects_non_positive_amount(shares):
    portfolio = Portfolio(cash=10.0, shares=1.0)
    with pytest.raises(ValueError, match="amount must be positive"):
        portfolio.sell(price=2.0, shares=shares)
    assert portfolio.cash == pytest.approx(10.0)
    assert portfolio.shares == pytest.approx(1.0)


@pytest.mark.parametrize(
    "price", [float("nan"), float("inf"), float("-inf"), 0.0, -1.0]
)
def test_equity_rejects_non_positive_price(price):
    portfolio = Portfolio(cash=10.0, shares=1.0)
    with pytest.raises(ValueError, match="price must be positive"):
        portfolio.equity(price)
    assert portfolio.cash == pytest.approx(10.0)
    assert portfolio.shares == pytest.approx(1.0)
