"""
Business Plan & Validation Engine — database schema.

All tables are prefixed `bp_` to avoid collisions.
RLS is enabled inline (app/tenancy/rls.py is hands-off for this module).
Call ensure_business_plans_schema(conn) once from app startup.
"""
from __future__ import annotations

import logging

import asyncpg

log = logging.getLogger(__name__)

_DDL = """
-- ── Main plan record ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS bp_plans (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID        NOT NULL,
    user_id         UUID        NOT NULL,
    title           TEXT        NOT NULL DEFAULT '',
    idea_raw        TEXT        NOT NULL DEFAULT '',
    industry        TEXT,
    stage           TEXT        NOT NULL DEFAULT 'IDEA',  -- IDEA/MVP/GROWTH/SCALE
    status          TEXT        NOT NULL DEFAULT 'DRAFT', -- DRAFT/GENERATING/COMPLETED/FAILED/PAUSED
    readiness_score INT,                                   -- 0-100
    workflow_run_id TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Fact Registry ─────────────────────────────────────────────────────────────
-- Source of truth for every claim in the plan.
-- AI must NEVER promote an ASSUMPTION to VERIFIED without external corroboration.
CREATE TABLE IF NOT EXISTS bp_facts (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_id         UUID        NOT NULL REFERENCES bp_plans(id) ON DELETE CASCADE,
    organization_id UUID        NOT NULL,
    fact_key        TEXT        NOT NULL,           -- e.g. "market_size_tam"
    value           JSONB       NOT NULL DEFAULT '{}',
    source_type     TEXT        NOT NULL DEFAULT 'AI_INFERENCE',
                                                    -- USER/WEB/CALCULATION/DOCUMENT/AI_INFERENCE
    source_url      TEXT,
    source_note     TEXT,
    status          TEXT        NOT NULL DEFAULT 'UNVERIFIED',
                                                    -- VERIFIED/UNVERIFIED/ASSUMPTION/MISSING/CONFLICTING
    confidence      FLOAT       NOT NULL DEFAULT 0.5 CHECK (confidence BETWEEN 0 AND 1),
    section         TEXT,                           -- which plan section this belongs to
    created_by      TEXT,                           -- agent name
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Plan sections (one row per generated section) ─────────────────────────────
CREATE TABLE IF NOT EXISTS bp_sections (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_id         UUID        NOT NULL REFERENCES bp_plans(id) ON DELETE CASCADE,
    organization_id UUID        NOT NULL,
    section_key     TEXT        NOT NULL,           -- e.g. "market_intelligence"
    title           TEXT        NOT NULL DEFAULT '',
    content         TEXT        NOT NULL DEFAULT '', -- Markdown
    status          TEXT        NOT NULL DEFAULT 'PENDING',
                                                    -- PENDING/RUNNING/COMPLETED/FAILED/NEEDS_REVIEW
    agent_name      TEXT,
    model_used      TEXT,
    tokens_used     INT         NOT NULL DEFAULT 0,
    elapsed_ms      INT,
    retry_count     INT         NOT NULL DEFAULT 0,
    error_msg       TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (plan_id, section_key)
);

-- ── Competitors ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS bp_competitors (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_id         UUID        NOT NULL REFERENCES bp_plans(id) ON DELETE CASCADE,
    organization_id UUID        NOT NULL,
    name            TEXT        NOT NULL,
    website         TEXT,
    description     TEXT,
    strengths       JSONB       NOT NULL DEFAULT '[]',
    weaknesses      JSONB       NOT NULL DEFAULT '[]',
    pricing         TEXT,
    market_position TEXT,
    source_url      TEXT,
    verified        BOOL        NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Readiness scores (append-only; latest row = current score) ───────────────
CREATE TABLE IF NOT EXISTS bp_scores (
    id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_id           UUID        NOT NULL REFERENCES bp_plans(id) ON DELETE CASCADE,
    organization_id   UUID        NOT NULL,
    overall_score     INT         NOT NULL CHECK (overall_score BETWEEN 0 AND 100),
    breakdown         JSONB       NOT NULL DEFAULT '{}',
    evidence_count    INT         NOT NULL DEFAULT 0,
    assumption_count  INT         NOT NULL DEFAULT 0,
    missing_count     INT         NOT NULL DEFAULT 0,
    computed_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Workflow checkpoints (for resume) ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS bp_checkpoints (
    id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_id           UUID        NOT NULL REFERENCES bp_plans(id) ON DELETE CASCADE,
    organization_id   UUID        NOT NULL,
    workflow_run_id   TEXT        NOT NULL,
    checkpoint_data   JSONB       NOT NULL DEFAULT '{}',
    completed_stages  JSONB       NOT NULL DEFAULT '[]',
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Indexes ───────────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS bp_plans_org_idx         ON bp_plans(organization_id);
CREATE INDEX IF NOT EXISTS bp_plans_user_idx        ON bp_plans(user_id);
CREATE INDEX IF NOT EXISTS bp_facts_plan_idx        ON bp_facts(plan_id);
CREATE INDEX IF NOT EXISTS bp_facts_org_idx         ON bp_facts(organization_id);
CREATE INDEX IF NOT EXISTS bp_facts_status_idx      ON bp_facts(status);
CREATE INDEX IF NOT EXISTS bp_sections_plan_idx     ON bp_sections(plan_id);
CREATE INDEX IF NOT EXISTS bp_competitors_plan_idx  ON bp_competitors(plan_id);
CREATE INDEX IF NOT EXISTS bp_scores_plan_idx       ON bp_scores(plan_id, computed_at DESC);
CREATE INDEX IF NOT EXISTS bp_checkpoints_plan_idx  ON bp_checkpoints(plan_id);

-- ── Row Level Security ────────────────────────────────────────────────────────
-- Inline because app/tenancy/rls.py is frozen for this module.
DO $$ BEGIN
  ALTER TABLE bp_plans        ENABLE ROW LEVEL SECURITY;
  ALTER TABLE bp_plans        FORCE  ROW LEVEL SECURITY;
  ALTER TABLE bp_facts        ENABLE ROW LEVEL SECURITY;
  ALTER TABLE bp_facts        FORCE  ROW LEVEL SECURITY;
  ALTER TABLE bp_sections     ENABLE ROW LEVEL SECURITY;
  ALTER TABLE bp_sections     FORCE  ROW LEVEL SECURITY;
  ALTER TABLE bp_competitors  ENABLE ROW LEVEL SECURITY;
  ALTER TABLE bp_competitors  FORCE  ROW LEVEL SECURITY;
  ALTER TABLE bp_scores       ENABLE ROW LEVEL SECURITY;
  ALTER TABLE bp_scores       FORCE  ROW LEVEL SECURITY;
  ALTER TABLE bp_checkpoints  ENABLE ROW LEVEL SECURITY;
  ALTER TABLE bp_checkpoints  FORCE  ROW LEVEL SECURITY;
EXCEPTION WHEN OTHERS THEN NULL; END $$;

DO $$ BEGIN
  CREATE POLICY bp_plans_isolation ON bp_plans
    USING (organization_id::text = current_setting('app.current_org_id', true));
  CREATE POLICY bp_facts_isolation ON bp_facts
    USING (organization_id::text = current_setting('app.current_org_id', true));
  CREATE POLICY bp_sections_isolation ON bp_sections
    USING (organization_id::text = current_setting('app.current_org_id', true));
  CREATE POLICY bp_competitors_isolation ON bp_competitors
    USING (organization_id::text = current_setting('app.current_org_id', true));
  CREATE POLICY bp_scores_isolation ON bp_scores
    USING (organization_id::text = current_setting('app.current_org_id', true));
  CREATE POLICY bp_checkpoints_isolation ON bp_checkpoints
    USING (organization_id::text = current_setting('app.current_org_id', true));
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
"""


