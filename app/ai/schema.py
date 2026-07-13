"""
ai_usage_log — the single persisted cost/token ledger for the whole AI
platform, idempotent boot-time init matching every other *_schema.py module
in this codebase.

AI Routing consolidation: this table did not previously exist anywhere in
the app's own startup path (only in an unexecuted migrations/versions/
003_ai_gateway.py file referencing a nonexistent ai_conversations table) —
every cost_tracker.record()/totals()/by_provider() call was silently
no-op'ing against a missing table. This is the real, live schema, wired
into factory.py like every other subsystem's schema module. conversation_id
references the actual live `conversations` table (app/core/db.py), not the
never-created `ai_conversations`.
"""
from __future__ import annotations

import logging

import asyncpg

log = logging.getLogger(__name__)

AI_USAGE_SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_usage_log (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID REFERENCES users(id) ON DELETE SET NULL,
    organization_id     UUID REFERENCES organizations(id) ON DELETE SET NULL,
    conversation_id     UUID REFERENCES conversations(id) ON DELETE SET NULL,
    provider            TEXT NOT NULL,
    model               TEXT NOT NULL,
    input_tokens        INTEGER NOT NULL DEFAULT 0,
    output_tokens       INTEGER NOT NULL DEFAULT 0,
    total_tokens        INTEGER NOT NULL DEFAULT 0,
    cost_usd            NUMERIC(16,8) NOT NULL DEFAULT 0,
    cached              BOOLEAN NOT NULL DEFAULT false,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ai_usage_user_idx ON ai_usage_log(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ai_usage_org_idx  ON ai_usage_log(organization_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ai_usage_conv_idx ON ai_usage_log(conversation_id);
"""


async def init_ai_usage_schema(conn: asyncpg.Connection) -> None:
    await conn.execute(AI_USAGE_SCHEMA)
    log.info("ai_usage_log schema initialised")
