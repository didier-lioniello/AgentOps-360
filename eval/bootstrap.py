"""Bootstrap CI — same routine as EvalStack-360, kept local to keep AgentOps standalone."""

from __future__ import annotations

import random


def bootstrap_ci(
    scores: list[float], n_samples: int = 1000, confidence: float = 0.95, seed: int = 42
) -> tuple[float, float]:
    if not scores:
        return (0.0, 0.0)
    rng = random.Random(seed)
    n = len(scores)
    means = []
    for _ in range(n_samples):
        sample = [scores[rng.randrange(n)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    lo_idx = int((1 - confidence) / 2 * n_samples)
    hi_idx = int((1 + confidence) / 2 * n_samples) - 1
    return (means[lo_idx], means[hi_idx])
