"""
AgentRegistry — versioned manifest store.

Manifests are immutable: once a (name, version) is published, the only allowed mutation
is `status` (active → deprecated → archived). Re-publishing the same version is rejected.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from models.agent import AgentManifest, AgentRecord, AgentStatus


class RegistryError(Exception):
    pass


class AgentRegistry:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def publish(self, manifest: AgentManifest) -> AgentRecord:
        existing = await self.get(manifest.name, manifest.version)
        if existing:
            raise RegistryError(f"version already published: {manifest.name}@{manifest.version}")

        result = await self.session.execute(
            text("""
                INSERT INTO agents (name, version, manifest)
                VALUES (:name, :version, :manifest)
                RETURNING id, created_at
            """),
            {
                "name": manifest.name,
                "version": manifest.version,
                "manifest": json.dumps(manifest.model_dump(by_alias=True)),
            },
        )
        row = result.mappings().first()
        return AgentRecord(
            id=str(row["id"]),
            name=manifest.name,
            version=manifest.version,
            manifest=manifest,
            status=AgentStatus.ACTIVE,
            created_at=row["created_at"],
        )

    async def get(self, name: str, version: str) -> AgentRecord | None:
        result = await self.session.execute(
            text(
                "SELECT id, name, version, manifest, status, created_at FROM agents "
                "WHERE name=:n AND version=:v"
            ),
            {"n": name, "v": version},
        )
        row = result.mappings().first()
        return self._row_to_record(row) if row else None

    async def list_versions(self, name: str) -> list[AgentRecord]:
        result = await self.session.execute(
            text(
                "SELECT id, name, version, manifest, status, created_at FROM agents "
                "WHERE name=:n ORDER BY created_at DESC"
            ),
            {"n": name},
        )
        return [self._row_to_record(r) for r in result.mappings().all()]

    async def list_agents(self) -> list[str]:
        result = await self.session.execute(text("SELECT DISTINCT name FROM agents ORDER BY name"))
        return [r[0] for r in result.all()]

    async def set_status(self, name: str, version: str, status: AgentStatus) -> None:
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:agent))"),
            {"agent": name},
        )
        record = await self.get(name, version)
        if record is None:
            raise RegistryError(f"unknown agent version: {name}@{version}")
        self.validate_status_transition(record.status, status)
        if record.status == status:
            return
        if status == AgentStatus.ARCHIVED and await self._is_routed(name, version):
            raise RegistryError(
                f"cannot archive a version referenced by the routing policy: {name}@{version}"
            )
        await self.session.execute(
            text("UPDATE agents SET status=:s WHERE name=:n AND version=:v"),
            {"s": status.value, "n": name, "v": version},
        )

    async def _is_routed(self, name: str, version: str) -> bool:
        result = await self.session.execute(
            text("""
                SELECT EXISTS (
                    SELECT 1
                    FROM routing_policies AS rp
                    CROSS JOIN LATERAL jsonb_array_elements(
                        COALESCE(rp.policy->'versions', '[]'::jsonb)
                    ) AS entries(entry)
                    WHERE rp.agent_name=:name
                      AND entry->>'version'=:version
                )
            """),
            {"name": name, "version": version},
        )
        return bool(result.scalar())

    @staticmethod
    def validate_status_transition(current: AgentStatus, target: AgentStatus) -> None:
        """Enforce the one-way active -> deprecated -> archived lifecycle."""
        if current == target:
            return
        allowed = {
            AgentStatus.ACTIVE: AgentStatus.DEPRECATED,
            AgentStatus.DEPRECATED: AgentStatus.ARCHIVED,
        }
        if allowed.get(current) != target:
            raise RegistryError(f"invalid status transition: {current.value} -> {target.value}")

    @staticmethod
    def _row_to_record(row: Any) -> AgentRecord:
        manifest_data = row["manifest"]
        if isinstance(manifest_data, str):
            manifest_data = json.loads(manifest_data)
        return AgentRecord(
            id=str(row["id"]),
            name=row["name"],
            version=row["version"],
            manifest=AgentManifest.model_validate(manifest_data),
            status=AgentStatus(row["status"]),
            created_at=row["created_at"],
        )
