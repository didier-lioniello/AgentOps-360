"""OpenTelemetry tracing setup."""

from __future__ import annotations

import os

from opentelemetry import trace
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

try:
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
except ImportError:
    OTLPSpanExporter = None  # graceful in unit-test contexts


_provider_inited = False


def setup_tracing(service_name: str = "agentops-api") -> None:
    global _provider_inited
    if _provider_inited:
        return

    resource = Resource.create({SERVICE_NAME: service_name})
    provider = TracerProvider(resource=resource)

    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if endpoint and OTLPSpanExporter is not None:
        try:
            exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
            provider.add_span_processor(BatchSpanProcessor(exporter))
        except Exception:
            pass  # avoid crashing app boot if exporter is unreachable

    trace.set_tracer_provider(provider)
    _provider_inited = True


def tracer(name: str = "agentops"):
    return trace.get_tracer(name)
