"""Invocation request / response / record."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_INVOCATION_INPUT_CHARS = 32_000
MAX_METADATA_BYTES = 16_384


class InvocationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent: str = Field(
        ...,
        min_length=3,
        max_length=64,
        pattern=r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$",
        description="Agent name (router selects the version)",
    )
    input: str = Field(..., min_length=1, max_length=MAX_INVOCATION_INPUT_CHARS)
    version: str | None = Field(
        default=None,
        max_length=64,
        pattern=r"^\d+\.\d+\.\d+(?:-[a-z0-9.-]+)?$",
    )
    metadata: dict[str, Any] = Field(default_factory=dict, max_length=64)

    @field_validator("metadata")
    @classmethod
    def _metadata_size(cls, value: dict[str, Any]) -> dict[str, Any]:
        try:
            encoded = json.dumps(
                value,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode()
        except (TypeError, ValueError) as exc:
            raise ValueError("metadata must contain JSON-serializable values") from exc
        if len(encoded) > MAX_METADATA_BYTES:
            raise ValueError(f"metadata must not exceed {MAX_METADATA_BYTES} encoded bytes")
        return value


class TokenUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0


class InvocationResult(BaseModel):
    invocation_id: str
    agent: str
    version: str
    output: str
    status: str  # ok | error | timeout
    error: str | None = None
    usage: TokenUsage = Field(default_factory=TokenUsage)
    cost_usd: float = 0.0
    latency_ms: int = 0
    trace_id: str | None = None


class InvocationRecord(BaseModel):
    id: str
    tenant_id: str
    agent_name: str
    agent_version: str
    input: str
    output: str | None
    status: str
    error: str | None
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: int
    trace_id: str | None
    created_at: datetime
