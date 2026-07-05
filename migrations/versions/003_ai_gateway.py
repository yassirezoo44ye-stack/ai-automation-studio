"""
AI Gateway tables.

Creates:
  ai_conversations   — conversation threads linked to user/project/agent
  ai_messages        — individual messages within a conversation
  ai_memory_items    — long-term memory snippets per user
  ai_usage_log       — per-call token + cost audit log
  ai_prompts         — named prompt templates
  ai_prompt_versions — versioned prompt content with {{ variable }} interpolation
"""

SQL_UP = """
-- ── ai_conversations ──────────────────────────────────────────────────────────
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

-- ── ai_messages ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ai_messages (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id     UUID NOT NULL REFERENCES ai_conversations(id) ON DELETE CASCADE,
    role                TEXT NOT NULL CHECK (role IN ('user','assistant','tool','system')),
    content             TEXT NOT NULL,
    tool_call_id        TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ai_msg_conv_idx  ON ai_messages(conversation_id, created_at);

-- ── ai_memory_items ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ai_memory_items (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID REFERENCES users(id) ON DELETE CASCADE,
    conversation_id     UUID REFERENCES ai_conversations(id) ON DELETE SET NULL,
    content             TEXT NOT NULL,
    importance          REAL NOT NULL DEFAULT 1.0,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ai_mem_user_idx  ON ai_memory_items(user_id, importance DESC);

-- ── ai_usage_log ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ai_usage_log (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID REFERENCES users(id) ON DELETE SET NULL,
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
CREATE INDEX IF NOT EXISTS ai_usage_user_idx  ON ai_usage_log(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ai_usage_conv_idx  ON ai_usage_log(conversation_id);

-- ── ai_prompts ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ai_prompts (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL,
    slug        TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    user_id     UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── ai_prompt_versions ────────────────────────────────────────────────────────
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

SQL_DOWN = """
DROP TABLE IF EXISTS ai_prompt_versions CASCADE;
DROP TABLE IF EXISTS ai_prompts CASCADE;
DROP TABLE IF EXISTS ai_usage_log CASCADE;
DROP TABLE IF EXISTS ai_memory_items CASCADE;
DROP TABLE IF EXISTS ai_messages CASCADE;
DROP TABLE IF EXISTS ai_conversations CASCADE;
"""


async def upgrade(conn) -> None:
    await conn.execute(SQL_UP)


async def downgrade(conn) -> None:
    await conn.execute(SQL_DOWN)
