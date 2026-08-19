"""Privacy, lifecycle, and routing-integrity tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

import core.invoker as invoker_module
from core.invoker import InvocationError, Invoker
from core.registry import AgentRegistry, RegistryError
from core.router import Router, RouterError
from models.agent import AgentManifest, AgentRecord, AgentStatus
from models.invocation import InvocationRequest, TokenUsage
from models.routing import RoutingPolicy


def _manifest() -> AgentManifest:
    return AgentManifest(
        name="orders-classifier",
        version="1.0.0",
        system_prompt="Classify the order.",
    )


def _record(status: AgentStatus = AgentStatus.ACTIVE) -> AgentRecord:
    return AgentRecord(
        id="00000000-0000-0000-0000-000000000001",
        name="orders-classifier",
        version="1.0.0",
        manifest=_manifest(),
        status=status,
        created_at=datetime.now(UTC),
    )


class _CaptureSession:
    def __init__(self) -> None:
        self.params: dict[str, Any] = {}

    async def execute(self, _statement: object, params: dict[str, Any]) -> None:
        self.params = params


class _Registry:
    def __init__(self, record: AgentRecord) -> None:
        self.record = record

    async def get(self, _name: str, _version: str) -> AgentRecord:
        return self.record


async def test_invocation_content_is_redacted_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("STORE_INVOCATION_CONTENT", raising=False)
    session = _CaptureSession()
    invoker = Invoker(session)  # type: ignore[arg-type]

    await invoker._persist(
        invocation_id="inv-1",
        tenant_id="tenant-a",
        agent="orders-classifier",
        version="1.0.0",
        input_text="customer-secret-prompt",
        output="customer-secret-response",
        status="ok",
        error=None,
        usage=TokenUsage(),
        cost=0.0,
        latency_ms=1,
        trace_id=None,
    )

    assert session.params["input"] == "[redacted]"
    assert session.params["output"] == "[redacted]"
    assert "customer-secret" not in repr(session.params)


async def test_invocation_content_storage_requires_explicit_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STORE_INVOCATION_CONTENT", "true")
    session = _CaptureSession()
    invoker = Invoker(session)  # type: ignore[arg-type]

    await invoker._persist(
        invocation_id="inv-1",
        tenant_id="tenant-a",
        agent="orders-classifier",
        version="1.0.0",
        input_text="stored prompt",
        output="stored response",
        status="ok",
        error=None,
        usage=TokenUsage(),
        cost=0.0,
        latency_ms=1,
        trace_id=None,
    )

    assert session.params["input"] == "stored prompt"
    assert session.params["output"] == "stored response"


async def test_provider_error_details_are_not_returned_or_persisted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invoker = Invoker(_CaptureSession())  # type: ignore[arg-type]
    invoker.registry = _Registry(_record())  # type: ignore[assignment]
    captured: dict[str, Any] = {}

    async def fail_provider(_manifest: AgentManifest, _prompt: str) -> tuple[str, TokenUsage]:
        raise RuntimeError("provider-secret-api-key")

    async def capture_persist(**kwargs: Any) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(invoker, "_call_llm", fail_provider)
    monkeypatch.setattr(invoker, "_persist", capture_persist)

    result = await invoker.invoke(
        "tenant-a",
        InvocationRequest(agent="orders-classifier", input="hello"),
        "1.0.0",
    )

    assert result.status == "error"
    assert result.error == "model provider invocation failed"
    assert captured["error"] == "model provider invocation failed"
    assert "provider-secret-api-key" not in repr(result)
    assert "provider-secret-api-key" not in repr(captured)


async def test_traces_do_not_export_tenant_identifiers(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Span:
        def __init__(self) -> None:
            self.attributes: dict[str, str] = {}

        def __enter__(self) -> _Span:
            return self

        def __exit__(self, *_args: object) -> None:
            pass

        def set_attribute(self, name: str, value: str) -> None:
            self.attributes[name] = value

        def get_span_context(self) -> None:
            return None

    class _Tracer:
        def __init__(self, span: _Span) -> None:
            self.span = span

        def start_as_current_span(self, _name: str) -> _Span:
            return self.span

    span = _Span()
    invoker = Invoker(_CaptureSession())  # type: ignore[arg-type]
    invoker.registry = _Registry(_record())  # type: ignore[assignment]

    async def call_provider(_manifest: AgentManifest, _prompt: str) -> tuple[str, TokenUsage]:
        return "ok", TokenUsage()

    async def skip_persist(**_kwargs: Any) -> None:
        pass

    monkeypatch.setattr(invoker_module, "tracer", lambda: _Tracer(span))
    monkeypatch.setattr(invoker, "_call_llm", call_provider)
    monkeypatch.setattr(invoker, "_persist", skip_persist)

    await invoker.invoke(
        "sensitive-tenant-id",
        InvocationRequest(agent="orders-classifier", input="hello"),
        "1.0.0",
    )

    assert span.attributes == {
        "agent.name": "orders-classifier",
        "agent.version": "1.0.0",
    }
    assert "sensitive-tenant-id" not in repr(span.attributes)


async def test_archived_version_cannot_be_invoked() -> None:
    invoker = Invoker(_CaptureSession())  # type: ignore[arg-type]
    invoker.registry = _Registry(_record(AgentStatus.ARCHIVED))  # type: ignore[assignment]

    with pytest.raises(InvocationError, match="archived agent version"):
        await invoker.invoke(
            "tenant-a",
            InvocationRequest(agent="orders-classifier", input="hello"),
            "1.0.0",
        )


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (AgentStatus.ACTIVE, AgentStatus.ACTIVE),
        (AgentStatus.ACTIVE, AgentStatus.DEPRECATED),
        (AgentStatus.DEPRECATED, AgentStatus.ARCHIVED),
        (AgentStatus.ARCHIVED, AgentStatus.ARCHIVED),
    ],
)
def test_valid_status_transitions(current: AgentStatus, target: AgentStatus) -> None:
    AgentRegistry.validate_status_transition(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (AgentStatus.ACTIVE, AgentStatus.ARCHIVED),
        (AgentStatus.DEPRECATED, AgentStatus.ACTIVE),
        (AgentStatus.ARCHIVED, AgentStatus.ACTIVE),
        (AgentStatus.ARCHIVED, AgentStatus.DEPRECATED),
    ],
)
def test_invalid_status_transitions_are_rejected(current: AgentStatus, target: AgentStatus) -> None:
    with pytest.raises(RegistryError, match="invalid status transition"):
        AgentRegistry.validate_status_transition(current, target)


class _ScalarResult:
    def __init__(self, value: bool | None = None) -> None:
        self.value = value

    def scalar(self) -> bool | None:
        return self.value


class _LifecycleSession:
    def __init__(self, routed: bool) -> None:
        self.routed = routed
        self.updated = False

    async def execute(self, statement: object, _params: dict[str, Any]) -> _ScalarResult:
        sql = str(statement)
        if "SELECT EXISTS" in sql:
            return _ScalarResult(self.routed)
        if "UPDATE agents" in sql:
            self.updated = True
        return _ScalarResult()


async def test_archiving_a_routed_version_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _LifecycleSession(routed=True)
    registry = AgentRegistry(session)  # type: ignore[arg-type]

    async def get_deprecated(_name: str, _version: str) -> AgentRecord:
        return _record(AgentStatus.DEPRECATED)

    monkeypatch.setattr(registry, "get", get_deprecated)

    with pytest.raises(RegistryError, match="referenced by the routing policy"):
        await registry.set_status("orders-classifier", "1.0.0", AgentStatus.ARCHIVED)

    assert session.updated is False


async def test_archiving_an_unrouted_version_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _LifecycleSession(routed=False)
    registry = AgentRegistry(session)  # type: ignore[arg-type]

    async def get_deprecated(_name: str, _version: str) -> AgentRecord:
        return _record(AgentStatus.DEPRECATED)

    monkeypatch.setattr(registry, "get", get_deprecated)

    await registry.set_status("orders-classifier", "1.0.0", AgentStatus.ARCHIVED)

    assert session.updated is True


class _Rows:
    def __init__(self, rows: list[dict[str, str]]) -> None:
        self.rows = rows

    def mappings(self) -> _Rows:
        return self

    def all(self) -> list[dict[str, str]]:
        return self.rows


class _PolicySession:
    def __init__(self, rows: list[dict[str, str]]) -> None:
        self.rows = rows
        self.calls = 0

    async def execute(self, _statement: object, _params: dict[str, Any]) -> _Rows:
        self.calls += 1
        return _Rows(self.rows)


def _policy_payload() -> dict[str, Any]:
    return {
        "agent": "orders-classifier",
        "strategy": "weighted",
        "versions": [
            {"version": "1.0.0", "weight": 90},
            {"version": "1.1.0", "weight": 10},
        ],
    }


async def test_routing_policy_requires_existing_non_archived_versions() -> None:
    session = _PolicySession(
        [
            {"version": "1.0.0", "status": "active"},
            {"version": "1.1.0", "status": "deprecated"},
        ]
    )

    await Router(session).upsert_policy(RoutingPolicy.model_validate(_policy_payload()))  # type: ignore[arg-type]

    assert session.calls == 3


async def test_routing_policy_rejects_unknown_version() -> None:
    session = _PolicySession([{"version": "1.0.0", "status": "active"}])

    with pytest.raises(RouterError, match="unknown versions"):
        await Router(session).upsert_policy(RoutingPolicy.model_validate(_policy_payload()))  # type: ignore[arg-type]

    assert session.calls == 2


async def test_routing_policy_rejects_archived_version() -> None:
    session = _PolicySession(
        [
            {"version": "1.0.0", "status": "active"},
            {"version": "1.1.0", "status": "archived"},
        ]
    )

    with pytest.raises(RouterError, match="archived versions"):
        await Router(session).upsert_policy(RoutingPolicy.model_validate(_policy_payload()))  # type: ignore[arg-type]


def test_unimplemented_fallback_field_is_rejected() -> None:
    payload = _policy_payload()
    payload["fallback"] = {"on_error": "1.0.0"}

    with pytest.raises(ValidationError):
        RoutingPolicy.model_validate(payload)
