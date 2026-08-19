"""Prometheus metrics — counters, histograms, gauges."""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram


class _Metrics:
    invocations_total = Counter(
        "agentops_invocations_total",
        "Total number of agent invocations",
        ["agent", "version", "status"],
    )
    invocation_latency_ms = Histogram(
        "agentops_invocation_latency_ms",
        "Invocation latency in milliseconds",
        ["agent", "version"],
        buckets=(50, 100, 250, 500, 1000, 2500, 5000, 10000, 30000),
    )
    invocation_tokens = Counter(
        "agentops_invocation_tokens_total",
        "Cumulative tokens (input + output)",
        ["agent", "version", "kind"],  # kind = input | output
    )
    rate_limited_total = Counter(
        "agentops_rate_limited_total",
        "Requests rejected by rate limit",
    )
    eval_runs_total = Counter(
        "agentops_eval_runs_total",
        "Number of eval runs completed",
        ["agent", "version"],
    )
    registry_active_versions = Gauge(
        "agentops_registry_active_versions",
        "Active versions per agent",
        ["agent"],
    )


metrics = _Metrics()
