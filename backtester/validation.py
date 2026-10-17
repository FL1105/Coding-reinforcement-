import math


def require_finite_positive(name: str, value: float) -> float:
    if not (math.isfinite(value) and value > 0):
        raise ValueError(f"{name} must be positive")
    return value
