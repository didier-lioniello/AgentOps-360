"""FastAPI application entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.responses import Response
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from api.auth import authenticate, validate_auth_configuration
from api.routes import agents, health, invoke, traces
from api.routes import routing as routing_routes
from core.tracing import setup_tracing
from db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_auth_configuration()
    setup_tracing(service_name="agentops-api")
    # Schema initialization is part of startup. Failing fast avoids serving an
    # apparently healthy API after an incomplete or invalid DDL migration.
    await init_db()
    yield


app = FastAPI(
    title="AgentOps-360",
    description="Reference implementation of an LLM agent control plane",
    version="0.1.0",
    lifespan=lifespan,
)

FastAPIInstrumentor.instrument_app(app)

app.include_router(health.router, tags=["health"])
app.include_router(agents.router, prefix="/v1/agents", tags=["agents"])
app.include_router(routing_routes.router, prefix="/v1/routing", tags=["routing"])
app.include_router(invoke.router, prefix="/v1/invoke", tags=["invoke"])
app.include_router(traces.router, prefix="/v1/traces", tags=["traces"])


@app.get("/metrics", include_in_schema=False)
def metrics_endpoint(_claims: dict = Depends(authenticate)) -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
