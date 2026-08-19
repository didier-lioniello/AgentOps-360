"""
Router unit tests — pure logic, no DB dependency.

We test:
- Single strategy is deterministic.
- Weighted random honors the distribution at large N.
- Sticky routing is deterministic for the same key.
- Sticky routing distributes across keys.
"""

from __future__ import annotations

from collections import Counter

import pytest

from core.router import Router
from models.routing import RoutingPolicy, RoutingStrategy, VersionWeight


def _policy(
    strategy: RoutingStrategy, weights: list[tuple[str, int]], sticky_by: str | None = None
) -> RoutingPolicy:
    return RoutingPolicy(
        agent="test-agent",
        strategy=strategy,
        versions=[VersionWeight(version=v, weight=w) for v, w in weights],
        sticky_by=sticky_by,
    )


def test_single_returns_only_version():
    p = _policy(RoutingStrategy.SINGLE, [("1.0.0", 100)])
    assert Router.select_version(Router(None), p) == "1.0.0"  # type: ignore[arg-type]


def test_weighted_distribution():
    p = _policy(RoutingStrategy.WEIGHTED, [("1.0.0", 80), ("2.0.0", 20)])
    counts: Counter = Counter()
    router = Router(None)  # type: ignore[arg-type]
    for _ in range(2000):
        counts[router.select_version(p)] += 1
    # 80/20 with N=2000 → expect ~1600/400 ± noise
    assert 1450 < counts["1.0.0"] < 1750
    assert 250 < counts["2.0.0"] < 550


def test_sticky_is_deterministic():
    p = _policy(RoutingStrategy.AB, [("1.0.0", 50), ("2.0.0", 50)], sticky_by="tenant_id")
    router = Router(None)  # type: ignore[arg-type]
    first = router.select_version(p, sticky_key="acme")
    for _ in range(100):
        assert router.select_version(p, sticky_key="acme") == first


def test_sticky_distributes_across_keys():
    p = _policy(RoutingStrategy.AB, [("1.0.0", 50), ("2.0.0", 50)], sticky_by="tenant_id")
    router = Router(None)  # type: ignore[arg-type]
    counts: Counter = Counter()
    for i in range(1000):
        counts[router.select_version(p, sticky_key=f"key-{i}")] += 1
    # 50/50 ± reasonable noise
    assert 400 < counts["1.0.0"] < 600
    assert 400 < counts["2.0.0"] < 600


def test_weights_must_sum_to_100():
    with pytest.raises(ValueError):
        _policy(RoutingStrategy.WEIGHTED, [("1.0.0", 30), ("2.0.0", 30)])


def test_single_requires_exactly_one_full_weight_version():
    with pytest.raises(ValueError, match="exactly one"):
        _policy(RoutingStrategy.SINGLE, [("1.0.0", 50), ("2.0.0", 50)])


@pytest.mark.parametrize(
    ("weights", "sticky_by"),
    [
        ([("1.0.0", 60), ("2.0.0", 40)], "tenant_id"),
        ([("1.0.0", 50), ("2.0.0", 50)], None),
    ],
)
def test_ab_requires_two_equal_sticky_arms(weights: list[tuple[str, int]], sticky_by: str | None):
    with pytest.raises(ValueError, match="ab routing requires"):
        _policy(RoutingStrategy.AB, weights, sticky_by=sticky_by)


@pytest.mark.parametrize(
    "weights",
    [
        [("1.0.0", 70), ("1.1.0", 30)],
        [("1.0.0", 100), ("1.1.0", 0)],
        [("1.0.0", 80), ("1.1.0", 10), ("1.2.0", 10)],
    ],
)
def test_canary_requires_one_stable_and_one_nonzero_canary(weights: list[tuple[str, int]]):
    with pytest.raises(ValueError, match="canary routing requires"):
        _policy(RoutingStrategy.CANARY, weights)


def test_policy_rejects_duplicate_versions():
    with pytest.raises(ValueError, match="versions must be unique"):
        _policy(RoutingStrategy.WEIGHTED, [("1.0.0", 50), ("1.0.0", 50)])


def test_policy_rejects_more_than_32_versions():
    weights = [(f"1.0.{index}", 0) for index in range(32)] + [("2.0.0", 100)]

    with pytest.raises(ValueError, match="at most 32"):
        _policy(RoutingStrategy.WEIGHTED, weights)
