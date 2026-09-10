"""
Flow Next — Unified Creation Model (Phase 1)

Adds the `flow_creations` table, which is a soft-reference catalogue that
links existing resources (apps, automations, canvases, devices) to a
discoverable, cross-org gallery without duplicating data.

Design decisions
────────────────
• `source_type` + `source_id` instead of strict FKs — the catalogue spans
  multiple tables (app_builder_apps, automation_definitions, design_canvases,
  devices) and cross-table FK references would couple the migration to every
  upstream schema.  The router validates ownership at write time.
• `visibility` default = 'private' — opt-in publishing, never accidental.
• No view_count / clone_count — event-based metrics come in a later phase.
• RLS is registered in app/tenancy/rls.py; the policy is applied by
  enable_scoped_rls() at boot time (idempotent).

Dependency: organizations(001), users(001)
"""

SQL_UP = """
CREATE TABLE IF NOT EXISTS flow_creations (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id     UUID        NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    created_by_user_id  UUID        REFERENCES users(id) ON DELETE SET NULL,
    type                VARCHAR(30) NOT NULL
                        CHECK (type IN ('APP','AGENT','WORKFLOW','AUTOMATION','TEMPLATE','DEVICE_WORKFLOW')),
    title               VARCHAR(200) NOT NULL,
    description         TEXT,
    visibility          VARCHAR(20) NOT NULL DEFAULT 'private'
                        CHECK (visibility IN ('private','public')),
    source_type         VARCHAR(30),
    source_id           UUID,
    thumbnail_url       TEXT,
    tags                TEXT[]      NOT NULL DEFAULT '{}',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Primary tenant-scoped index (list my org's creations)
CREATE INDEX IF NOT EXISTS ix_flow_creations_org
    ON flow_creations(organization_id, created_at DESC);

-- Public feed (only scans public rows)
CREATE INDEX IF NOT EXISTS ix_flow_creations_public
    ON flow_creations(created_at DESC)
    WHERE visibility = 'public';

-- Source lookup (find the creation card for a given resource)
CREATE INDEX IF NOT EXISTS ix_flow_creations_source
    ON flow_creations(source_type, source_id)
    WHERE source_id IS NOT NULL;
"""

SQL_DOWN = """
DROP TABLE IF EXISTS flow_creations CASCADE;
"""


async def up(conn) -> None:
    await conn.execute(SQL_UP)


async def down(conn) -> None:
    await conn.execute(SQL_DOWN)
