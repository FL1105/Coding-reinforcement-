import math

import pytest
from hypothesis import given
from hypothesis import strategies as st

from backtester.validation import require_finite_positive


@pytest.mark.parametrize(
    "value", [float("nan"), float("inf"), float("-inf"), 0.0, -1.0]
)
def test_require_finite_positive_rejects_non_finite_or_non_positive(value):
    with pytest.raises(ValueError, match="price must be positive"):
        require_finite_positive("price", value)


@given(st.floats())
def test_require_finite_positive_accepts_exactly_finite_positives(value):
    if math.isfinite(value) and value > 0:
        assert require_finite_positive("price", value) == pytest.approx(value)
    else:
        with pytest.raises(ValueError, match="price must be positive"):
            require_finite_positive("price", value)
