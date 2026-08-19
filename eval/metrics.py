"""Metric functions for the eval worker."""

from __future__ import annotations

import json
import os
import re
from typing import Any

from openai import OpenAI

_client: OpenAI | None = None
_EMB_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-large")


def external_evaluation_enabled() -> bool:
    """Return whether sending evaluation data to external providers is explicitly allowed."""
    return os.getenv("ALLOW_EXTERNAL_EVAL_DATA", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _require_external_evaluation() -> None:
    if not external_evaluation_enabled():
        raise RuntimeError("external evaluation is disabled")


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI()
    return _client


def _cos(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb + 1e-12)


def semantic_similarity(actual: str, expected: str, _item: dict[str, Any]) -> float:
    _require_external_evaluation()
    if not actual or not expected:
        return 0.0
    client = _get_client()
    resp = client.embeddings.create(model=_EMB_MODEL, input=[actual, expected])
    return max(0.0, min(1.0, (_cos(resp.data[0].embedding, resp.data[1].embedding) + 1) / 2))


JUDGE_SYSTEM = """
You are a strict evaluator. Score the MODEL_ANSWER vs EXPECTED on [0, 1].

Axes (average them):
- correctness
- relevance
- completeness

Return ONLY {"score": <float>, "reason": "..."}.
""".strip()


def llm_judge(actual: str, expected: str, item: dict[str, Any]) -> float:
    _require_external_evaluation()
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_openai import ChatOpenAI

    llm = ChatOpenAI(model=os.getenv("JUDGE_MODEL", "gpt-4o-mini"), temperature=0.0)
    prompt = f"INPUT:\n{item.get('input', '')}\n\nEXPECTED:\n{expected}\n\nMODEL_ANSWER:\n{actual}"
    resp = llm.invoke([SystemMessage(content=JUDGE_SYSTEM), HumanMessage(content=prompt)])
    clean = re.sub(r"```(?:json)?|```", "", resp.content).strip()
    obj = json.loads(clean)
    if "score" not in obj:
        raise ValueError("judge response is missing a score")
    score = float(obj["score"])
    if not 0.0 <= score <= 1.0:
        raise ValueError("judge score must be between 0 and 1")
    return score
