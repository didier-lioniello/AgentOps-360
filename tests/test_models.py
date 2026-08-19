"""Manifest validation tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from models.agent import AgentManifest
from models.invocation import InvocationRequest


def _base_manifest(**overrides) -> dict:
    base = {
        "name": "orders-classifier",
        "version": "1.0.0",
        "model": "gpt-4o-mini",
        "system_prompt": "You classify orders.",
    }
    base.update(overrides)
    return base


def test_manifest_minimal_ok():
    m = AgentManifest.model_validate(_base_manifest())
    assert m.name == "orders-classifier"
    assert m.guardrails.max_tokens > 0


def test_manifest_rejects_uppercase_name():
    with pytest.raises(ValidationError):
        AgentManifest.model_validate(_base_manifest(name="OrdersClassifier"))


def test_manifest_rejects_short_name():
    with pytest.raises(ValidationError):
        AgentManifest.model_validate(_base_manifest(name="ab"))


def test_manifest_rejects_bad_semver():
    with pytest.raises(ValidationError):
        AgentManifest.model_validate(_base_manifest(version="v1"))


def test_manifest_accepts_prerelease_version():
    m = AgentManifest.model_validate(_base_manifest(version="1.0.0-canary"))
    assert m.version == "1.0.0-canary"


def test_tool_schema_keeps_public_alias():
    manifest = AgentManifest.model_validate(
        _base_manifest(
            tools=[
                {
                    "name": "lookup",
                    "description": "Look up an order",
                    "schema": {"type": "object"},
                }
            ]
        )
    )

    assert manifest.tools[0].input_schema == {"type": "object"}
    assert manifest.model_dump(by_alias=True)["tools"][0]["schema"] == {"type": "object"}


@pytest.mark.parametrize(
    "overrides",
    [
        {"system_prompt": "x" * 32_001},
        {"version": f"1.0.0-{'x' * 59}"},
        {"guardrails": {"max_tokens": 32_769}},
        {"guardrails": {"timeout_ms": 120_001}},
        {"metadata": {"value": "x" * 16_384}},
        {
            "tools": [
                {
                    "name": "lookup",
                    "description": "Look up an order",
                    "schema": {"value": "x" * 32_768},
                }
            ]
        },
    ],
)
def test_manifest_rejects_oversized_or_unbounded_configuration(overrides: dict) -> None:
    with pytest.raises(ValidationError):
        AgentManifest.model_validate(_base_manifest(**overrides))


def test_invocation_rejects_oversized_input() -> None:
    with pytest.raises(ValidationError):
        InvocationRequest(agent="orders-classifier", input="x" * 32_001)


def test_invocation_rejects_oversized_metadata() -> None:
    with pytest.raises(ValidationError):
        InvocationRequest(
            agent="orders-classifier",
            input="hello",
            metadata={"value": "x" * 16_384},
        )


def test_invocation_rejects_non_json_numeric_metadata() -> None:
    with pytest.raises(ValidationError):
        InvocationRequest(
            agent="orders-classifier",
            input="hello",
            metadata={"value": float("nan")},
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"unknown_manifest_field": True},
        {"guardrails": {"max_token": 123}},
        {
            "tools": [
                {
                    "name": "lookup",
                    "description": "Look up an order",
                    "schema": {"type": "object"},
                    "unknown_tool_field": True,
                }
            ]
        },
    ],
)
def test_manifest_rejects_unknown_policy_fields(overrides: dict) -> None:
    with pytest.raises(ValidationError):
        AgentManifest.model_validate(_base_manifest(**overrides))


def test_invocation_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        InvocationRequest.model_validate(
            {
                "agent": "orders-classifier",
                "input": "hello",
                "tenant_id": "attacker-controlled",
            }
        )
