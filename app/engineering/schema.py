"""
Engineering Control Plane — database schema.

Tables (idempotent, backward-compatible):

  eng_missions         — long-lived goals Claude executes on behalf of an org
  eng_tasks            — individual steps within a mission
  eng_task_transitions — append-only FSM audit log (actor, reason, timestamp)
  eng_evidence         — immutable records produced by every external tool call
  eng_approvals        — persistent approval gates for high-risk actions

All tables are org-scoped and will be added to _RLS_TABLES in
app/tenancy/rls.py (see rls.py for the RLS policy pattern).

RLS note: eng_evidence and eng_approvals reference eng_missions(id) and
eng_tasks(id) — those are already scoped by organization_id in their
parent tables, but we add organization_id directly to every child table
as well (denormalized) so RLS can enforce the policy without a JOIN.

init_engineering_schema() is called from app/factory.py lifespan block
after init_integrations_schema() (integration credentials are a prerequisite
for tool calls, which missions depend on).
"""
from __future__ import annotations

import logging

import asyncpg

log = logging.getLogger(__name__)

_ENGINEERING_SCHEMA = """
-- ── Missions ──────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS eng_missions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    project_id      UUID,                          -- optional project scope
    objective       TEXT NOT NULL,                 -- free-text goal
    template        TEXT,                          -- 'release', 'incident', 'custom'
    status          TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN (
            'pending','planning','running','waiting_approval',
            'blocked','verifying','succeeded','failed',
            'cancelled','recovering','rolled_back'
        )),
    created_by      UUID NOT NULL REFERENCES users(id),
    agent_session   TEXT,                          -- opaque agent/session identifier
    current_phase   TEXT,                          -- human-readable current step name
    budget_tokens   INTEGER DEFAULT 200000,        -- max LLM tokens for this mission
    budget_steps    INTEGER DEFAULT 100,           -- max tool calls
    tokens_used     INTEGER DEFAULT 0,
    steps_used      INTEGER DEFAULT 0,
    job_id          TEXT,                          -- JobQueue job id running this mission
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_eng_missions_org
    ON eng_missions(organization_id)
    WHERE status NOT IN ('succeeded','failed','cancelled','rolled_back');

CREATE INDEX IF NOT EXISTS idx_eng_missions_status
    ON eng_missions(status, created_at DESC);

-- ── Tasks ─────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS eng_tasks (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mission_id       UUID NOT NULL REFERENCES eng_missions(id) ON DELETE CASCADE,
    organization_id  UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    type             TEXT NOT NULL,               -- 'tool_call', 'approval_wait', 'verify', etc.
    name             TEXT NOT NULL,               -- human-readable label
    status           TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN (
            'pending','running','waiting','completed','failed',
            'cancelled','skipped','compensated'
        )),
    attempt          INTEGER NOT NULL DEFAULT 0,
    max_attempts     INTEGER NOT NULL DEFAULT 3,
    input            JSONB   NOT NULL DEFAULT '{}',
    output           JSONB,                        -- sanitized result (never raw secrets)
    error            TEXT,
    idempotency_key  TEXT UNIQUE,                 -- prevents duplicate execution
    heartbeat_at     TIMESTAMPTZ,
    started_at       TIMESTAMPTZ,
    completed_at     TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_eng_tasks_mission
    ON eng_tasks(mission_id, status);

CREATE INDEX IF NOT EXISTS idx_eng_tasks_org_running
    ON eng_tasks(organization_id)
    WHERE status = 'running';

-- ── Task transitions (FSM audit log) ──────────────────────────────────────────

CREATE TABLE IF NOT EXISTS eng_task_transitions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id     UUID NOT NULL REFERENCES eng_tasks(id) ON DELETE CASCADE,
    mission_id  UUID NOT NULL,                     -- denormalized for fast query
    org_id      UUID NOT NULL,
    from_status TEXT,
    to_status   TEXT NOT NULL,
    actor       TEXT,                              -- 'system', 'user:{id}', 'agent'
    reason      TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_eng_transitions_task
    ON eng_task_transitions(task_id, created_at DESC);

-- ── Evidence ──────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS eng_evidence (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id     UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    mission_id          UUID NOT NULL REFERENCES eng_missions(id) ON DELETE CASCADE,
    task_id             UUID REFERENCES eng_tasks(id) ON DELETE SET NULL,
    provider            TEXT NOT NULL,             -- 'github', 'render', 'vercel', etc.
    operation           TEXT NOT NULL,             -- 'create_pr', 'trigger_deploy', etc.
    tool_name           TEXT NOT NULL,             -- 'github.create_pr'
    -- inputs_hash: SHA-256 of the sanitized input dict (no secrets ever)
    inputs_hash         TEXT NOT NULL,
    -- outputs_summary: sanitized result — no raw tokens, no credentials
    outputs_summary     JSONB NOT NULL DEFAULT '{}',
    verification_status TEXT NOT NULL DEFAULT 'unverified'
        CHECK (verification_status IN ('unverified','pending','verified','failed')),
    verified_at         TIMESTAMPTZ,
    -- For deployment evidence: tracked SHAs
    requested_sha       TEXT,
    observed_sha        TEXT,
    deploy_id           TEXT,                      -- provider-specific deploy identifier
    sha_match           BOOLEAN,                   -- requested_sha == observed_sha
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_eng_evidence_mission
    ON eng_evidence(mission_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_eng_evidence_org
    ON eng_evidence(organization_id, created_at DESC);

-- ── Approvals ─────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS eng_approvals (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    mission_id      UUID NOT NULL REFERENCES eng_missions(id) ON DELETE CASCADE,
    task_id         UUID REFERENCES eng_tasks(id) ON DELETE SET NULL,
    action          TEXT NOT NULL,               -- 'github.pr.merge', 'render.deploy', etc.
    resource        TEXT,                        -- repo name, service id, etc.
    risk_level      TEXT NOT NULL
        CHECK (risk_level IN ('low','medium','high','critical')),
    requested_by    UUID NOT NULL REFERENCES users(id),
    decided_by      UUID REFERENCES users(id),
    decision        TEXT CHECK (decision IN ('approved','rejected')),
    reason          TEXT NOT NULL,               -- agent's justification
    evidence_id     UUID REFERENCES eng_evidence(id) ON DELETE SET NULL,
    expires_at      TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    decided_at      TIMESTAMPTZ,
    -- status is derived from decision + expires_at but stored for fast queries
    status          TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending','approved','rejected','expired'))
);

CREATE INDEX IF NOT EXISTS idx_eng_approvals_mission
    ON eng_approvals(mission_id, status);

CREATE INDEX IF NOT EXISTS idx_eng_approvals_org_pending
    ON eng_approvals(organization_id)
    WHERE status = 'pending';
"""


