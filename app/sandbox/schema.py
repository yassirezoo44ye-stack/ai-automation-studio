"""
Agent Sandbox database schema — idempotent boot-time init, matching every
other *_schema.py module in this codebase.

Two tables. No new permission-declaration table — sandbox_workers'/
sandbox_events' organization_id scoping is enough for RLS; the actual
permission/approval gate stays plugin_installations.approved +
plugin_permissions (Plugin SDK, unchanged), which SandboxManager reads
from directly to build a worker's SandboxLimits.
"""
from __future__ import annotations

import logging

import asyncpg

log = logging.getLogger(__name__)

SANDBOX_SCHEMA = """
CREATE TABLE IF NOT EXISTS sandbox_workers (
    id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id        UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    plugin_installation_id UUID NOT NULL REFERENCES plugin_installations(id) ON DELETE CASCADE,
    backend                VARCHAR(10) NOT NULL CHECK (backend IN ('docker','process')),
    status                 VARCHAR(10) NOT NULL DEFAULT 'starting'
                           CHECK (status IN ('starting','running','stopped','crashed')),
    pid_or_container_id    TEXT,
    started_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    stopped_at             TIMESTAMPTZ,
    cpu_seconds_used       DOUBLE PRECISION,
    memory_mb_peak         DOUBLE PRECISION,
    UNIQUE (plugin_installation_id)
);
CREATE INDEX IF NOT EXISTS idx_sandbox_workers_org ON sandbox_workers(organization_id);

CREATE TABLE IF NOT EXISTS sandbox_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    worker_id       UUID NOT NULL REFERENCES sandbox_workers(id) ON DELETE CASCADE,
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    event_type      VARCHAR(20) NOT NULL CHECK (event_type IN ('log','network','security','resource','lifecycle')),
    severity        VARCHAR(10) NOT NULL DEFAULT 'info' CHECK (severity IN ('info','warning','error')),
    message         TEXT,
    details         JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_sandbox_events_worker ON sandbox_events(worker_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sandbox_events_org_type ON sandbox_events(organization_id, event_type, created_at DESC);
"""


async def init_sandbox_schema(conn: asyncpg.Connection) -> None:
    await conn.execute(SANDBOX_SCHEMA)
    log.info("agent sandbox schema initialised")
