"""
009_app_builder — AI Business App Builder tables.

Adds:
  app_builder_apps      — one record per generated business application,
                          scoped to org_id (multi-tenant, RLS-safe).
  app_builder_versions  — immutable audit trail of every AI modification;
                          supports rollback display and incremental editing.

All org-scoped columns are intentionally named `organization_id` to match
the RLS GUC convention already used by organisations/members/usage_records.
"""
from __future__ import annotations

import asyncpg


async def upgrade(conn: asyncpg.Connection) -> None:
    # ── app_builder_apps ──────────────────────────────────────────────────────
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS app_builder_apps (
            id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id  UUID        NOT NULL,
            created_by       UUID        NOT NULL,
            name             TEXT        NOT NULL,
            description      TEXT,
            spec             JSONB       NOT NULL DEFAULT '{}',
            build_status     TEXT        NOT NULL DEFAULT 'pending'
                             CHECK (build_status IN
                                   ('pending','planning','building','ready','failed')),
            build_result     JSONB       NOT NULL DEFAULT '{}',
            build_warnings   JSONB       NOT NULL DEFAULT '[]',
            include_automation BOOLEAN   NOT NULL DEFAULT false,
            canvas_id        UUID,
            workflow_ids     UUID[]      NOT NULL DEFAULT '{}',
            agent_ids        UUID[]      NOT NULL DEFAULT '{}',
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS aba_org_idx ON app_builder_apps(organization_id)"
    )
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS aba_created_by_idx ON app_builder_apps(created_by)"
    )

    # ── app_builder_versions ─────────────────────────────────────────────────
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS app_builder_versions (
            id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            app_id           UUID        NOT NULL
                             REFERENCES app_builder_apps(id) ON DELETE CASCADE,
            organization_id  UUID        NOT NULL,
            version_number   INTEGER     NOT NULL,
            label            TEXT        NOT NULL,
            spec_snapshot    JSONB       NOT NULL,
            change_summary   TEXT,
            created_by       UUID        NOT NULL,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS abv_app_idx ON app_builder_versions(app_id)"
    )
    await conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS abv_app_version_uidx "
        "ON app_builder_versions(app_id, version_number)"
    )


async def downgrade(conn: asyncpg.Connection) -> None:
    await conn.execute("DROP TABLE IF EXISTS app_builder_versions")
    await conn.execute("DROP TABLE IF EXISTS app_builder_apps")
