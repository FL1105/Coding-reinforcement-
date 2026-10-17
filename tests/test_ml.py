import csv
import math
from datetime import datetime, timedelta

import numpy as np
import pytest

from backtester.data import Bar
from backtester.ml.features import build_features
from backtester.ml.report import main
from backtester.ml.walk_forward import walk_forward


def test_lagged_log_returns_and_next_day_label():
    closes = [10.0, 10.0, 20.0, 20.0, 40.0]
    volumes = [1.0, 1.0, 3.0, 3.0, 8.0]
    X, y = build_features(_bars(closes, volumes), lags=2)

    assert X.shape == (2, 3)
    assert X[0] == pytest.approx([math.log(2.0), 0.0, 2.0])
    assert X[1] == pytest.approx([0.0, math.log(2.0), 0.0])
    assert y.tolist() == [0, 1]


def test_short_history_drops_every_row():
    X, y = build_features(_bars([10.0, 11.0, 12.0], [1.0, 1.0, 1.0]), lags=5)
    assert X.shape == (0, 6)
    assert y.shape == (0,)


def test_future_bar_does_not_change_feature_row():
    lags = 3
    closes = [10.0 + i for i in range(12)]
    volumes = [100.0 + 3 * i for i in range(12)]
    bars = _bars(closes, volumes)
    t = 7
    row = t - lags
    X, y = build_features(bars, lags=lags)
    original = X[row].copy()

    for index in range(t + 1, len(bars)):
        bumped = _replace(
            bars,
            index,
            close=closes[index] + 50,
            volume=volumes[index] + 500,
        )
        X_future, _ = build_features(bumped, lags=lags)
        assert X_future[row] == pytest.approx(original)

    below = _replace(bars, t + 1, close=closes[t] - 1)
    X_label, y_label = build_features(below, lags=lags)
    assert y[row] == 1
    assert y_label[row] == 0
    assert X_label[row] == pytest.approx(original)

    today = _replace(bars, t, close=closes[t] + 50)
    X_today, _ = build_features(today, lags=lags)
    assert X_today[row] != pytest.approx(original)


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_non_finite_close_rejected(bad):
    closes = [10.0, 11.0, 12.0, 13.0, 14.0]
    closes[2] = bad
    bars = _bars(closes, [1.0] * len(closes))
    with pytest.raises(ValueError, match="non-finite close"):
        build_features(bars, lags=2)


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_non_finite_volume_rejected(bad):
    volumes = [1.0, 1.0, 1.0, 1.0, 1.0]
    volumes[2] = bad
    bars = _bars([10.0, 11.0, 12.0, 13.0, 14.0], volumes)
    with pytest.raises(ValueError, match="non-finite volume"):
        build_features(bars, lags=2)


@pytest.mark.parametrize("bad", [0.0, -1.0])
def test_non_positive_close_rejected(bad):
    closes = [10.0, 11.0, 12.0, 13.0, 14.0]
    closes[2] = bad
    bars = _bars(closes, [1.0] * len(closes))
    with pytest.raises(ValueError, match="non-finite log return"):
        build_features(bars, lags=2)


def test_folds_are_causal_and_disjoint():
    n = 50
    X = np.random.default_rng(0).normal(size=(n, 2))
    y = np.arange(n) % 2
    result = walk_forward(X, y, min_train=20, step=7, random_state=0)

    assert len(result.folds) >= 2
    seen: set[int] = set()
    for fold in result.folds:
        train = range(fold.train_end)
        test = range(fold.test_start, fold.test_end)
        assert test
        assert max(train) < min(test)
        assert seen.isdisjoint(test)
        seen.update(test)
        assert fold.test_start == fold.train_end
    for prev, nxt in zip(result.folds, result.folds[1:]):
        assert nxt.train_end == prev.test_end
    for fold in result.folds[:-1]:
        assert fold.test_end - fold.test_start == 7

    total = sum(fold.test_end - fold.test_start for fold in result.folds)
    weighted = sum(
        fold.accuracy * (fold.test_end - fold.test_start) for fold in result.folds
    )
    assert result.accuracy == pytest.approx(weighted / total)


