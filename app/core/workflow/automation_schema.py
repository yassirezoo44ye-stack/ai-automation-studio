"""
Automation persistence schema — Phase 5 Gate 3.

Four tables:
  automation_definitions  — saved workflow blueprints
  automation_runs         — execution records (one per engine.WorkflowRun)
  automation_run_steps    — per-step records (one per engine.WorkflowStep)
  automation_approvals    — human-approval gate records

Design rules:
  • CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS — idempotent, no Alembic
  • ALTER TABLE … ADD COLUMN IF NOT EXISTS for forward-compatible schema evolution
  • No FK to organizations (follows app-builder convention — org_id is carried
    by every row for application-layer + RLS scoping, not a PG FK)
  • PostgreSQL 14+, asyncpg-compatible parameterised SQL
"""
from __future__ import annotations

import logging

import asyncpg

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Table DDL
# ---------------------------------------------------------------------------

_SQL_AUTOMATION_DEFINITIONS = """
CREATE TABLE IF NOT EXISTS automation_definitions (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID        NOT NULL,
    name            TEXT        NOT NULL,
    description     TEXT,
    definition      JSONB       NOT NULL DEFAULT '{}',
    triggers        JSONB       NOT NULL DEFAULT '[]',
    is_active       BOOLEAN     NOT NULL DEFAULT false,
    version         INTEGER     NOT NULL DEFAULT 1,
    created_by      UUID,
    updated_by      UUID,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at      TIMESTAMPTZ
);
"""

_SQL_AUTOMATION_DEFINITIONS_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_auto_defs_org    ON automation_definitions(organization_id) WHERE deleted_at IS NULL",
    "CREATE INDEX IF NOT EXISTS idx_auto_defs_active  ON automation_definitions(organization_id, is_active) WHERE deleted_at IS NULL",
    # Partial unique: org cannot have two live automations with the same name.
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_auto_defs_org_name ON automation_definitions(organization_id, name) WHERE deleted_at IS NULL",
]

_SQL_AUTOMATION_RUNS = """
CREATE TABLE IF NOT EXISTS automation_runs (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID        NOT NULL,
    definition_id   UUID,
    run_id          TEXT        NOT NULL,
    name            TEXT        NOT NULL DEFAULT '',
    status          TEXT        NOT NULL DEFAULT 'pending'
                    CHECK (status IN (
                        'pending','running','completed','failed',
                        'compensating','cancelled','interrupted'
                    )),
    context         JSONB       NOT NULL DEFAULT '{}',
    error           TEXT,
    triggered_by    TEXT,
    triggered_by_user UUID,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ,
    CONSTRAINT automation_runs_run_id_unique UNIQUE (run_id)
);
"""

_SQL_AUTOMATION_RUNS_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_auto_runs_org    ON automation_runs(organization_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_auto_runs_def    ON automation_runs(definition_id) WHERE definition_id IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS idx_auto_runs_run_id ON automation_runs(run_id)",
    # Partial index for startup recovery and monitoring.
    "CREATE INDEX IF NOT EXISTS idx_auto_runs_active ON automation_runs(organization_id, status) WHERE status IN ('pending','running','interrupted')",
]

_SQL_AUTOMATION_RUN_STEPS = """
CREATE TABLE IF NOT EXISTS automation_run_steps (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id  UUID        NOT NULL,
    run_id           TEXT        NOT NULL,
    step_id          TEXT        NOT NULL,
    name             TEXT        NOT NULL DEFAULT '',
    status           TEXT        NOT NULL DEFAULT 'pending'
                     CHECK (status IN (
                         'pending','running','completed','failed',
                         'skipped','waiting','compensated'
                     )),
    attempt          INTEGER     NOT NULL DEFAULT 0,
    requires_approval BOOLEAN    NOT NULL DEFAULT false,
    depends_on       JSONB       NOT NULL DEFAULT '[]',
    args             JSONB       NOT NULL DEFAULT '{}',
    result           JSONB,
    error            TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at       TIMESTAMPTZ,
    finished_at      TIMESTAMPTZ,
    CONSTRAINT automation_run_steps_run_step_unique UNIQUE (run_id, step_id)
);
"""

