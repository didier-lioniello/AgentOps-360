"""Health and operational-metrics boundary tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from fastapi import FastAPI, Response
from fastapi.testclient import TestClient

import api.routes.health as health_routes
from api.main import metrics_endpoint


class _ScalarResult:
    def __init__(self, value: bool) -> None:
        self.value = value

    def scalar(self) -> bool:
        return self.value


class _Database:
    def __init__(self, schema_ready: bool = True, fail: bool = False) -> None:
        self.schema_ready = schema_ready
        self.fail = fail
        self.statement = ""

    async def execute(self, statement: object) -> _ScalarResult:
        self.statement = str(statement)
        if self.fail:
            raise RuntimeError("database unavailable")
        return _ScalarResult(self.schema_ready)


class _Redis:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    async def ping(self) -> bool:
        if self.fail:
            raise RuntimeError("redis unavailable")
        return True


@pytest.mark.parametrize(
    ("database", "redis", "expected_checks"),
    [
        (_Database(fail=True), _Redis(), {"db": False, "redis": True}),
        (_Database(schema_ready=False), _Redis(), {"db": False, "redis": True}),
        (_Database(), _Redis(fail=True), {"db": True, "redis": False}),
    ],
)
async def test_ready_returns_503_when_a_dependency_or_schema_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    database: _Database,
    redis: _Redis,
    expected_checks: dict[str, bool],
) -> None:
    monkeypatch.setattr(health_routes, "get_redis", lambda: redis)
    response = Response()

    payload = await health_routes.ready(response=response, db=database)  # type: ignore[arg-type]

    assert response.status_code == 503
    assert payload == {"status": "degraded", "checks": expected_checks}


async def test_ready_returns_200_when_database_schema_and_redis_are_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(health_routes, "get_redis", lambda: _Redis())
    response = Response()

    database = _Database()
    payload = await health_routes.ready(response=response, db=database)  # type: ignore[arg-type]

    assert response.status_code == 200
    assert payload == {"status": "ready", "checks": {"db": True, "redis": True}}
    assert "cost_rollups_daily" in database.statement
    assert "golden_datasets" in database.statement
    assert "eval_runs" in database.statement


def _metrics_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("AUTH_MODE", "development")
    monkeypatch.setenv("DEV_TOKEN", "local-test-token-only")
    monkeypatch.setenv("DEV_TENANT_ID", "local-tenant")
    app = FastAPI()
    app.add_api_route("/metrics", metrics_endpoint, methods=["GET"])
    return TestClient(app)


def test_metrics_requires_authentication(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _metrics_client(monkeypatch).get("/metrics")

    assert response.status_code == 401


def test_metrics_omits_tenant_labels_and_cost_values(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _metrics_client(monkeypatch).get(
        "/metrics",
        headers={"Authorization": "Bearer local-test-token-only"},
    )

    assert response.status_code == 200
    assert "agentops_invocation_cost_usd" not in response.text
    assert "tenant=" not in response.text


def test_grafana_queries_only_use_exposed_aggregate_metrics() -> None:
    dashboard_path = Path(__file__).resolve().parents[1] / "ops" / "grafana-dashboard.json"
    dashboard = json.loads(dashboard_path.read_text())
    expressions = [target["expr"] for panel in dashboard["panels"] for target in panel["targets"]]

    assert all("agentops_invocation_cost_usd" not in expression for expression in expressions)
    assert all("tenant" not in expression for expression in expressions)
    assert "sum(rate(agentops_rate_limited_total[1m])) * 60" in expressions


def test_compose_workers_receive_only_required_environment() -> None:
    compose_path = Path(__file__).resolve().parents[1] / "docker-compose.yml"
    compose = yaml.safe_load(compose_path.read_text())
    eval_worker = compose["services"]["eval-worker"]
    cost_aggregator = compose["services"]["cost-aggregator"]

    assert eval_worker["profiles"] == ["evaluation"]
    assert "env_file" not in eval_worker
    assert "env_file" not in cost_aggregator
    for service in (eval_worker, cost_aggregator):
        environment = service["environment"]
        assert "JWT_SECRET" not in environment
        assert "DEV_TOKEN" not in environment
