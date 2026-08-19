"""Scheduled evaluation worker.

Each cycle reads active agent versions with a configured PostgreSQL dataset. For every
(agent, version, dataset) job it:

1. Loads the manifest + dataset.
2. Runs every item through the live invoker.
3. Scores with semantic_similarity + LLM-judge from EvalStack-style metrics.
4. Bootstraps CIs.
5. Persists `eval_runs` row.
6. Compares to the previous run; if regressed > tolerance with non-overlapping CIs,
   logs a structured WARNING that an alerting integration can route to PagerDuty/Slack.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import random
import uuid
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.invoker import Invoker
from db import SessionLocal
from eval.bootstrap import bootstrap_ci
from eval.metrics import external_evaluation_enabled, llm_judge, semantic_similarity
from models.invocation import InvocationRequest

log = structlog.get_logger("eval_worker")
INTERVAL_SEC = int(os.getenv("EVAL_INTERVAL_SEC", "3600"))
TOLERANCE = float(os.getenv("EVAL_REGRESSION_TOLERANCE", "0.03"))
SAMPLE_LIMIT = int(os.getenv("EVAL_MAX_ITEMS", "50"))


METRICS = {
    "semantic_similarity": semantic_similarity,
    "llm_judge": llm_judge,
}


async def _list_jobs() -> list[dict[str, Any]]:
    """Returns one job per (agent, latest active version) that has an attached dataset."""
    async with SessionLocal() as session:
        result = await session.execute(
            text("""
            SELECT DISTINCT ON (a.name) a.name AS agent_name, a.version AS agent_version,
                   a.manifest->>'eval_dataset' AS dataset_name
            FROM agents a
            WHERE a.status = 'active'
              AND a.manifest->>'eval_dataset' IS NOT NULL
            ORDER BY a.name, a.created_at DESC
        """)
        )
        agent_rows = list(result.mappings().all())

    jobs = []
    async with SessionLocal() as session:
        for row in agent_rows:
            ds = await session.execute(
                text("SELECT id FROM golden_datasets WHERE agent_name=:a AND name=:n"),
                {"a": row["agent_name"], "n": row["dataset_name"]},
            )
            ds_row = ds.mappings().first()
            if ds_row:
                jobs.append({**dict(row), "dataset_id": str(ds_row["id"])})
    return jobs


async def _load_dataset(dataset_id: str) -> list[dict[str, Any]]:
    async with SessionLocal() as session:
        result = await session.execute(
            text("SELECT items FROM golden_datasets WHERE id=:i"),
            {"i": dataset_id},
        )
        row = result.mappings().first()
        if not row:
            return []
        items = row["items"]
        if isinstance(items, str):
            items = json.loads(items)
        return items


async def _previous_run(agent_name: str, agent_version: str) -> dict[str, Any] | None:
    async with SessionLocal() as session:
        result = await session.execute(
            text("""
                SELECT aggregate, ci FROM eval_runs
                WHERE agent_name=:a AND agent_version=:v
                ORDER BY created_at DESC LIMIT 1
            """),
            {"a": agent_name, "v": agent_version},
        )
        row = result.mappings().first()
        if not row:
            return None
        agg = row["aggregate"] if isinstance(row["aggregate"], dict) else json.loads(row["aggregate"])
        ci = row["ci"] if isinstance(row["ci"], dict) else json.loads(row["ci"])
        return {"aggregate": agg, "ci": ci}


def _detect_regression(
    prev: dict[str, Any] | None, curr_agg: dict[str, float], curr_ci: dict[str, list[float]]
) -> list[dict[str, Any]]:
    if not prev:
        return []
    findings = []
    for metric, curr_mean in curr_agg.items():
        prev_mean = float(prev["aggregate"].get(metric, curr_mean))
        prev_ci = list(prev["ci"].get(metric, [prev_mean, prev_mean]))
        cci = curr_ci.get(metric, [curr_mean, curr_mean])
        delta = curr_mean - prev_mean
        ci_separable = cci[1] < prev_ci[0]
        significant = delta < -TOLERANCE and ci_separable
        if significant:
            findings.append(
                {
                    "metric": metric,
                    "delta": delta,
                    "prev_mean": prev_mean,
                    "curr_mean": curr_mean,
                    "prev_ci": prev_ci,
                    "curr_ci": cci,
                }
            )
    return findings


async def _invoke_item(
    invoker: Invoker,
    session: AsyncSession,
    job: dict[str, Any],
    item: dict[str, Any],
) -> tuple[str | None, bool]:
    """Invoke and commit one eval item; return ``(output, failed)``."""
    req = InvocationRequest(agent=job["agent_name"], input=item["input"])
    try:
        result = await invoker.invoke("__eval__", req, version=job["agent_version"])
        await session.commit()
    except Exception as exc:
        await session.rollback()
        log.warn(
            "eval.invoke_error",
            error_type=type(exc).__name__,
            item=item.get("id"),
        )
        return None, True

    if result.status != "ok":
        log.warn(
            "eval.invoke_unsuccessful",
            status=result.status,
            item=item.get("id"),
        )
        return None, True
    return result.output, False


def _score_item(
    actual: str,
    expected: str,
    item: dict[str, Any],
) -> tuple[dict[str, float], bool]:
    """Return only valid metric scores and whether any metric failed."""
    scores: dict[str, float] = {}
    had_error = False
    for name, fn in METRICS.items():
        try:
            score = float(fn(actual, expected, item))
            if not math.isfinite(score) or not 0.0 <= score <= 1.0:
                raise ValueError("metric returned a score outside [0, 1]")
            scores[name] = score
        except Exception as exc:
            had_error = True
            log.warn(
                "eval.metric_error",
                metric=name,
                error_type=type(exc).__name__,
                item=item.get("id"),
            )
    return scores, had_error


async def run_one_job(job: dict[str, Any]) -> None:
    if not external_evaluation_enabled():
        log.warn("eval.external_data_disabled", agent=job["agent_name"])
        return

    items = await _load_dataset(job["dataset_id"])
    if not items:
        log.warn("eval.empty_dataset", **job)
        return

    if len(items) > SAMPLE_LIMIT:
        items = random.sample(items, SAMPLE_LIMIT)

    n_errors = 0
    per_metric: dict[str, list[float]] = {k: [] for k in METRICS}

    async with SessionLocal() as session:
        invoker = Invoker(session)
        for item in items:
            actual, invoke_failed = await _invoke_item(invoker, session, job, item)
            if invoke_failed or actual is None:
                n_errors += 1
                continue
            scores, metric_failed = _score_item(actual, item["expected"], item)
            if metric_failed:
                n_errors += 1
            for name, score in scores.items():
                per_metric[name].append(score)

    aggregate = {k: sum(v) / len(v) for k, v in per_metric.items() if v}
    ci = {k: list(bootstrap_ci(v)) for k, v in per_metric.items() if v}

    prev = await _previous_run(job["agent_name"], job["agent_version"])
    regressions = _detect_regression(prev, aggregate, ci)

    async with SessionLocal() as session:
        await session.execute(
            text("""
            INSERT INTO eval_runs
              (id, agent_name, agent_version, dataset_id, aggregate, ci, n_items, n_errors)
            VALUES
              (:id, :a, :v, :d, :agg, :ci, :n, :e)
        """),
            {
                "id": str(uuid.uuid4()),
                "a": job["agent_name"],
                "v": job["agent_version"],
                "d": job["dataset_id"],
                "agg": json.dumps(aggregate),
                "ci": json.dumps(ci),
                "n": len(items),
                "e": n_errors,
            },
        )
        await session.commit()

    from core.telemetry import metrics

    metrics.eval_runs_total.labels(job["agent_name"], job["agent_version"]).inc()

    if regressions:
        log.warn(
            "eval.regression_detected",
            agent=job["agent_name"],
            version=job["agent_version"],
            findings=regressions,
        )
    else:
        log.info("eval.run_ok", agent=job["agent_name"], version=job["agent_version"], aggregate=aggregate)


async def main() -> None:
    log.info("eval_worker.start", interval_sec=INTERVAL_SEC)
    if not external_evaluation_enabled():
        log.error("eval_worker.disabled", reason="external evaluation requires explicit opt-in")
        return
    while True:
        try:
            jobs = await _list_jobs()
            log.info("eval_worker.cycle", n_jobs=len(jobs))
            for job in jobs:
                await run_one_job(job)
        except Exception as exc:
            log.error("eval_worker.error", error_type=type(exc).__name__)
        await asyncio.sleep(INTERVAL_SEC)


if __name__ == "__main__":
    asyncio.run(main())
