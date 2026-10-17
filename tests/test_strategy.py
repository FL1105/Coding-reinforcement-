from datetime import datetime

import pytest

from backtester.data import Bar
from backtester.strategy import SmaCrossover, run_backtest, sma

# Closes chosen so the 2/3 crossover is hand-checkable:
#   index 2 short (10+16)/2 = 13 > long (10+10+16)/3 = 12 -> long
#   index 3 short (16+2)/2 = 9 < long (10+16+2)/3 = 28/3 -> flat
#   index 4 short (2+20)/2 = 11 < long (16+2+20)/3 = 38/3 -> flat
_CROSSES = [10.0, 10.0, 16.0, 2.0, 20.0]


def test_sma_matches_hand_computed_values():
    closes = _CROSSES
    assert sma(closes[:2], 2) == pytest.approx(10.0)  # (10 + 10) / 2
    assert sma(closes[:3], 2) == pytest.approx(13.0)  # (10 + 16) / 2
    assert sma(closes[:3], 3) == pytest.approx(12.0)  # (10 + 10 + 16) / 3
    assert sma(closes[:4], 2) == pytest.approx(9.0)  # (16 + 2) / 2
    assert sma(closes[:4], 3) == pytest.approx(28 / 3)  # (10 + 16 + 2) / 3
    assert sma(closes, 2) == pytest.approx(11.0)  # (2 + 20) / 2
    assert sma(closes, 3) == pytest.approx(38 / 3)  # (16 + 2 + 20) / 3
    with pytest.raises(ValueError, match="not enough closes"):
        sma(closes[:2], 3)


def test_no_trade_before_long_window_is_full():
    # At the third bar the short SMA is (2+8)/2 = 5, above the mean of the
    # bars so far, (2+2+8)/3 = 4. The long window is still short one bar.
    bars = _bars([2.0, 2.0, 8.0, 1.0])
    strategy = SmaCrossover(short_window=2, long_window=4)
    cash = 50.0

    assert [strategy.target_position(bars[: index + 1]) for index in range(3)] == [
        0.0,
        0.0,
        0.0,
    ]
    assert strategy.target_position(bars) == 1.0

    curve = run_backtest(bars[:3], cash, SmaCrossover(2, 4))
    assert [v for _, v in curve] == pytest.approx([cash, cash, cash])


def test_crossover_buys_then_sells_on_the_expected_bars():
    bars = _bars(_CROSSES)
    strategy = SmaCrossover(short_window=2, long_window=3)
    cash = 160.0

    assert [
        strategy.target_position(bars[: index + 1]) for index in range(len(bars))
    ] == [
        0.0,
        0.0,
        1.0,
        0.0,
        0.0,
    ]

    curve = run_backtest(bars, cash, strategy)
    assert [t for t, _ in curve] == [bar.timestamp for bar in bars]
    # Buy at index 2's close (16): 160/16 = 10 shares. Sell at index 3's close (2).
    assert [v for _, v in curve] == pytest.approx([160.0, 160.0, 160.0, 20.0, 20.0])


def test_signal_includes_bar_close_and_fills_at_that_close():
    bars = _bars(_CROSSES)
    # Opens differ from the signal closes. A fill at those opens would mark
    # 320 on entry (160/8*16) and 100 on exit (10 shares * 10).
    bars[2] = _with_prices(bars[2], open=8.0, high=16.0, low=8.0, close=16.0)
    bars[3] = _with_prices(bars[3], open=10.0, high=10.0, low=2.0, close=2.0)
    flat = _bars([10.0, 10.0, 10.0])
    strategy = SmaCrossover(2, 3)

    # Close 16 crosses; close 10 makes both SMAs 10, which stays flat.
    assert strategy.target_position(bars[:3]) == 1.0
    assert strategy.target_position(flat) == 0.0

    curve = run_backtest(bars, 160.0, SmaCrossover(2, 3))
    assert [v for _, v in curve] == pytest.approx([160.0, 160.0, 160.0, 20.0, 20.0])


def test_future_close_does_not_change_earlier_signal_or_equity():
    bars = _bars([5.0, 4.0, 7.0, 8.0, 9.0])
    cash = 100.0
    curve = run_backtest(bars, cash, SmaCrossover(2, 3))
    signals = _signals(bars)
    assert signals == [0.0, 0.0, 1.0, 1.0, 1.0]

    for index in range(len(bars) - 1):
        altered = list(bars)
        for later in range(index + 1, len(bars)):
            altered[later] = _with_close(bars[later], close=50.0 + later)
        altered_curve = run_backtest(altered, cash, SmaCrossover(2, 3))
        altered_signals = _signals(altered)
        assert altered_signals[: index + 1] == signals[: index + 1]
        assert [t for t, _ in altered_curve[: index + 1]] == [
            t for t, _ in curve[: index + 1]
        ]
        assert [v for _, v in altered_curve[: index + 1]] == pytest.approx(
            [v for _, v in curve[: index + 1]]
        )
        assert altered_curve[-1][1] != pytest.approx(curve[-1][1])


@pytest.mark.parametrize(
    ("short_window", "long_window", "message"),
    [
        (float("nan"), 3, "short window must be positive"),
        (float("inf"), 3, "short window must be positive"),
        (float("-inf"), 3, "short window must be positive"),
        (0, 3, "short window must be positive"),
        (-2, 3, "short window must be positive"),
        (2, float("nan"), "long window must be positive"),
        (2, float("inf"), "long window must be positive"),
        (2, float("-inf"), "long window must be positive"),
        (2, 0, "long window must be positive"),
        (2, -1, "long window must be positive"),
        (True, 3, "short window must be an integer"),
        (False, 3, "short window must be an integer"),
        (2, True, "long window must be an integer"),
        (2, False, "long window must be an integer"),
        (2.0, 3, "short window must be an integer"),
        (2, 3.0, "long window must be an integer"),
        (3, 3, "short window must be less than long window"),
        (4, 2, "short window must be less than long window"),
    ],
)
def test_sma_crossover_rejects_bad_windows(short_window, long_window, message):
    with pytest.raises(ValueError, match=message):
        SmaCrossover(short_window=short_window, long_window=long_window)


@pytest.mark.parametrize(
    "close", [float("nan"), float("inf"), float("-inf"), 0.0, -1.0]
)
def test_sma_rejects_non_positive_close(close):
    bars = _bars([1.0, 1.0, 1.0])
    bars[1] = _with_close(bars[1], close)
    with pytest.raises(ValueError, match="close must be positive"):
        SmaCrossover(2, 3).target_position(bars)


def _bars(closes: list[float]) -> list[Bar]:
    return [
        Bar(
            timestamp=datetime(2024, 1, index + 1),
            open=close,
            high=close,
            low=close,
            close=close,
            volume=1.0,
        )
        for index, close in enumerate(closes)
    ]


def _with_close(bar: Bar, close: float) -> Bar:
    return _with_prices(bar, open=close, high=close, low=close, close=close)


def _with_prices(
    bar: Bar, *, open: float, high: float, low: float, close: float
) -> Bar:
    return Bar(
        timestamp=bar.timestamp,
        open=open,
        high=high,
        low=low,
        close=close,
        volume=bar.volume,
    )


def _signals(bars: list[Bar]) -> list[float]:
    strategy = SmaCrossover(2, 3)
    return [strategy.target_position(bars[: index + 1]) for index in range(len(bars))]
