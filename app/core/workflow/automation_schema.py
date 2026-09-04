"""
Automation Engine — Phase 5 Gate 3 schema.

Four tables, each initialised idempotently via ensure_*_table() functions
called from app/factory.py lifespan (same pattern as ensure_agents_table,
ensure_tasks_table, etc. in app/core/db.py).

No Alembic — all DDL uses CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT
EXISTS / ALTER TABLE … ADD COLUMN IF NOT EXISTS so re-running on an existing
database is safe.

Table summary
─────────────
automation_definitions  — named, versioned workflow blueprints per org
automation_runs         — execution records for every WorkflowRun instance
automation_run_steps    — per-step state mirroring WorkflowStep
automation_approvals    — human-approval gate requests and decisions
"""
from __future__ import annotations

import logging

from app.core.db import get_pool

log = logging.getLogger(__name__)


async def ensure_automation_definitions_table() -> None:
    """Idempotent: creates automation_definitions and its indexes."""
    async with get_pool().acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS automation_definitions (
                id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                organization_id UUID NOT NULL,
                name            TEXT NOT NULL,
                description     TEXT NOT NULL DEFAULT '',
                definition      JSONB NOT NULL DEFAULT '{}',
                triggers        JSONB NOT NULL DEFAULT '[]',
                is_active       BOOLEAN NOT NULL DEFAULT true,
                version         INTEGER NOT NULL DEFAULT 1,
                created_by      UUID,
                updated_by      UUID,
                created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
                deleted_at      TIMESTAMPTZ
            )
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_automation_defs_org
            ON automation_definitions(organization_id)
            WHERE deleted_at IS NULL
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_automation_defs_active
            ON automation_definitions(organization_id, is_active)
            WHERE deleted_at IS NULL
        """)
        await conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_automation_defs_name_org
            ON automation_definitions(organization_id, name)
            WHERE deleted_at IS NULL
        """)
    log.info("automation_definitions table ready")


async def ensure_automation_runs_table() -> None:
    """Idempotent: creates automation_runs and its indexes."""
    async with get_pool().acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS automation_runs (
                id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                organization_id     UUID NOT NULL,
                definition_id       UUID,
                run_id              TEXT NOT NULL UNIQUE,
                name                TEXT NOT NULL,
                status              TEXT NOT NULL DEFAULT 'pending'
                                    CHECK (status IN (
                                        'pending', 'running', 'completed', 'failed',
                                        'compensating', 'cancelled', 'interrupted'
                                    )),
                context             JSONB NOT NULL DEFAULT '{}',
                error               TEXT,
                triggered_by        TEXT,
                triggered_by_user   UUID,
                created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
                started_at          TIMESTAMPTZ,
                finished_at         TIMESTAMPTZ
            )
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_automation_runs_org
            ON automation_runs(organization_id, created_at DESC)
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_automation_runs_def
            ON automation_runs(definition_id, created_at DESC)
            WHERE definition_id IS NOT NULL
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_automation_runs_status
            ON automation_runs(organization_id, status)
            WHERE status IN ('pending', 'running')
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_automation_runs_run_id
            ON automation_runs(run_id)
        """)
    log.info("automation_runs table ready")


async def ensure_automation_run_steps_table() -> None:
    """Idempotent: creates automation_run_steps and its indexes."""
    async with get_pool().acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS automation_run_steps (
                id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                run_id          TEXT NOT NULL,
                organization_id UUID NOT NULL,
                step_id         TEXT NOT NULL,
                name            TEXT NOT NULL,
                status          TEXT NOT NULL DEFAULT 'pending'
                                CHECK (status IN (
                                    'pending', 'running', 'completed', 'failed',
                                    'skipped', 'waiting', 'compensated'
                                )),
                attempt         INTEGER NOT NULL DEFAULT 0,
                requires_approval BOOLEAN NOT NULL DEFAULT false,
                depends_on      JSONB NOT NULL DEFAULT '[]',
                args            JSONB NOT NULL DEFAULT '{}',
                result          JSONB,
                error           TEXT,
                started_at      TIMESTAMPTZ,
                finished_at     TIMESTAMPTZ,
                created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_run_steps_run
            ON automation_run_steps(run_id, step_id)
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_run_steps_org
            ON automation_run_steps(organization_id)
        """)
        await conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_run_steps_unique
            ON automation_run_steps(run_id, step_id)
        """)
    log.info("automation_run_steps table ready")


async def ensure_automation_approvals_table() -> None:
    """Idempotent: creates automation_approvals and its indexes."""
    async with get_pool().acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS automation_approvals (
                id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                organization_id UUID NOT NULL,
                run_id          TEXT NOT NULL,
                step_id         TEXT NOT NULL,
                approval_id     TEXT NOT NULL UNIQUE,
                status          TEXT NOT NULL DEFAULT 'pending'
                                CHECK (status IN (
                                    'pending', 'approved', 'rejected', 'expired', 'orphaned'
                                )),
                requested_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
                decided_at      TIMESTAMPTZ,
                decided_by      UUID
            )
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_approvals_org_pending
            ON automation_approvals(organization_id, status)
            WHERE status = 'pending'
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_approvals_run
            ON automation_approvals(run_id)
        """)
    log.info("automation_approvals table ready")
