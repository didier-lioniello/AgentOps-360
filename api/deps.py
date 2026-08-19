"""FastAPI dependencies — DB session + redis + rate limiter."""

from __future__ import annotations

import os
import time

import redis.asyncio as aioredis
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from db.client import SessionLocal

_redis: aioredis.Redis | None = None
RATE_LIMIT_PER_MIN = int(os.getenv("RATE_LIMIT_PER_MIN", "60"))


async def get_db() -> AsyncSession:
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(
            os.getenv("REDIS_URL", "redis://localhost:6379/0"),
            decode_responses=True,
        )
    return _redis


async def enforce_rate_limit(
    tenant_id: str, redis: aioredis.Redis, limit: int = RATE_LIMIT_PER_MIN, window_sec: int = 60
) -> None:
    """
    Sliding-window rate limit.
    Uses a Redis sorted set keyed on tenant; each request is a member with score=now.
    Trim entries older than `now - window_sec`, then count.
    """
    key = f"rl:{tenant_id}"
    now = time.time()
    pipe = redis.pipeline()
    pipe.zadd(key, {f"{now}-{int(now * 1e6) % 1_000_000}": now})
    pipe.zremrangebyscore(key, 0, now - window_sec)
    pipe.zcard(key)
    pipe.expire(key, window_sec * 2)
    _, _, count, _ = await pipe.execute()
    if count > limit:
        from core.telemetry import metrics

        metrics.rate_limited_total.inc()
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"rate limit exceeded: {count}/{limit} in {window_sec}s",
        )
