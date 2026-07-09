"""
Scoped PostgreSQL Row Level Security — defense-in-depth for the tables
where a cross-tenant leak would matter most.

Deliberately narrow: RLS is enabled on 5 tables (organizations,
organization_members, teams, usage_records, marketplace_installs), and the
policy only restricts queries that explicitly set the `app.current_org_id`
session GUC via `app.core.db.acquire_scoped()`. Every other connection in
the app (the overwhelming majority of ~30 routers) never sets that GUC, so
RLS is a no-op for them — this is intentional. It adds a real database-level
guarantee for TenancyService/UsageService without rewriting how the rest of
the app talks to Postgres.

FORCE ROW LEVEL SECURITY is required because the app's own DB role owns
these tables (it ran the CREATE TABLE statements) — Postgres exempts table
owners from RLS by default, so without FORCE the policy would silently do
nothing for the app's own connections.
"""
from __future__ import annotations

import logging

import asyncpg

log = logging.getLogger(__name__)

# (table, org_id_column) — organizations uses its own `id` as the tenant key.
# invoice_items and coupons/subscription_plans are deliberately excluded:
# invoice_items is a child row always accessed by joining through
# invoices.organization_id (which is RLS'd), and coupons/subscription_plans
# are global catalogs, not tenant data.
_RLS_TABLES: tuple[tuple[str, str], ...] = (
    ("organizations", "id"),
    ("organization_members", "organization_id"),
    ("teams", "organization_id"),
    ("usage_records", "organization_id"),
    ("marketplace_installs", "organization_id"),
    ("api_keys", "organization_id"),
    ("invoices", "organization_id"),
    ("payments", "organization_id"),
    ("payment_methods", "organization_id"),
    ("credits", "organization_id"),
    ("billing_events", "organization_id"),
)


async def enable_scoped_rls(conn: asyncpg.Connection) -> None:
    """
    Idempotent: safe to run on every boot. Skips tables that don't exist yet
    (e.g. a fresh install where a later migration hasn't run) rather than
    failing startup over an optional hardening step.
    """
    for table, col in _RLS_TABLES:
        exists = await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name=$1)",
            table,
        )
        if not exists:
            log.warning("RLS: table %s does not exist yet, skipping", table)
            continue
        try:
            await conn.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            await conn.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
            await conn.execute(f"DROP POLICY IF EXISTS org_scoped ON {table}")
            # nullif(...,'') matters: a pooled connection that has EVER run
            # acquire_scoped() has "touched" this custom GUC, so Postgres
            # resets it to '' (not NULL) once the SET LOCAL transaction
            # ends. A plain, never-scoped connection still reads NULL. The
            # policy must treat both the same as "unscoped" or a later
            # unscoped query on a reused connection gets `''::uuid` and
            # every query on that connection starts erroring.
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
            log.warning("RLS: failed to enable on %s (continuing)", table, exc_info=True)
    log.info("scoped RLS initialised on %d tables", len(_RLS_TABLES))
