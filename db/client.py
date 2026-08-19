"""Async SQLAlchemy engine + session factory."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://agentops:agentops@localhost:5432/agentops",
)

engine = create_async_engine(DATABASE_URL, pool_pre_ping=True, pool_size=10, max_overflow=20)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@asynccontextmanager
async def get_session():
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """Run the schema.sql at boot. Idempotent."""
    from pathlib import Path

    schema_path = Path(__file__).parent / "schema.sql"
    if not schema_path.exists():
        return
    sql = schema_path.read_text()
    async with engine.begin() as conn:
        from sqlalchemy import text

        for stmt in [s for s in sql.split(";") if s.strip()]:
            await conn.execute(text(stmt))
