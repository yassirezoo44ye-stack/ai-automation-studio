"""
010_app_builder_async — Async build state + RLS for App Builder.

Adds progress-tracking columns to app_builder_apps so the build job can
report step-by-step progress without blocking the HTTP connection, and
enables Row Level Security on both App Builder tables so the existing
Postgres GUC mechanism (already used by tenancy/billing) provides
database-level cross-tenant isolation.

Idempotent: all DDL uses IF NOT EXISTS / IF EXISTS guards — safe to run
on startup every boot even when the columns already exist.
"""
from __future__ import annotations

import asyncpg


async def upgrade(conn: asyncpg.Connection) -> None:
    # ── Extend app_builder_apps with async build state ────────────────────
    for sql in (
        "ALTER TABLE app_builder_apps ADD COLUMN IF NOT EXISTS "
        "progress INTEGER NOT NULL DEFAULT 0",

        "ALTER TABLE app_builder_apps ADD COLUMN IF NOT EXISTS "
        "current_step TEXT NOT NULL DEFAULT 'pending'",

        "ALTER TABLE app_builder_apps ADD COLUMN IF NOT EXISTS "
        "total_steps INTEGER NOT NULL DEFAULT 12",

        "ALTER TABLE app_builder_apps ADD COLUMN IF NOT EXISTS "
        "completed_steps INTEGER NOT NULL DEFAULT 0",

        "ALTER TABLE app_builder_apps ADD COLUMN IF NOT EXISTS "
        "error TEXT",

        "ALTER TABLE app_builder_apps ADD COLUMN IF NOT EXISTS "
        "started_at TIMESTAMPTZ",

        "ALTER TABLE app_builder_apps ADD COLUMN IF NOT EXISTS "
        "completed_at TIMESTAMPTZ",

        "ALTER TABLE app_builder_apps ADD COLUMN IF NOT EXISTS "
        "last_heartbeat_at TIMESTAMPTZ",

        "ALTER TABLE app_builder_apps ADD COLUMN IF NOT EXISTS "
        "retry_count INTEGER NOT NULL DEFAULT 0",

        "ALTER TABLE app_builder_apps ADD COLUMN IF NOT EXISTS "
        "job_id TEXT",
    ):
        try:
            await conn.execute(sql)
        except Exception:
            pass  # column may already exist on a fresh install that ran this migration

    # ── Fix build_status CHECK to include 'partial' ────────────────────────
    # The original 009 migration omitted 'partial' from the CHECK constraint
    # even though the service uses it — this corrects that silently.
    try:
        await conn.execute(
            "ALTER TABLE app_builder_apps "
            "DROP CONSTRAINT IF EXISTS app_builder_apps_build_status_check"
        )
    except Exception:
        pass
    try:
        await conn.execute("""
            ALTER TABLE app_builder_apps
            ADD CONSTRAINT app_builder_apps_build_status_check
            CHECK (build_status IN
                   ('pending', 'planning', 'building', 'ready', 'partial', 'failed'))
        """)
    except Exception:
        pass  # constraint already recreated by a previous run

    # ── Row Level Security on App Builder tables ───────────────────────────
    # Mirrors the pattern in app/tenancy/rls.py — the GUC
    # app.current_org_id must be set via acquire_scoped() for the policy
    # to filter rows; unscoped connections (the majority of app queries)
    # see all rows unchanged — additive defense-in-depth, not a blanket
    # rewrite of existing queries.
    for table, col in (
        ("app_builder_apps", "organization_id"),
        ("app_builder_versions", "organization_id"),
    ):
        exists = await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name=$1)",
            table,
        )
        if not exists:
            continue
        try:
            await conn.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            await conn.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
            await conn.execute(f"DROP POLICY IF EXISTS org_scoped ON {table}")
            await conn.execute(f"""
                CREATE POLICY org_scoped ON {table}
                USING (
                    nullif(current_setting('app.current_org_id', true), '') IS NULL
                    OR {col} = nullif(current_setting('app.current_org_id', true), '')::uuid
                )
                WITH CHECK (
                    nullif(current_setting('app.current_org_id', true), '') IS NULL
                    OR {col} = nullif(current_setting('app.current_org_id', true), '')::uuid
                )
            """)
        except Exception:
            pass  # best-effort, matching enable_scoped_rls() behaviour


async def downgrade(conn: asyncpg.Connection) -> None:
    # Remove RLS (leave tables intact)
    for table in ("app_builder_apps", "app_builder_versions"):
        try:
            await conn.execute(f"DROP POLICY IF EXISTS org_scoped ON {table}")
            await conn.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
        except Exception:
            pass

    # Remove new columns
    for col in (
        "progress", "current_step", "total_steps", "completed_steps",
        "error", "started_at", "completed_at", "last_heartbeat_at",
        "retry_count", "job_id",
    ):
        try:
            await conn.execute(
                f"ALTER TABLE app_builder_apps DROP COLUMN IF EXISTS {col}"
            )
        except Exception:
            pass
