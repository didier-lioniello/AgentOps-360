"""External eval metric failures must reach the worker error boundary."""

from __future__ import annotations

from typing import Any

import langchain_openai
import pytest

from eval import metrics as eval_metrics


def test_external_metrics_are_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALLOW_EXTERNAL_EVAL_DATA", raising=False)

    with pytest.raises(RuntimeError, match="external evaluation is disabled"):
        eval_metrics.semantic_similarity("actual", "expected", {})


def test_embedding_provider_failure_is_not_converted_to_a_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALLOW_EXTERNAL_EVAL_DATA", "true")

    class _Embeddings:
        def create(self, **_kwargs: Any) -> None:
            raise RuntimeError("embedding provider unavailable")

    class _Client:
        embeddings = _Embeddings()

    monkeypatch.setattr(eval_metrics, "_get_client", lambda: _Client())

    with pytest.raises(RuntimeError, match="embedding provider unavailable"):
        eval_metrics.semantic_similarity("actual", "expected", {})


def test_judge_provider_failure_is_not_converted_to_a_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALLOW_EXTERNAL_EVAL_DATA", "true")

    class _Judge:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        def invoke(self, _messages: object) -> None:
            raise RuntimeError("judge provider unavailable")

    monkeypatch.setattr(langchain_openai, "ChatOpenAI", _Judge)

    with pytest.raises(RuntimeError, match="judge provider unavailable"):
        eval_metrics.llm_judge("actual", "expected", {"input": "prompt"})
