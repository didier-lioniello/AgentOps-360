"""Evaluation worker transaction and scoring tests."""

from __future__ import annotations

from typing import Any

import pytest

from models.invocation import InvocationResult
from workers import eval_worker


class _Session:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class _Invoker:
    def __init__(self, result: InvocationResult | None = None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error

    async def invoke(self, _tenant: str, _request: object, version: str) -> InvocationResult:
        del version
        if self.error:
            raise self.error
        assert self.result is not None
        return self.result


def _result(status: str) -> InvocationResult:
    return InvocationResult(
        invocation_id="inv-1",
        agent="orders-classifier",
        version="1.0.0",
        output="classified" if status == "ok" else "",
        status=status,
        error=None if status == "ok" else "sanitized failure",
    )


def _job() -> dict[str, Any]:
    return {"agent_name": "orders-classifier", "agent_version": "1.0.0"}


def _item() -> dict[str, Any]:
    return {"id": "case-1", "input": "where is my order?", "expected": "shipping"}


async def test_successful_eval_invocation_is_committed() -> None:
    session = _Session()

    output, failed = await eval_worker._invoke_item(  # type: ignore[arg-type]
        _Invoker(result=_result("ok")), session, _job(), _item()
    )

    assert output == "classified"
    assert failed is False
    assert session.commits == 1
    assert session.rollbacks == 0


@pytest.mark.parametrize("status", ["error", "timeout"])
async def test_unsuccessful_eval_result_is_committed_and_counted_as_failure(status: str) -> None:
    session = _Session()

    output, failed = await eval_worker._invoke_item(  # type: ignore[arg-type]
        _Invoker(result=_result(status)), session, _job(), _item()
    )

    assert output is None
    assert failed is True
    assert session.commits == 1
    assert session.rollbacks == 0


async def test_eval_invocation_exception_rolls_back_without_leaking_details() -> None:
    session = _Session()

    output, failed = await eval_worker._invoke_item(  # type: ignore[arg-type]
        _Invoker(error=RuntimeError("provider-secret")), session, _job(), _item()
    )

    assert output is None
    assert failed is True
    assert session.commits == 0
    assert session.rollbacks == 1


def test_metric_failures_are_not_converted_to_zero_scores(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken_metric(_actual: str, _expected: str, _item: dict[str, Any]) -> float:
        raise RuntimeError("judge unavailable")

    monkeypatch.setattr(
        eval_worker,
        "METRICS",
        {
            "valid": lambda _actual, _expected, _item: 0.8,
            "broken": broken_metric,
            "non_finite": lambda _actual, _expected, _item: float("nan"),
            "negative": lambda _actual, _expected, _item: -0.1,
            "too_large": lambda _actual, _expected, _item: 1.1,
        },
    )

    scores, had_error = eval_worker._score_item("actual", "expected", _item())

    assert scores == {"valid": 0.8}
    assert had_error is True
    assert "broken" not in scores
    assert "non_finite" not in scores
    assert "negative" not in scores
    assert "too_large" not in scores


async def test_eval_job_does_not_load_data_without_external_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ALLOW_EXTERNAL_EVAL_DATA", raising=False)

    async def unexpected_load(_dataset_id: str) -> list[dict[str, Any]]:
        raise AssertionError("dataset must not be loaded while external evaluation is disabled")

    monkeypatch.setattr(eval_worker, "_load_dataset", unexpected_load)

    await eval_worker.run_one_job({**_job(), "dataset_id": "dataset-1"})
