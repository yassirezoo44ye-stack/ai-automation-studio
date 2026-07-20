"""
Integration SDK schema — idempotent DDL, boot-time init like every other
subsystem in this codebase (see app/tenancy/schema.py for the convention
this follows). References organizations/users, so must init after
init_tenancy_schema().
"""
from __future__ import annotations

import logging

import asyncpg

log = logging.getLogger(__name__)

INTEGRATIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS integrations (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id  UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    provider_id      VARCHAR(80) NOT NULL,
    provider_type    VARCHAR(20) NOT NULL,
    status           VARCHAR(20) NOT NULL DEFAULT 'connected'
                     CHECK (status IN ('disconnected','connected','syncing','error','degraded')),
    granted_scopes   TEXT[] NOT NULL DEFAULT '{}',
    connected_by     UUID REFERENCES users(id) ON DELETE SET NULL,
    connected_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_sync_at     TIMESTAMPTZ,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (organization_id, provider_id)
);
CREATE INDEX IF NOT EXISTS idx_integrations_org ON integrations(organization_id);

CREATE TABLE IF NOT EXISTS integration_credentials (
    provider_id       VARCHAR(80) NOT NULL,
    organization_id   UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    provider_type     VARCHAR(20) NOT NULL,
    secrets_encrypted TEXT NOT NULL,
    metadata          JSONB NOT NULL DEFAULT '{}',
    expires_at        TIMESTAMPTZ,
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (provider_id, organization_id)
);

CREATE TABLE IF NOT EXISTS integration_sync_runs (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    provider_id      VARCHAR(80) NOT NULL,
    organization_id  UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    status           VARCHAR(20) NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending','running','succeeded','failed')),
    items_synced     INTEGER NOT NULL DEFAULT 0,
    message          TEXT,
    cursor           TEXT,
    started_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at      TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_integration_sync_runs_lookup
    ON integration_sync_runs(provider_id, organization_id, started_at DESC);

CREATE TABLE IF NOT EXISTS integration_webhook_events (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    provider_id      VARCHAR(80) NOT NULL,
    organization_id  UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    dedup_key        VARCHAR(64) NOT NULL UNIQUE,
    received_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_integration_webhook_events_org ON integration_webhook_events(organization_id, received_at DESC);
"""


async def init_integrations_schema(conn: asyncpg.Connection) -> None:
    await conn.execute(INTEGRATIONS_SCHEMA)
    log.info("integrations schema initialised")
