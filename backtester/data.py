import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

_COLUMNS = ("timestamp", "open", "high", "low", "close", "volume")
_NUMERIC = ("open", "high", "low", "close", "volume")


@dataclass(frozen=True)
class Bar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


def load_bars_csv(path) -> list[Bar]:
    with Path(path).open(newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or ()
        missing = [name for name in _COLUMNS if name not in fieldnames]
        if missing:
            raise ValueError(f"missing column: {', '.join(missing)}")

        bars: list[Bar] = []
        seen: set[datetime] = set()
        for row in reader:
            timestamp = datetime.fromisoformat(row["timestamp"])
            values = {name: _parse_float(name, row[name]) for name in _NUMERIC}
            if timestamp in seen:
                raise ValueError(f"duplicate timestamp: {row['timestamp']}")
            seen.add(timestamp)
            if values["high"] < values["low"]:
                raise ValueError(f"high < low at {row['timestamp']}")
            for name in ("open", "close"):
                if values[name] < values["low"] or values[name] > values["high"]:
                    raise ValueError(
                        f"{name} outside [low, high] at {row['timestamp']}"
                    )
            bars.append(Bar(timestamp=timestamp, **values))

    bars.sort(key=lambda bar: bar.timestamp)
    return bars


def _parse_float(name: str, raw: str) -> float:
    try:
        return float(raw)
    except (TypeError, ValueError):
        raise ValueError(f"non-numeric {name}: {raw!r}") from None
