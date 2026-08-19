"""
CostCalculator — per-model token pricing.

Prices are in USD per 1M tokens. Update from provider rate cards regularly.
For unknown models, falls back to a configurable default.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelPricing:
    input_per_mtok: float  # USD per 1,000,000 input tokens
    output_per_mtok: float  # USD per 1,000,000 output tokens


# Snapshot — not a live rate card. Update before relying on absolute numbers.
PRICING: dict[str, ModelPricing] = {
    "gpt-4o": ModelPricing(2.50, 10.00),
    "gpt-4o-mini": ModelPricing(0.15, 0.60),
    "gpt-4-turbo": ModelPricing(10.00, 30.00),
    "claude-3-5-sonnet": ModelPricing(3.00, 15.00),
    "claude-3-haiku": ModelPricing(0.25, 1.25),
    "claude-opus-4": ModelPricing(15.00, 75.00),
}

DEFAULT_PRICING = ModelPricing(1.00, 3.00)


class CostCalculator:
    def __init__(
        self, pricing: dict[str, ModelPricing] | None = None, default: ModelPricing = DEFAULT_PRICING
    ):
        self.pricing = pricing or PRICING
        self.default = default

    def cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        p = self.pricing.get(model, self.default)
        return (input_tokens * p.input_per_mtok + output_tokens * p.output_per_mtok) / 1_000_000.0
