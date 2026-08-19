"""Read-side: invocations + cost rollups."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import authenticate
from api.deps import get_db

router = APIRouter()


@router.get("/invocations")
async def list_invocations(
    agent: str | None = None,
    version: str | None = None,
    limit: int = Query(default=50, le=500),
    claims: dict = Depends(authenticate),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    tenant_id = claims["tenant_id"]
    sql = """
        SELECT id, tenant_id, agent_name, agent_version, status, error,
               input_tokens, output_tokens, cost_usd, latency_ms, trace_id, created_at
        FROM invocations
        WHERE tenant_id = :tenant_id
    """
    params: dict[str, Any] = {"tenant_id": tenant_id, "limit": limit}
    if agent:
        sql += " AND agent_name = :agent"
        params["agent"] = agent
    if version:
        sql += " AND agent_version = :version"
        params["version"] = version
    sql += " ORDER BY created_at DESC LIMIT :limit"

    result = await db.execute(text(sql), params)
    return [dict(r) for r in result.mappings().all()]


@router.get("/cost/daily")
async def daily_cost(
    agent: str | None = None,
    days: int = Query(default=30, le=365),
    claims: dict = Depends(authenticate),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    tenant_id = claims["tenant_id"]
    sql = """
        SELECT day, agent_name, agent_version, n_invocations,
               total_input, total_output, total_cost_usd,
               p50_latency_ms, p95_latency_ms, p99_latency_ms
        FROM cost_rollups_daily
        WHERE tenant_id = :tenant_id
          AND day >= CURRENT_DATE - (:days || ' days')::interval
    """
    params: dict[str, Any] = {"tenant_id": tenant_id, "days": days}
    if agent:
        sql += " AND agent_name = :agent"
        params["agent"] = agent
    sql += " ORDER BY day DESC, agent_name, agent_version"

    result = await db.execute(text(sql), params)
    return [dict(r) for r in result.mappings().all()]
