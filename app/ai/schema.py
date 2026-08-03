"""
AI Gateway persistence — ai_conversations/ai_messages/ai_memory_items/
ai_prompts/ai_prompt_versions/ai_usage_log, idempotent boot-time init
matching every other *_schema.py module in this codebase.

AI entry-point unification audit (docs/AI_ENTRY_POINT_UNIFICATION_AUDIT.md,
2026-08-03), P0: none of these tables previously existed in the app's own
startup path. migrations/versions/003_ai_gateway.py defines them, but that
file is not a valid Alembic revision script — it has no `revision`/
`down_revision` module-level variables, which `alembic history` requires to
build the revision graph; confirmed by running `python -m alembic history`
directly, which fails with "Could not determine revision id from filename
003_ai_gateway.py". It was never executed by any live startup path. This
module applies the same table definitions via the init_*_schema() convention
every other subsystem here already uses, so they actually run.

ai_usage_log specifically: an earlier version of this module (before the
tables above existed) pointed conversation_id at the legacy `conversations`
table (app/core/db.py) as a stopgap, since `ai_conversations` didn't exist
yet. That is now the wrong target — AIGateway._post_complete() (app/ai/
gateway.py) writes ai_conversations.id values into this column, never
conversations.id — so AI_USAGE_LOG_FK_FIX below retargets it. Verified safe
for any pre-existing deployment: cost_tracker.record() is ai_usage_log's
only writer, reachable only via AIGateway._post_complete(), which itself
requires mem.is_owned_by() to pass first — and that has only ever been
satisfiable against a real ai_conversations row, which could not exist
before this fix. No non-null conversation_id can already be sitting in this
column pointing anywhere.
"""
from __future__ import annotations

import logging

import asyncpg

log = logging.getLogger(__name__)

# ── AI Gateway tables (conversations / messages / memory / prompts) ────────
#
# Verbatim from migrations/versions/003_ai_gateway.py's SQL_UP (minus
# ai_usage_log, handled separately below since it predates this function and
# needs its own FK-retargeting step for pre-existing deployments).
AI_GATEWAY_SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_conversations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID REFERENCES users(id) ON DELETE SET NULL,
    project_id      UUID,
    agent_id        UUID,
    title           TEXT NOT NULL DEFAULT 'New conversation',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ai_conv_user_idx      ON ai_conversations(user_id);
CREATE INDEX IF NOT EXISTS ai_conv_updated_idx   ON ai_conversations(updated_at DESC);

CREATE TABLE IF NOT EXISTS ai_messages (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id     UUID NOT NULL REFERENCES ai_conversations(id) ON DELETE CASCADE,
    role                TEXT NOT NULL CHECK (role IN ('user','assistant','tool','system')),
    content             TEXT NOT NULL,
    tool_call_id        TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ai_msg_conv_idx  ON ai_messages(conversation_id, created_at);

CREATE TABLE IF NOT EXISTS ai_memory_items (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID REFERENCES users(id) ON DELETE CASCADE,
    conversation_id     UUID REFERENCES ai_conversations(id) ON DELETE SET NULL,
    content             TEXT NOT NULL,
    importance          REAL NOT NULL DEFAULT 1.0,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ai_mem_user_idx  ON ai_memory_items(user_id, importance DESC);

CREATE TABLE IF NOT EXISTS ai_prompts (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL,
    slug        TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    user_id     UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ai_prompt_versions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    prompt_id       UUID NOT NULL REFERENCES ai_prompts(id) ON DELETE CASCADE,
    version         INTEGER NOT NULL,
    system          TEXT,
    user_template   TEXT,
    variables       TEXT[] NOT NULL DEFAULT '{}',
    is_active       BOOLEAN NOT NULL DEFAULT false,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (prompt_id, version)
);
CREATE INDEX IF NOT EXISTS ai_pv_prompt_active  ON ai_prompt_versions(prompt_id, is_active);
"""


async def init_ai_gateway_schema(conn: asyncpg.Connection) -> None:
    await conn.execute(AI_GATEWAY_SCHEMA)
    log.info("ai_conversations/ai_messages/ai_memory_items/ai_prompts/ai_prompt_versions schema initialised")


AI_USAGE_SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_usage_log (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID REFERENCES users(id) ON DELETE SET NULL,
    organization_id     UUID REFERENCES organizations(id) ON DELETE SET NULL,
    conversation_id     UUID REFERENCES ai_conversations(id) ON DELETE SET NULL,
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

# Retargets conversation_id's FK for any pre-existing ai_usage_log created by
# an earlier version of AI_USAGE_SCHEMA (which pointed at the legacy
# `conversations` table — see module docstring). A no-op on a fresh DB,
# where AI_USAGE_SCHEMA above already creates the column with this exact
# target and Postgres's default constraint-naming convention
# (<table>_<column>_fkey) makes the DROP/re-ADD a harmless round-trip.
AI_USAGE_LOG_FK_FIX = """
ALTER TABLE ai_usage_log
    DROP CONSTRAINT IF EXISTS ai_usage_log_conversation_id_fkey;
ALTER TABLE ai_usage_log
    ADD CONSTRAINT ai_usage_log_conversation_id_fkey
    FOREIGN KEY (conversation_id) REFERENCES ai_conversations(id) ON DELETE SET NULL;
"""


async def init_ai_usage_schema(conn: asyncpg.Connection) -> None:
    await conn.execute(AI_USAGE_SCHEMA)
    await conn.execute(AI_USAGE_LOG_FK_FIX)
    log.info("ai_usage_log schema initialised")
