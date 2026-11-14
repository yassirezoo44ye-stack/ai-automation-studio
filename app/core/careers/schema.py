"""Idempotent schema, following the platform's startup migration convention."""

SQL = """
CREATE TABLE IF NOT EXISTS career_profiles (
 organization_id UUID NOT NULL, user_id UUID NOT NULL,
 profile JSONB NOT NULL DEFAULT '{}', updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 PRIMARY KEY (organization_id,user_id)
);
CREATE TABLE IF NOT EXISTS career_jobs (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
 organization_id UUID NOT NULL, user_id UUID NOT NULL, job_key TEXT NOT NULL,
 data JSONB NOT NULL, status TEXT NOT NULL DEFAULT 'new'
 CHECK(status IN ('new','saved','applied','interview','rejected')),
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 UNIQUE(organization_id,user_id,job_key)
);
CREATE INDEX IF NOT EXISTS career_jobs_owner ON career_jobs(organization_id,user_id,created_at DESC);
CREATE TABLE IF NOT EXISTS career_gmail (
 organization_id UUID NOT NULL, user_id UUID NOT NULL, refresh_encrypted TEXT NOT NULL,
 enabled BOOLEAN NOT NULL DEFAULT false, interval_hours INTEGER NOT NULL DEFAULT 24
 CHECK(interval_hours BETWEEN 6 AND 168), next_sync TIMESTAMPTZ NOT NULL DEFAULT now(),
 last_sync TIMESTAMPTZ, last_error TEXT,
 PRIMARY KEY (organization_id,user_id)
);
CREATE TABLE IF NOT EXISTS career_oauth_states (
 state_hash TEXT PRIMARY KEY, organization_id UUID NOT NULL, user_id UUID NOT NULL,
 verifier_encrypted TEXT NOT NULL, expires_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS career_gmail_messages (
 organization_id UUID NOT NULL, user_id UUID NOT NULL, message_id TEXT NOT NULL,
 processed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 PRIMARY KEY (organization_id,user_id,message_id)
);
"""


async def init_careers_schema(conn):
    await conn.execute(SQL)
