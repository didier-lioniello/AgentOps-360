-- AgentOps-360 schema
-- One source of truth for agents, versions, invocations, and eval results.

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS tenants (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS agents (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name         TEXT NOT NULL,
    version      TEXT NOT NULL,
    manifest     JSONB NOT NULL,
    status       TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','deprecated','archived')),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (name, version)
);

CREATE INDEX IF NOT EXISTS idx_agents_name ON agents (name);
CREATE INDEX IF NOT EXISTS idx_agents_status ON agents (status);

CREATE TABLE IF NOT EXISTS routing_policies (
    agent_name   TEXT PRIMARY KEY,
    policy       JSONB NOT NULL,        -- canary | ab | weighted manifest
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS invocations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       TEXT NOT NULL,
    agent_name      TEXT NOT NULL,
    agent_version   TEXT NOT NULL,
    input           TEXT NOT NULL,
    output          TEXT,
    status          TEXT NOT NULL,            -- ok | error | timeout
    error           TEXT,
    input_tokens    INTEGER NOT NULL DEFAULT 0,
    output_tokens   INTEGER NOT NULL DEFAULT 0,
    cost_usd        NUMERIC(12,6) NOT NULL DEFAULT 0,
    latency_ms      INTEGER NOT NULL DEFAULT 0,
    trace_id        TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_inv_tenant_agent ON invocations (tenant_id, agent_name, created_at);
CREATE INDEX IF NOT EXISTS idx_inv_created ON invocations (created_at);

-- Pre-aggregated daily rollups (cost_aggregator worker fills this)
CREATE TABLE IF NOT EXISTS cost_rollups_daily (
    tenant_id       TEXT NOT NULL,
    agent_name      TEXT NOT NULL,
    agent_version   TEXT NOT NULL,
    day             DATE NOT NULL,
    n_invocations   INTEGER NOT NULL DEFAULT 0,
    total_input     BIGINT NOT NULL DEFAULT 0,
    total_output    BIGINT NOT NULL DEFAULT 0,
    total_cost_usd  NUMERIC(14,6) NOT NULL DEFAULT 0,
    p50_latency_ms  INTEGER,
    p95_latency_ms  INTEGER,
    p99_latency_ms  INTEGER,
    PRIMARY KEY (tenant_id, agent_name, agent_version, day)
);

CREATE TABLE IF NOT EXISTS golden_datasets (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_name   TEXT NOT NULL,
    name         TEXT NOT NULL,
    items        JSONB NOT NULL,        -- [{"input": ..., "expected": ..., "tags": [...]}, ...]
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (agent_name, name)
);

CREATE TABLE IF NOT EXISTS eval_runs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_name      TEXT NOT NULL,
    agent_version   TEXT NOT NULL,
    dataset_id      UUID NOT NULL REFERENCES golden_datasets(id),
    aggregate       JSONB NOT NULL,    -- {"metric": mean, ...}
    ci              JSONB NOT NULL,    -- {"metric": [lo, hi], ...}
    n_items         INTEGER NOT NULL,
    n_errors        INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_eval_runs ON eval_runs (agent_name, agent_version, created_at);

-- Convenience seed: dev tenant.
INSERT INTO tenants (id, name) VALUES ('acme', 'Acme Corp')
    ON CONFLICT (id) DO NOTHING;