_SQL_AUTOMATION_RUN_STEPS_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_auto_steps_org    ON automation_run_steps(organization_id)",
    "CREATE INDEX IF NOT EXISTS idx_auto_steps_run    ON automation_run_steps(run_id)",
]

_SQL_AUTOMATION_APPROVALS = """
CREATE TABLE IF NOT EXISTS automation_approvals (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID        NOT NULL,
    run_id          TEXT        NOT NULL,
    step_id         TEXT        NOT NULL,
    approval_id     TEXT        NOT NULL,
    status          TEXT        NOT NULL DEFAULT 'pending'
                    CHECK (status IN (
                        'pending','approved','rejected','expired','orphaned'
                    )),
    requested_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    decided_at      TIMESTAMPTZ,
    decided_by      UUID,
    CONSTRAINT automation_approvals_approval_id_unique UNIQUE (approval_id)
);
"""

_SQL_AUTOMATION_APPROVALS_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_auto_approvals_org     ON automation_approvals(organization_id)",
    "CREATE INDEX IF NOT EXISTS idx_auto_approvals_run     ON automation_approvals(run_id)",
    "CREATE INDEX IF NOT EXISTS idx_auto_approvals_pending ON automation_approvals(organization_id, status) WHERE status = 'pending'",
]


# ---------------------------------------------------------------------------
# Schema init (idempotent)
# ---------------------------------------------------------------------------

async def init_automation_schema(conn: asyncpg.Connection) -> None:
    """Create all four automation tables and their indexes.
    Safe to call on every boot — fully idempotent.
    """
    log.info("automation schema: initialising")

    # Tables
    for sql in (
        _SQL_AUTOMATION_DEFINITIONS,
        _SQL_AUTOMATION_RUNS,
        _SQL_AUTOMATION_RUN_STEPS,
        _SQL_AUTOMATION_APPROVALS,
    ):
        await conn.execute(sql)

    # Indexes
    for sql in (
        *_SQL_AUTOMATION_DEFINITIONS_INDEXES,
        *_SQL_AUTOMATION_RUNS_INDEXES,
        *_SQL_AUTOMATION_RUN_STEPS_INDEXES,
        *_SQL_AUTOMATION_APPROVALS_INDEXES,
    ):
        await conn.execute(sql)

    # Forward-compatible column additions (idempotent ALTER TABLE).
    # Add new columns here when extending the schema rather than creating
    # new migration files.  Each statement is independent and safe to re-run.
    _evolution_stmts = [
        # placeholder — future evolutions go here, e.g.:
        # "ALTER TABLE automation_definitions ADD COLUMN IF NOT EXISTS tags JSONB NOT NULL DEFAULT '[]'",
    ]
    for sql in _evolution_stmts:
        await conn.execute(sql)

    log.info("automation schema: ready")


# ---------------------------------------------------------------------------
# Startup recovery
# ---------------------------------------------------------------------------

async def mark_interrupted_runs() -> None:
    """
    Mark any run that was left in a transient (non-terminal) state as
    'interrupted' after a server restart.

    WorkflowEngine is purely in-memory: after a process restart its
    _active dict is empty.  Runs persisted as 'running' or 'compensating'
    can never make forward progress — marking them 'interrupted' lets the
    UI surface a clear error and lets users retry rather than waiting
    forever.

    Idempotent: completed/failed/cancelled runs are untouched.
    Pending approval records for interrupted runs are intentionally left
    pending (v1) — the API surfaces the run as interrupted, making it
    clear the runtime is gone.
    """
    from app.core.db import get_pool

    pool = get_pool()
    if pool is None:
        log.warning("automation recovery: pool not ready, skipping")
        return

    try:
        async with pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE automation_runs
                SET
                    status      = 'interrupted',
                    finished_at = now(),
                    error       = 'Run interrupted — server restarted before completion'
                WHERE status IN ('running', 'compensating')
                """
            )
        # asyncpg returns "UPDATE N" as the status string
        count = int(result.split()[-1]) if result else 0
        if count:
            log.warning("automation recovery: marked %d run(s) as interrupted", count)
        else:
            log.debug("automation recovery: no orphaned runs found")
    except Exception:
        log.exception("automation recovery: failed — non-fatal, continuing startup")
