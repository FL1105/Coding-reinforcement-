import math

import numpy as np

from backtester.data import Bar


def build_features(
    bars: list[Bar], lags: int = 5
) -> tuple[np.ndarray, np.ndarray]:
    if lags < 1:
        raise ValueError("lags must be positive")

    closes = [_require_finite("close", bar.close) for bar in bars]
    volumes = [_require_finite("volume", bar.volume) for bar in bars]
    width = lags + 1
    if len(bars) < lags + 2:
        return np.empty((0, width)), np.empty(0, dtype=int)

    rows: list[list[float]] = []
    labels: list[int] = []
    for t in range(lags, len(bars) - 1):
        row = [
            _log_return(closes[t - k + 1], closes[t - k])
            for k in range(1, lags + 1)
        ]
        change = volumes[t] - volumes[t - 1]
        row.append(_require_finite("volume change", change))
        rows.append(row)
        labels.append(1 if closes[t + 1] > closes[t] else 0)

    return np.asarray(rows, dtype=float), np.asarray(labels, dtype=int)


def _log_return(curr: float, prev: float) -> float:
    if prev > 0.0 and curr > 0.0:
        value = math.log(curr / prev)
    else:
        value = math.nan
    return _require_finite("log return", value)


def _require_finite(name: str, value: float) -> float:
    if not math.isfinite(value):
        raise ValueError(f"non-finite {name}: {value!r}")
    return value
