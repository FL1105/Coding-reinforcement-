from datetime import datetime
from pathlib import Path

import pytest

from backtester.buy_and_hold import run_buy_and_hold
from backtester.data import Bar, load_bars_csv

FIXTURE = Path(__file__).parent / "fixtures" / "bars.csv"


def test_buy_and_hold_equity_curve_from_fixture():
    bars = load_bars_csv(FIXTURE)
    starting_cash = 850.0
    curve = run_buy_and_hold(bars, starting_cash)
    assert [t for t, _ in curve] == [
        datetime.fromisoformat("2024-01-01T00:00:00"),
        datetime.fromisoformat("2024-01-02T00:00:00"),
        datetime.fromisoformat("2024-01-03T00:00:00"),
        datetime.fromisoformat("2024-01-04T00:00:00"),
        datetime.fromisoformat("2024-01-05T00:00:00"),
    ]
    assert [v for _, v in curve] == pytest.approx(
        [850.0, 1000.0, 1100.0, 600.0, 400.0]
    )
    assert curve[-1][1] == pytest.approx(
        starting_cash * bars[-1].close / bars[0].close
    )


def test_run_buy_and_hold_rejects_empty_bars():
    with pytest.raises(ValueError, match="bars must not be empty"):
        run_buy_and_hold([], 100.0)


@pytest.mark.parametrize(
    "starting_cash", [float("nan"), float("inf"), float("-inf"), 0.0, -1.0]
)
def test_run_buy_and_hold_rejects_non_positive_starting_cash(starting_cash):
    bars = load_bars_csv(FIXTURE)
    with pytest.raises(ValueError, match="starting cash must be positive"):
        run_buy_and_hold(bars, starting_cash)


def test_each_curve_point_ignores_later_bars():
    bars = load_bars_csv(FIXTURE)
    starting_cash = 850.0
    curve = run_buy_and_hold(bars, starting_cash)
    for index in range(len(bars) - 1):
        altered = list(bars)
        for later in range(index + 1, len(bars)):
            altered[later] = _with_close(bars[later], close=100.0 + later)
        altered_curve = run_buy_and_hold(altered, starting_cash)
        expected = curve[: index + 1]
        actual = altered_curve[: index + 1]
        assert [t for t, _ in actual] == [t for t, _ in expected]
        assert [v for _, v in actual] == pytest.approx([v for _, v in expected])
        assert altered_curve[-1][1] != pytest.approx(curve[-1][1])


def _with_close(bar: Bar, close: float) -> Bar:
    return Bar(
        timestamp=bar.timestamp,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=bar.volume,
    )
