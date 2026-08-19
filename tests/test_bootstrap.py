"""Bootstrap CI sanity checks."""

from __future__ import annotations

import pytest

from eval.bootstrap import bootstrap_ci


def test_empty_returns_zero():
    assert bootstrap_ci([]) == (0.0, 0.0)


def test_constant_series_zero_width_ci():
    lo, hi = bootstrap_ci([0.7] * 100)
    assert (lo, hi) == pytest.approx((0.7, 0.7))


def test_ci_brackets_mean_for_normal_data():
    # Roughly normal-ish scores
    scores = [0.3, 0.5, 0.6, 0.7, 0.8, 0.4, 0.55, 0.65, 0.45, 0.5] * 10
    lo, hi = bootstrap_ci(scores)
    mean = sum(scores) / len(scores)
    assert lo < mean < hi
