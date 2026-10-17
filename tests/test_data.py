from datetime import datetime
from pathlib import Path

import pytest

from backtester.data import Bar, load_bars_csv

FIXTURE = Path(__file__).parent / "fixtures" / "bars.csv"


def test_load_bars_csv_sorts_and_parses():
    bars = load_bars_csv(FIXTURE)
    assert bars == [
        Bar(datetime.fromisoformat("2024-01-01T00:00:00"), 8, 9, 7, 8.5, 50),
        Bar(datetime.fromisoformat("2024-01-02T00:00:00"), 8.5, 10.5, 8, 10, 75),
        Bar(datetime.fromisoformat("2024-01-03T00:00:00"), 10, 12, 9, 11, 100),
        Bar(datetime.fromisoformat("2024-01-04T00:00:00"), 5, 6, 5, 6, 10),
        Bar(datetime.fromisoformat("2024-01-05T00:00:00"), 4, 4, 4, 4, 1),
    ]


def test_bar_is_frozen():
    bar = Bar(datetime(2024, 1, 1), 1, 2, 1, 1.5, 10)
    with pytest.raises(AttributeError):
        bar.close = 2


def test_missing_column(tmp_path):
    path = _write(
        tmp_path,
        "timestamp,open,high,low,close\n2024-01-01T00:00:00,1,1,1,1\n",
    )
    with pytest.raises(ValueError, match="missing column: volume"):
        load_bars_csv(path)


def test_non_numeric_value(tmp_path):
    path = _write(
        tmp_path,
        "timestamp,open,high,low,close,volume\n2024-01-01T00:00:00,1,1,1,abc,1\n",
    )
    with pytest.raises(ValueError, match="non-numeric close"):
        load_bars_csv(path)


def test_duplicate_timestamps(tmp_path):
    path = _write(
        tmp_path,
        "timestamp,open,high,low,close,volume\n"
        "2024-01-01T00:00:00,1,2,1,1.5,1\n"
        "2024-01-01T00:00:00,1,2,1,1.5,2\n",
    )
    with pytest.raises(ValueError, match="duplicate timestamp: 2024-01-01T00:00:00"):
        load_bars_csv(path)


def test_high_below_low(tmp_path):
    path = _write(
        tmp_path,
        "timestamp,open,high,low,close,volume\n2024-01-01T00:00:00,1.5,1,2,1.5,1\n",
    )
    with pytest.raises(ValueError, match="high < low"):
        load_bars_csv(path)


def test_open_outside_range(tmp_path):
    path = _write(
        tmp_path,
        "timestamp,open,high,low,close,volume\n2024-01-01T00:00:00,0,2,1,1.5,1\n",
    )
    with pytest.raises(ValueError, match=r"open outside \[low, high\]"):
        load_bars_csv(path)


def test_close_outside_range(tmp_path):
    path = _write(
        tmp_path,
        "timestamp,open,high,low,close,volume\n2024-01-01T00:00:00,1.5,2,1,3,1\n",
    )
    with pytest.raises(ValueError, match=r"close outside \[low, high\]"):
        load_bars_csv(path)


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "bars.csv"
    path.write_text(text)
    return path
