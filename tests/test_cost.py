"""Cost calculator unit tests."""

from __future__ import annotations

import pytest

from core.cost import CostCalculator, ModelPricing


def test_known_model_cost():
    calc = CostCalculator()
    cost = calc.cost("gpt-4o-mini", 1_000_000, 1_000_000)
    # 0.15 + 0.60 = 0.75 USD per 1M each
    assert cost == pytest.approx(0.15 + 0.60, rel=1e-9)


def test_unknown_model_uses_default():
    calc = CostCalculator()
    cost = calc.cost("totally-not-a-real-model", 1_000_000, 1_000_000)
    assert cost == pytest.approx(1.00 + 3.00, rel=1e-9)


def test_zero_tokens_zero_cost():
    calc = CostCalculator()
    assert calc.cost("gpt-4o", 0, 0) == 0.0


def test_pricing_override():
    custom = {"my-model": ModelPricing(0.50, 1.00)}
    calc = CostCalculator(pricing=custom)
    assert calc.cost("my-model", 2_000_000, 1_000_000) == pytest.approx(2.0, rel=1e-9)