async def ensure_business_plans_schema(conn: asyncpg.Connection) -> None:
    """Idempotent: safe to call on every startup."""
    await conn.execute(_DDL)


async def mark_interrupted_business_plans() -> None:
    """
    Mark any business plan or section left in a transient state as FAILED
    after a server restart/crash.

    The workflow engine is purely in-memory: after a process restart its
    state is gone. Plans persisted as GENERATING and sections as RUNNING
    can never make forward progress — marking them FAILED lets the UI
    surface the error and lets users click Retry rather than waiting forever.

    Idempotent: only touches non-terminal states (GENERATING/RUNNING).
    Concurrency-safe: plain UPDATE WHERE; second concurrent call finds 0 rows.
    Org-safe: updates across all orgs (system-level recovery, not tenant-scoped).
    Uses plain pool.acquire() — the app DB user has BYPASSRLS so unscoped
    connections see all rows (same pattern as mark_interrupted_runs() for
    automation_runs in app/core/workflow/automation_schema.py).
    """
    from app.core.db import get_pool

    pool = get_pool()
    if pool is None:
        log.warning("business plan recovery: pool not ready, skipping")
        return

    try:
        async with pool.acquire() as conn:
            plan_result = await conn.execute(
                """
                UPDATE bp_plans
                SET status     = 'FAILED',
                    updated_at = NOW()
                WHERE status = 'GENERATING'
                """
            )
            section_result = await conn.execute(
                """
                UPDATE bp_sections
                SET status     = 'FAILED',
                    error_msg  = 'Server restarted before this section completed',
                    updated_at = NOW()
                WHERE status = 'RUNNING'
                """
            )
        plan_count    = int(plan_result.split()[-1])    if plan_result    else 0
        section_count = int(section_result.split()[-1]) if section_result else 0
        if plan_count or section_count:
            log.warning(
                "business plan recovery: marked %d plan(s) and %d section(s) as FAILED",
                plan_count, section_count,
            )
        else:
            log.debug("business plan recovery: no orphaned plans or sections found")
    except Exception:
        log.exception("business plan recovery: failed — non-fatal, continuing startup")
