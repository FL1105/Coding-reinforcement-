from dataclasses import dataclass

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


@dataclass(frozen=True)
class FoldResult:
    train_end: int
    test_start: int
    test_end: int
    accuracy: float
    majority_accuracy: float
    always_up_accuracy: float
    pipeline: Pipeline


@dataclass(frozen=True)
class WalkForwardResult:
    folds: list[FoldResult]
    accuracy: float
    majority_accuracy: float
    always_up_accuracy: float


def walk_forward(
    X,
    y,
    *,
    min_train: int,
    step: int,
    random_state: int = 0,
) -> WalkForwardResult:
    if min_train < 1 or step < 1:
        raise ValueError("min_train and step must be positive")

    features = np.asarray(X, dtype=float)
    labels = np.asarray(y)
    if features.ndim != 2 or labels.ndim != 1 or len(features) != len(labels):
        raise ValueError("X and y must be aligned")
    if min_train >= len(labels):
        raise ValueError("not enough rows to test")

    folds: list[FoldResult] = []
    correct = 0
    majority_correct = 0
    up_correct = 0
    total = 0
    train_end = min_train
    while train_end < len(labels):
        test_end = min(train_end + step, len(labels))
        pipeline = _pipeline(random_state)
        pipeline.fit(features[:train_end], labels[:train_end])
        y_test = labels[train_end:test_end]
        pred = pipeline.predict(features[train_end:test_end])
        n_test = test_end - train_end
        majority_pred = np.full(n_test, _majority(labels[:train_end]))
        up_pred = np.ones(n_test, dtype=int)
        fold_correct = int(np.sum(pred == y_test))
        fold_majority = int(np.sum(majority_pred == y_test))
        fold_up = int(np.sum(up_pred == y_test))
        folds.append(
            FoldResult(
                train_end=train_end,
                test_start=train_end,
                test_end=test_end,
                accuracy=fold_correct / n_test,
                majority_accuracy=fold_majority / n_test,
                always_up_accuracy=fold_up / n_test,
                pipeline=pipeline,
            )
        )
        correct += fold_correct
        majority_correct += fold_majority
        up_correct += fold_up
        total += n_test
        train_end = test_end

    return WalkForwardResult(
        folds=folds,
        accuracy=correct / total,
        majority_accuracy=majority_correct / total,
        always_up_accuracy=up_correct / total,
    )


def _pipeline(random_state: int) -> Pipeline:
    return Pipeline(
        [
            ("scaler", StandardScaler()),
            (
                "clf",
                LogisticRegression(random_state=random_state, max_iter=1000),
            ),
        ]
    )


def _majority(labels: np.ndarray) -> int:
    return int(np.argmax(np.bincount(labels.astype(int))))
