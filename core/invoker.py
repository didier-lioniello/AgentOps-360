"""
Invoker — actually runs an agent.

- Loads manifest from registry
- Enforces guardrails (max_tokens, timeout)
- Calls the LLM via langchain_openai
- Captures token usage from the response
- Persists the InvocationRecord
- Emits OTel span + Prometheus metrics
- Optionally enqueues for offline eval
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from models.agent import AgentManifest, AgentStatus
from models.invocation import InvocationRequest, InvocationResult, TokenUsage

from .cost import CostCalculator
from .registry import AgentRegistry
from .telemetry import metrics
from .tracing import tracer


class InvocationError(Exception):
    pass


_REDACTED_CONTENT = "[redacted]"


def _content_storage_enabled() -> bool:
    return os.getenv("STORE_INVOCATION_CONTENT", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _content_for_storage(value: str) -> str:
    """Return raw content only after an explicit operator opt-in."""
    return value if _content_storage_enabled() else _REDACTED_CONTENT


class Invoker:
    def __init__(self, session: AsyncSession, cost_calc: CostCalculator | None = None):
        self.session = session
        self.registry = AgentRegistry(session)
        self.cost_calc = cost_calc or CostCalculator()

    async def invoke(self, tenant_id: str, req: InvocationRequest, version: str) -> InvocationResult:
        record = await self.registry.get(req.agent, version)
        if record is None:
            raise InvocationError(f"unknown agent version: {req.agent}@{version}")
        if record.status == AgentStatus.ARCHIVED:
            raise InvocationError(f"archived agent version cannot be invoked: {req.agent}@{version}")
        manifest = record.manifest

        invocation_id = str(uuid.uuid4())
        trace_id: str | None = None
        t0 = time.perf_counter()

        with tracer().start_as_current_span("invoke") as span:
            span.set_attribute("agent.name", req.agent)
            span.set_attribute("agent.version", version)
            ctx = span.get_span_context()
            trace_id = format(ctx.trace_id, "032x") if ctx and ctx.trace_id else None

            try:
                output, usage = await self._call_llm(manifest, req.input)
                latency_ms = int((time.perf_counter() - t0) * 1000)
                cost = self.cost_calc.cost(manifest.model, usage.input_tokens, usage.output_tokens)
                status = "ok"
                error = None
            except TimeoutError:
                output, usage = "", TokenUsage()
                latency_ms = manifest.guardrails.timeout_ms
                cost, status, error = 0.0, "timeout", "guardrail timeout"
            except Exception:
                output, usage = "", TokenUsage()
                latency_ms = int((time.perf_counter() - t0) * 1000)
                cost, status, error = 0.0, "error", "model provider invocation failed"

        await self._persist(
            invocation_id=invocation_id,
            tenant_id=tenant_id,
            agent=req.agent,
            version=version,
            input_text=req.input,
            output=output,
            status=status,
            error=error,
            usage=usage,
            cost=cost,
            latency_ms=latency_ms,
            trace_id=trace_id,
        )

        metrics.invocations_total.labels(req.agent, version, status).inc()
        metrics.invocation_latency_ms.labels(req.agent, version).observe(latency_ms)
        metrics.invocation_tokens.labels(req.agent, version, "input").inc(usage.input_tokens)
        metrics.invocation_tokens.labels(req.agent, version, "output").inc(usage.output_tokens)

        return InvocationResult(
            invocation_id=invocation_id,
            agent=req.agent,
            version=version,
            output=output,
            status=status,
            error=error,
            usage=usage,
            cost_usd=cost,
            latency_ms=latency_ms,
            trace_id=trace_id,
        )

    async def _call_llm(self, manifest: AgentManifest, prompt: str) -> tuple[str, TokenUsage]:
        llm = ChatOpenAI(
            model=manifest.model,
            temperature=manifest.temperature,
            max_tokens=manifest.guardrails.max_tokens,
            timeout=manifest.guardrails.timeout_ms / 1000.0,
        )
        msgs = [SystemMessage(content=manifest.system_prompt), HumanMessage(content=prompt)]
        resp = await asyncio.wait_for(
            llm.ainvoke(msgs),
            timeout=manifest.guardrails.timeout_ms / 1000.0,
        )

        content = resp.content if isinstance(resp.content, str) else str(resp.content)
        usage_meta = getattr(resp, "usage_metadata", None) or {}
        usage = TokenUsage(
            input_tokens=int(usage_meta.get("input_tokens", 0)),
            output_tokens=int(usage_meta.get("output_tokens", 0)),
        )
        return content, usage

    async def _persist(
        self,
        *,
        invocation_id: str,
        tenant_id: str,
        agent: str,
        version: str,
        input_text: str,
        output: str,
        status: str,
        error: str | None,
        usage: TokenUsage,
        cost: float,
        latency_ms: int,
        trace_id: str | None,
    ) -> None:
        await self.session.execute(
            text("""
                INSERT INTO invocations
                  (id, tenant_id, agent_name, agent_version, input, output, status, error,
                   input_tokens, output_tokens, cost_usd, latency_ms, trace_id)
                VALUES
                  (:id, :tenant_id, :agent, :version, :input, :output, :status, :error,
                   :input_tokens, :output_tokens, :cost, :latency, :trace_id)
            """),
            {
                "id": invocation_id,
                "tenant_id": tenant_id,
                "agent": agent,
                "version": version,
                "input": _content_for_storage(input_text),
                "output": _content_for_storage(output),
                "status": status,
                "error": error,
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "cost": cost,
                "latency": latency_ms,
                "trace_id": trace_id,
            },
        )
