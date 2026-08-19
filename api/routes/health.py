"""Liveness + readiness probes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db, get_redis

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@router.get("/ready")
async def ready(response: Response, db: AsyncSession = Depends(get_db)) -> dict:
    checks = {"db": False, "redis": False}
    try:
        result = await db.execute(
            text(
                "SELECT to_regclass('public.agents') IS NOT NULL "
                "AND to_regclass('public.invocations') IS NOT NULL "
                "AND to_regclass('public.routing_policies') IS NOT NULL "
                "AND to_regclass('public.cost_rollups_daily') IS NOT NULL "
                "AND to_regclass('public.golden_datasets') IS NOT NULL "
                "AND to_regclass('public.eval_runs') IS NOT NULL "
                "AND to_regclass('public.tenants') IS NOT NULL"
            )
        )
        checks["db"] = bool(result.scalar())
    except Exception:
        pass
    try:
        r = get_redis()
        await r.ping()
        checks["redis"] = True
    except Exception:
        pass
    is_ready = all(checks.values())
    response.status_code = status.HTTP_200_OK if is_ready else status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ready" if is_ready else "degraded", "checks": checks}
