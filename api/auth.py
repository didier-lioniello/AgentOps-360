"""Bearer authentication for the reference API.

Two explicit modes are supported:

* ``jwt`` (the safe default): validate an HS256 JWT and derive the tenant solely
  from its signed ``tenant_id`` claim.
* ``development``: accept one explicitly configured local token and map it to
  one explicitly configured local tenant.

The development mode is intentionally opt-in. It must not be used for a
deployed service; a real deployment should replace the HS256 decoder with an
OIDC/JWKS integration and add authorization appropriate to its threat model.
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from typing import Any

import jwt
from fastapi import Header, HTTPException, status

_INSECURE_JWT_SECRETS = {
    "change-me",
    "change-me-in-production",
    "dev-secret-change-me",
    "secret",
}


class AuthConfigurationError(RuntimeError):
    """Raised when authentication is not configured safely."""


@dataclass(frozen=True)
class AuthSettings:
    mode: str
    audience: str
    jwt_secret: str | None = None
    dev_token: str | None = None
    dev_tenant_id: str | None = None


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise AuthConfigurationError(f"{name} must be set")
    return value


def load_auth_settings() -> AuthSettings:
    """Load and validate auth settings without any credential fallback."""
    mode = os.getenv("AUTH_MODE", "jwt").strip().lower()
    audience = os.getenv("JWT_AUDIENCE", "agentops").strip()
    if not audience:
        raise AuthConfigurationError("JWT_AUDIENCE must not be empty")

    if mode == "jwt":
        secret = _required_env("JWT_SECRET")
        if len(secret) < 32 or secret.lower() in _INSECURE_JWT_SECRETS:
            raise AuthConfigurationError(
                "JWT_SECRET must be at least 32 characters and must not be a placeholder"
            )
        return AuthSettings(mode=mode, audience=audience, jwt_secret=secret)

    if mode == "development":
        token = _required_env("DEV_TOKEN")
        tenant_id = _required_env("DEV_TENANT_ID")
        if len(token) < 16:
            raise AuthConfigurationError("DEV_TOKEN must be at least 16 characters")
        return AuthSettings(
            mode=mode,
            audience=audience,
            dev_token=token,
            dev_tenant_id=tenant_id,
        )

    raise AuthConfigurationError("AUTH_MODE must be either 'jwt' or 'development'")


def validate_auth_configuration() -> None:
    """Fail application startup when auth configuration is unsafe or incomplete."""
    load_auth_settings()


def _decode_token(token: str) -> dict[str, Any]:
    try:
        settings = load_auth_settings()
    except AuthConfigurationError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="authentication is not configured",
        ) from exc

    if settings.mode == "development":
        if not secrets.compare_digest(token, settings.dev_token or ""):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="invalid token")
        return {"sub": "development-user", "tenant_id": settings.dev_tenant_id}

    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=["HS256"],
            audience=settings.audience,
            options={"require": ["aud", "exp", "sub", "tenant_id"]},
        )
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="invalid token") from exc

    subject = claims.get("sub")
    tenant_id = claims.get("tenant_id")
    if not isinstance(subject, str) or not subject.strip():
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="token subject required")
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="token tenant_id required")
    return claims


async def authenticate(
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Authenticate a bearer token; tenant identity always comes from the token."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="missing bearer token")
    return _decode_token(token)
