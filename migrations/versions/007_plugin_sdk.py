"""
Plugin SDK & Extension Framework.

Adds: plugin_installations, plugin_permissions, plugin_health_log,
plugin_secrets, plugin_storage, plugin_ui_extensions.

marketplace_items/marketplace_versions/marketplace_dependencies/
marketplace_assets (all pre-existing, from migration 006) stay the global
plugin catalog, unchanged. plugin_installations is the new per-org
activation-state table — the direct analog of how marketplace_installs
already tracks per-org install events but carries none of the
enabled/disabled/config/approval state a running plugin needs.

Matches 006's up(conn)/down(conn) convention (not real Alembic — the
upstream 001-004 revision chain is already broken, out of scope to repair
here; see 005's docstring for the full history of that decision).
"""

SQL_UP = """
CREATE TABLE IF NOT EXISTS plugin_installations (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id      UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    marketplace_item_id  TEXT NOT NULL REFERENCES marketplace_items(id) ON DELETE CASCADE,
    plugin_id            VARCHAR(80) NOT NULL,
    version              VARCHAR(30) NOT NULL,
    status               VARCHAR(20) NOT NULL DEFAULT 'installed'
                         CHECK (status IN ('installed','enabled','disabled','failed','uninstalled')),
    approved             BOOLEAN NOT NULL DEFAULT false,
    config               JSONB NOT NULL DEFAULT '{}',
    manifest             JSONB NOT NULL DEFAULT '{}',
    installed_by         UUID,
    installed_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
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

SQL_DOWN = """
DROP TABLE IF EXISTS plugin_ui_extensions;
DROP TABLE IF EXISTS plugin_storage;
DROP TABLE IF EXISTS plugin_secrets;
DROP TABLE IF EXISTS plugin_health_log;
DROP TABLE IF EXISTS plugin_permissions;
DROP TABLE IF EXISTS plugin_installations;
"""
# Does not touch marketplace_items/marketplace_versions/marketplace_assets/
# marketplace_dependencies — those predate this revision (migration 006)
# and are only read by the Plugin SDK, never modified by it.


def up(conn):
    conn.execute(SQL_UP)


def down(conn):
    conn.execute(SQL_DOWN)
