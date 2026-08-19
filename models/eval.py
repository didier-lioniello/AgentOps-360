"""Evaluation models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class GoldenItem(BaseModel):
    id: str | None = None
    input: str
    expected: Any
    tags: list[str] = Field(default_factory=list)


class EvalRunRecord(BaseModel):
    id: str
    agent_name: str
    agent_version: str
    dataset_id: str
    aggregate: dict[str, float]
    ci: dict[str, list[float]]
    n_items: int
    n_errors: int
    created_at: datetime
