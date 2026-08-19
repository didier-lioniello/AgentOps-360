"""Authentication and token-derived tenant tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from api.auth import AuthConfigurationError, authenticate, validate_auth_configuration

JWT_SECRET = "unit-test-secret-that-is-longer-than-thirty-two-characters"
JWT_AUDIENCE = "agentops-tests"


def _client() -> TestClient:
    app = FastAPI()

    @app.get("/claims")
    async def claims_endpoint(claims: dict = Depends(authenticate)) -> dict:
        return claims

    return TestClient(app)


def _configure_jwt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_MODE", "jwt")
    monkeypatch.setenv("JWT_SECRET", JWT_SECRET)
    monkeypatch.setenv("JWT_AUDIENCE", JWT_AUDIENCE)


def _token(**overrides: Any) -> str:
    claims = {
        "sub": "user-1",
        "tenant_id": "tenant-a",
        "aud": JWT_AUDIENCE,
        "exp": datetime.now(UTC) + timedelta(minutes=5),
    }
    claims.update(overrides)
    return jwt.encode(claims, JWT_SECRET, algorithm="HS256")


def test_tenant_header_cannot_override_signed_claim(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_jwt(monkeypatch)

    response = _client().get(
        "/claims",
        headers={
            "Authorization": f"Bearer {_token()}",
            "X-Tenant-Id": "tenant-b",
        },
    )

    assert response.status_code == 200
    assert response.json()["tenant_id"] == "tenant-a"


def test_static_development_token_is_not_a_jwt_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_jwt(monkeypatch)

    response = _client().get(
        "/claims",
        headers={"Authorization": "Bearer dev-token"},
    )

    assert response.status_code == 401


def test_development_mode_requires_explicit_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_MODE", "development")
    monkeypatch.delenv("DEV_TOKEN", raising=False)
    monkeypatch.delenv("DEV_TENANT_ID", raising=False)

    with pytest.raises(AuthConfigurationError):
        validate_auth_configuration()


def test_explicit_development_token_maps_to_configured_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTH_MODE", "development")
    monkeypatch.setenv("DEV_TOKEN", "local-test-token-only")
    monkeypatch.setenv("DEV_TENANT_ID", "local-tenant")

    response = _client().get(
        "/claims",
        headers={
            "Authorization": "Bearer local-test-token-only",
            "X-Tenant-Id": "attacker-tenant",
        },
    )

    assert response.status_code == 200
    assert response.json()["tenant_id"] == "local-tenant"


def test_jwt_without_tenant_claim_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_jwt(monkeypatch)
    token = jwt.encode(
        {
            "sub": "user-1",
            "aud": JWT_AUDIENCE,
            "exp": datetime.now(UTC) + timedelta(minutes=5),
        },
        JWT_SECRET,
        algorithm="HS256",
    )

    response = _client().get(
        "/claims",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401


def test_expired_jwt_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_jwt(monkeypatch)

    response = _client().get(
        "/claims",
        headers={"Authorization": f"Bearer {_token(exp=datetime.now(UTC) - timedelta(seconds=1))}"},
    )

    assert response.status_code == 401


@pytest.mark.parametrize("secret", ["", "change-me-in-production", "too-short"])
def test_jwt_mode_rejects_missing_or_placeholder_secret(
    monkeypatch: pytest.MonkeyPatch,
    secret: str,
) -> None:
    monkeypatch.setenv("AUTH_MODE", "jwt")
    monkeypatch.setenv("JWT_SECRET", secret)

    with pytest.raises(AuthConfigurationError):
        validate_auth_configuration()
