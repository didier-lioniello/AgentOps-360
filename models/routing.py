"""Routing policy schema."""

from __future__ import annotations

from enum import Enum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RoutingStrategy(str, Enum):
    SINGLE = "single"  # one version, no split
    WEIGHTED = "weighted"  # static %
    CANARY = "canary"  # one stable + small canary
    AB = "ab"  # two equal arms; sticky by tenant


class VersionWeight(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = Field(
        ...,
        max_length=64,
        pattern=r"^\d+\.\d+\.\d+(?:-[a-z0-9.-]+)?$",
    )
    weight: int = Field(..., ge=0, le=100)


class RoutingPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent: str = Field(
        ...,
        min_length=3,
        max_length=64,
        pattern=r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$",
    )
    strategy: RoutingStrategy
    versions: list[VersionWeight] = Field(..., max_length=32)
    sticky_by: Literal["tenant_id"] | None = None

    @field_validator("versions")
    @classmethod
    def _weights_sum(cls, v: list[VersionWeight]) -> list[VersionWeight]:
        if not v:
            raise ValueError("at least one version required")
        total = sum(x.weight for x in v)
        if total != 100:
            raise ValueError(f"version weights must sum to 100, got {total}")
        return v

    @model_validator(mode="after")
    def _strategy_invariants(self) -> Self:
        weights = [item.weight for item in self.versions]
        version_names = [item.version for item in self.versions]
        if len(set(version_names)) != len(version_names):
            raise ValueError("routing policy versions must be unique")

        if self.strategy == RoutingStrategy.SINGLE:
            if len(self.versions) != 1 or weights != [100]:
                raise ValueError("single routing requires exactly one version at weight 100")
            if self.sticky_by is not None:
                raise ValueError("single routing does not accept sticky_by")

        if self.strategy == RoutingStrategy.AB:
            if len(self.versions) != 2 or weights != [50, 50]:
                raise ValueError("ab routing requires exactly two versions weighted 50/50")
            if self.sticky_by != "tenant_id":
                raise ValueError("ab routing requires sticky_by='tenant_id'")

        if self.strategy == RoutingStrategy.CANARY:
            ordered = sorted(weights)
            if len(ordered) != 2 or not (1 <= ordered[0] <= 20 and 80 <= ordered[1] <= 99):
                raise ValueError("canary routing requires two non-zero versions split between 80/20 and 99/1")

        return self
