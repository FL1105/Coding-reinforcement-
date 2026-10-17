import sys

from backtester.data import load_bars_csv
from backtester.ml.features import build_features
from backtester.ml.walk_forward import WalkForwardResult, walk_forward


def format_report(result: WalkForwardResult) -> str:
    lines = [_header()]
    for i, fold in enumerate(result.folds):
        span = f"{fold.test_start}:{fold.test_end}"
        lines.append(
            _row(
                f"{i:4d}",
                f"{fold.train_end:9d}",
                f"{span:>11}",
                f"{fold.accuracy:8.4f}",
                f"{fold.majority_accuracy:8.4f}",
                f"{fold.always_up_accuracy:9.4f}",
            )
        )
    lines.append(
        "  ".join(
            [
                "overall",
                f"accuracy {result.accuracy:.4f}",
                f"majority {result.majority_accuracy:.4f}",
                f"always_up {result.always_up_accuracy:.4f}",
            ]
        )
    )
    return "\n".join(lines)


def _header() -> str:
    return _row(
        f"{'fold':>4}",
        f"{'train_end':>9}",
        f"{'test':>11}",
        f"{'accuracy':>8}",
        f"{'majority':>8}",
        f"{'always_up':>9}",
    )


def _row(*cells: str) -> str:
    return "  ".join(cells)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("usage: python -m backtester.ml.report <csv>", file=sys.stderr)
        return 2
    bars = load_bars_csv(args[0])
    features, labels = build_features(bars)
    n = len(labels)
    if n < 3:
        print("not enough bars for a walk-forward split", file=sys.stderr)
        return 1
    min_train = max(n // 2, 2)
    step = max((n - min_train) // 4, 1)
    result = walk_forward(features, labels, min_train=min_train, step=step)
    print(format_report(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