async def init_engineering_schema(conn: asyncpg.Connection) -> None:
    """Create all Engineering Control Plane tables if they don't exist.

    Idempotent — safe to call on every boot. Called from app/factory.py
    after init_integrations_schema().
    """
    try:
        await conn.execute(_ENGINEERING_SCHEMA)
        log.info("engineering schema initialized")
    except Exception:
        log.warning("engineering schema init failed (continuing)", exc_info=True)


# ── Role permissions for engineering resources ─────────────────────────────────

ENGINEERING_PERMISSIONS: dict[str, list[tuple[str, str]]] = {
    "owner": [
        ("engineering", "read"),
        ("engineering", "write"),
        ("engineering", "execute"),
        ("engineering", "approve"),
        ("engineering", "deploy"),
    ],
    "admin": [
        ("engineering", "read"),
        ("engineering", "write"),
        ("engineering", "execute"),
        ("engineering", "approve"),
        ("engineering", "deploy"),
    ],
    "manager": [
        ("engineering", "read"),
        ("engineering", "write"),
        ("engineering", "approve"),
    ],
    "developer": [
        ("engineering", "read"),
        ("engineering", "write"),
        ("engineering", "execute"),
    ],
    "operator": [
        ("engineering", "read"),
        ("engineering", "execute"),
    ],
    "viewer": [
        ("engineering", "read"),
    ],
}
