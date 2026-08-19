"""
Router — picks an agent version per the routing policy.

Strategies:
- single:   one version, no split
- weighted: pure weighted random
- canary:   weighted, but the convention is one >=80% stable + one small canary
- ab:       sticky-by-tenant so a given tenant lands on the same arm

Sticky routing uses MD5 of (sticky_key || agent_name) → bucket on [0,100). This is
deterministic, so the same tenant always sees the same arm without external state.
"""

from __future__ import annotations

import hashlib
import json
import random

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from models.routing import RoutingPolicy, RoutingStrategy


class RouterError(Exception):
    pass


class Router:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_policy(self, agent: str) -> RoutingPolicy | None:
        result = await self.session.execute(
            text("SELECT policy FROM routing_policies WHERE agent_name=:a"),
            {"a": agent},
        )
        row = result.mappings().first()
        if not row:
            return None
        data = row["policy"]
        if isinstance(data, str):
            data = json.loads(data)
        return RoutingPolicy.model_validate(data)

    async def upsert_policy(self, policy: RoutingPolicy) -> None:
        # Serialize policy changes with status transitions for this agent. This
        # closes the race between validating a version and archiving it.
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:agent))"),
            {"agent": policy.agent},
        )
        versions = [item.version for item in policy.versions]
        result = await self.session.execute(
            text("SELECT version, status FROM agents WHERE name=:agent AND version = ANY(:versions)"),
            {"agent": policy.agent, "versions": versions},
        )
        rows = list(result.mappings().all())
        found = {row["version"] for row in rows}
        missing = sorted(set(versions) - found)
        if missing:
            raise RouterError(f"unknown versions in routing policy: {', '.join(missing)}")
        archived = sorted(row["version"] for row in rows if row["status"] == "archived")
        if archived:
            raise RouterError(f"archived versions cannot be routed: {', '.join(archived)}")

        await self.session.execute(
            text("""
                INSERT INTO routing_policies (agent_name, policy, updated_at)
                VALUES (:a, :p, NOW())
                ON CONFLICT (agent_name) DO UPDATE
                  SET policy = EXCLUDED.policy, updated_at = NOW()
            """),
            {"a": policy.agent, "p": json.dumps(policy.model_dump())},
        )

    def select_version(self, policy: RoutingPolicy, sticky_key: str | None = None) -> str:
        if policy.strategy == RoutingStrategy.SINGLE:
            return policy.versions[0].version

        if policy.sticky_by and sticky_key:
            return self._sticky_select(policy, sticky_key)

        return self._weighted_random(policy)

    @staticmethod
    def _weighted_random(policy: RoutingPolicy) -> str:
        r = random.uniform(0, 100)
        acc = 0.0
        for vw in policy.versions:
            acc += vw.weight
            if r <= acc:
                return vw.version
        return policy.versions[-1].version

    @staticmethod
    def _sticky_select(policy: RoutingPolicy, key: str) -> str:
        digest = hashlib.md5(f"{key}::{policy.agent}".encode()).hexdigest()
        bucket = int(digest[:8], 16) % 100  # [0, 99]
        acc = 0
        for vw in policy.versions:
            acc += vw.weight
            if bucket < acc:
                return vw.version
        return policy.versions[-1].version

    async def resolve(
        self, agent_name: str, default_version: str | None = None, sticky_key: str | None = None
    ) -> str:
        """Returns the version string to invoke. Falls back to default_version
        if no policy is registered for this agent."""
        policy = await self.get_policy(agent_name)
        if policy is None:
            if default_version is None:
                raise RouterError(f"no routing policy and no default version for {agent_name!r}")
            return default_version
        return self.select_version(policy, sticky_key=sticky_key)