def test_baselines_use_the_test_rows():
    X = np.arange(30, dtype=float).reshape(30, 1)
    y = np.array([0] * 15 + [1] * 5 + [1] * 10)
    result = walk_forward(X, y, min_train=20, step=10, random_state=0)

    assert len(result.folds) == 1
    fold = result.folds[0]
    assert fold.always_up_accuracy == pytest.approx(1.0)
    assert fold.majority_accuracy == pytest.approx(0.0)
    assert result.always_up_accuracy == pytest.approx(1.0)
    assert result.majority_accuracy == pytest.approx(0.0)


def test_scaler_mean_matches_train_slice_only():
    X = np.random.default_rng(0).normal(size=(80, 3))
    X[40:] += 10
    y = np.arange(80) % 2
    result = walk_forward(X, y, min_train=40, step=20, random_state=0)

    for fold in result.folds:
        fitted = fold.pipeline.named_steps["scaler"].mean_
        train_mean = X[: fold.train_end].mean(axis=0)
        assert fitted == pytest.approx(train_mean)
        assert fitted != pytest.approx(X.mean(axis=0))


def test_planted_signal_beats_majority_baseline():
    bars = _return_bars(n=800, seed=0, phi=0.9, scale=0.01)
    X, y = build_features(bars, lags=5)
    result = walk_forward(X, y, min_train=300, step=50, random_state=0)
    assert result.accuracy > result.majority_accuracy


def test_random_walk_stays_near_chance():
    bars = _return_bars(n=800, seed=1, phi=0.0, scale=0.01)
    X, y = build_features(bars, lags=5)
    result = walk_forward(X, y, min_train=300, step=50, random_state=0)
    assert result.accuracy == pytest.approx(0.5, abs=0.08)


def test_report_prints_fold_table(tmp_path, capsys):
    bars = _return_bars(n=40, seed=2, phi=0.0, scale=0.01)
    path = tmp_path / "bars.csv"
    _write_bars(path, bars)

    assert main([str(path)]) == 0
    out = capsys.readouterr().out
    assert "fold" in out
    assert "overall" in out
    assert "accuracy" in out
    assert "majority" in out
    assert "always_up" in out


def _bars(closes, volumes) -> list[Bar]:
    start = datetime(2020, 1, 1)
    bars = []
    for i, (close, volume) in enumerate(zip(closes, volumes, strict=True)):
        bars.append(
            Bar(
                timestamp=start + timedelta(days=i),
                open=close,
                high=close,
                low=close,
                close=close,
                volume=volume,
            )
        )
    return bars


def _replace(bars, index, **changes):
    current = bars[index]
    data = {
        "timestamp": current.timestamp,
        "open": current.open,
        "high": current.high,
        "low": current.low,
        "close": current.close,
        "volume": current.volume,
    }
    data.update(changes)
    updated = list(bars)
    updated[index] = Bar(**data)
    return updated


def _return_bars(n: int, seed: int, phi: float, scale: float) -> list[Bar]:
    rng = np.random.default_rng(seed)
    rets = np.empty(n)
    rets[0] = rng.normal(0, scale)
    for i in range(1, n):
        rets[i] = phi * rets[i - 1] + rng.normal(0, scale)
    price = 100.0
    closes = []
    for ret in rets:
        price *= math.exp(float(ret))
        closes.append(price)
    volumes = rng.uniform(50.0, 150.0, size=n)
    return _bars(closes, volumes)


def _write_bars(path, bars) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["timestamp", "open", "high", "low", "close", "volume"])
        for bar in bars:
            writer.writerow(
                [
                    bar.timestamp.isoformat(),
                    bar.open,
                    bar.high,
                    bar.low,
                    bar.close,
                    bar.volume,
                ]
            )
