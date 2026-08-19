"""
Cost aggregator worker.

Periodically rolls up `invocations` into `cost_rollups_daily`. Idempotent:
recomputes the most recent N days every cycle and upserts.
"""

from __future__ import annotations

import asyncio
import os

import structlog
from sqlalchemy import text

from db import SessionLocal

log = structlog.get_logger("cost_aggregator")
INTERVAL_SEC = int(os.getenv("COST_ROLLUP_INTERVAL_SEC", "300"))
RECENT_DAYS = int(os.getenv("COST_ROLLUP_DAYS", "7"))


ROLLUP_SQL = """
WITH daily AS (
    SELECT
        tenant_id,
        agent_name,
        agent_version,
        DATE(created_at AT TIME ZONE 'UTC') AS day,
        COUNT(*) AS n_invocations,
        SUM(input_tokens) AS total_input,
        SUM(output_tokens) AS total_output,
        SUM(cost_usd) AS total_cost_usd,
        PERCENTILE_DISC(0.50) WITHIN GROUP (ORDER BY latency_ms) AS p50,
        PERCENTILE_DISC(0.95) WITHIN GROUP (ORDER BY latency_ms) AS p95,
        PERCENTILE_DISC(0.99) WITHIN GROUP (ORDER BY latency_ms) AS p99
    FROM invocations
    WHERE created_at >= NOW() - (:days || ' days')::interval
    GROUP BY tenant_id, agent_name, agent_version, day
)
INSERT INTO cost_rollups_daily AS r
  (tenant_id, agent_name, agent_version, day, n_invocations,
   total_input, total_output, total_cost_usd, p50_latency_ms, p95_latency_ms, p99_latency_ms)
SELECT * FROM daily
ON CONFLICT (tenant_id, agent_name, agent_version, day) DO UPDATE SET
  n_invocations = EXCLUDED.n_invocations,
  total_input = EXCLUDED.total_input,
  total_output = EXCLUDED.total_output,
  total_cost_usd = EXCLUDED.total_cost_usd,
  p50_latency_ms = EXCLUDED.p50_latency_ms,
  p95_latency_ms = EXCLUDED.p95_latency_ms,
  p99_latency_ms = EXCLUDED.p99_latency_ms;
"""


async def rollup_once(days: int = RECENT_DAYS) -> int:
    async with SessionLocal() as session:
        result = await session.execute(text(ROLLUP_SQL), {"days": days})
        await session.commit()
        return result.rowcount or 0


async def main() -> None:
    log.info("cost_aggregator.start", interval_sec=INTERVAL_SEC, recent_days=RECENT_DAYS)
    while True:
        try:
            n = await rollup_once()
            log.info("cost_aggregator.cycle", upserted_rows=n)
        except Exception as exc:
            log.error("cost_aggregator.error", error_type=type(exc).__name__)
        await asyncio.sleep(INTERVAL_SEC)


if __name__ == "__main__":
    asyncio.run(main())
