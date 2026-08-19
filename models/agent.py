"""Agent manifest + DB record models."""

from __future__ import annotations

import json
import re
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AgentStatus(str, Enum):
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    ARCHIVED = "archived"


class CostGuardrail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_cost_per_call_usd: float = Field(default=0.50, gt=0, le=100)
    max_tokens: int = Field(default=4000, gt=0, le=32_768)
    timeout_ms: int = Field(default=30_000, ge=100, le=120_000)


class ToolSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: str = Field(..., min_length=1, max_length=64)
    description: str = Field(..., min_length=1, max_length=4000)
    input_schema: dict[str, Any] = Field(
        default_factory=dict,
        validation_alias="schema",
        serialization_alias="schema",
    )

    @field_validator("input_schema")
    @classmethod
    def _schema_size(cls, value: dict[str, Any]) -> dict[str, Any]:
        _validate_json_size(value, 32_768, "tool schema")
        return value


class AgentManifest(BaseModel):
    """Immutable specification of one agent version."""

    model_config = ConfigDict(extra="forbid")

    name: str
    version: str = Field(..., max_length=64)
    model: str = Field(default="gpt-4o-mini", min_length=1, max_length=128)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    system_prompt: str = Field(..., min_length=1, max_length=32_000)
    tools: list[ToolSpec] = Field(default_factory=list, max_length=32)
    eval_dataset: str | None = Field(default=None, max_length=128)
    guardrails: CostGuardrail = Field(default_factory=CostGuardrail)
    metadata: dict[str, Any] = Field(default_factory=dict, max_length=64)

    @field_validator("name")
    @classmethod
    def _name_kebab(cls, v: str) -> str:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,62}[a-z0-9]", v):
            raise ValueError("name must be kebab-case alphanum, 3-64 chars")
        return v

    @field_validator("version")
    @classmethod
    def _semver(cls, v: str) -> str:
        if not re.fullmatch(r"\d+\.\d+\.\d+(?:-[a-z0-9.-]+)?", v):
            raise ValueError("version must be semver, e.g. 1.2.3 or 1.2.3-canary")
        return v

    @field_validator("metadata")
    @classmethod
    def _metadata_size(cls, value: dict[str, Any]) -> dict[str, Any]:
        _validate_json_size(value, 16_384, "manifest metadata")
        return value


class AgentRecord(BaseModel):
    id: str
    name: str
    version: str
    manifest: AgentManifest
    status: AgentStatus
    created_at: datetime


def _validate_json_size(value: Any, max_bytes: int, field_name: str) -> None:
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must contain JSON-serializable values") from exc
    if len(encoded) > max_bytes:
        raise ValueError(f"{field_name} must not exceed {max_bytes} encoded bytes")
