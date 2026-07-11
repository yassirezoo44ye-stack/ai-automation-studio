"""
Plugin SDK database schema — idempotent boot-time init, matching every
other *_schema.py module in this codebase (CREATE TABLE IF NOT EXISTS /
ADD COLUMN IF NOT EXISTS, safe to run on every boot).

marketplace_items/marketplace_versions/marketplace_dependencies/
marketplace_assets stay the global catalog (unchanged) — plugin_installations
is the new per-org ACTIVATION-state table, the direct analog of how
marketplace_installs already tracks per-org install events but carries none
of the enabled/disabled/config/approval state a running plugin needs.
"""
from __future__ import annotations

import logging

import asyncpg

log = logging.getLogger(__name__)

PLUGIN_SCHEMA = """
CREATE TABLE IF NOT EXISTS plugin_installations (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id      UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    marketplace_item_id  TEXT NOT NULL REFERENCES marketplace_items(id) ON DELETE CASCADE,
    plugin_id            VARCHAR(80) NOT NULL,
    version               VARCHAR(30) NOT NULL,
    status                VARCHAR(20) NOT NULL DEFAULT 'installed'
                          CHECK (status IN ('installed','enabled','disabled','failed','uninstalled')),
    approved              BOOLEAN NOT NULL DEFAULT false,
    config                JSONB NOT NULL DEFAULT '{}',
    manifest              JSONB NOT NULL DEFAULT '{}',
    installed_by          UUID,
    installed_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (organization_id, plugin_id)
);
CREATE INDEX IF NOT EXISTS idx_plugin_installs_org ON plugin_installations(organization_id);

CREATE TABLE IF NOT EXISTS plugin_permissions (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    installation_id   UUID NOT NULL REFERENCES plugin_installations(id) ON DELETE CASCADE,
    capability        VARCHAR(40) NOT NULL,
    granted           BOOLEAN NOT NULL DEFAULT false,
    UNIQUE (installation_id, capability)
);

CREATE TABLE IF NOT EXISTS plugin_health_log (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    installation_id   UUID NOT NULL REFERENCES plugin_installations(id) ON DELETE CASCADE,
    event             VARCHAR(20) NOT NULL CHECK (event IN ('load','unload','reload','error','tick')),
    message           TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_plugin_health_installation ON plugin_health_log(installation_id, created_at DESC);

CREATE TABLE IF NOT EXISTS plugin_secrets (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    installation_id   UUID NOT NULL REFERENCES plugin_installations(id) ON DELETE CASCADE,
    key               VARCHAR(80) NOT NULL,
    value_encrypted   TEXT NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (installation_id, key)
);

CREATE TABLE IF NOT EXISTS plugin_storage (
    installation_id   UUID NOT NULL REFERENCES plugin_installations(id) ON DELETE CASCADE,
    key               VARCHAR(200) NOT NULL,
    value             JSONB NOT NULL,
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (installation_id, key)
);

CREATE TABLE IF NOT EXISTS plugin_ui_extensions (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    installation_id   UUID NOT NULL REFERENCES plugin_installations(id) ON DELETE CASCADE,
    slot              VARCHAR(60) NOT NULL,
    component_ref     TEXT NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_plugin_ui_ext_installation ON plugin_ui_extensions(installation_id);
"""


async def init_plugins_schema(conn: asyncpg.Connection) -> None:
    await conn.execute(PLUGIN_SCHEMA)
    log.info("plugin SDK schema initialised")
