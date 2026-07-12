"""
Agent Sandbox & Secure Execution Runtime.

Adds: sandbox_workers, sandbox_events.

No new permission-declaration/approval table — a sandbox worker's network
policy, filesystem mount mode, and secret injection are all derived from
the already-approved plugin_permissions rows for its plugin_installations
row (Plugin SDK, migration 007), read directly by SandboxManager. This
migration only adds the tables needed to track a worker's own lifecycle
and event history.

Matches 007's up(conn)/down(conn) convention.
"""

SQL_UP = """
CREATE TABLE IF NOT EXISTS sandbox_workers (
    id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id        UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    plugin_installation_id UUID NOT NULL REFERENCES plugin_installations(id) ON DELETE CASCADE,
    backend                VARCHAR(10) NOT NULL CHECK (backend IN ('docker','process')),
    status                 VARCHAR(10) NOT NULL DEFAULT 'starting'
                           CHECK (status IN ('starting','running','stopped','crashed')),
    pid_or_container_id    TEXT,
    started_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    stopped_at             TIMESTAMPTZ,
    cpu_seconds_used       DOUBLE PRECISION,
    memory_mb_peak         DOUBLE PRECISION,
    UNIQUE (plugin_installation_id)
);
CREATE INDEX IF NOT EXISTS idx_sandbox_workers_org ON sandbox_workers(organization_id);

CREATE TABLE IF NOT EXISTS sandbox_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    worker_id       UUID NOT NULL REFERENCES sandbox_workers(id) ON DELETE CASCADE,
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    event_type      VARCHAR(20) NOT NULL CHECK (event_type IN ('log','network','security','resource','lifecycle')),
    severity        VARCHAR(10) NOT NULL DEFAULT 'info' CHECK (severity IN ('info','warning','error')),
    message         TEXT,
    details         JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_sandbox_events_worker ON sandbox_events(worker_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sandbox_events_org_type ON sandbox_events(organization_id, event_type, created_at DESC);
"""

SQL_DOWN = """
DROP TABLE IF EXISTS sandbox_events;
DROP TABLE IF EXISTS sandbox_workers;
"""
# Does not touch plugin_installations/plugin_permissions (migration 007)
# or any marketplace_* table (migration 006) — only read from, never
# modified by this revision.


def up(conn):
    conn.execute(SQL_UP)


def down(conn):
    conn.execute(SQL_DOWN)
