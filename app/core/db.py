"""
Database pool management and schema initialisation.

The pool is stored as a module-level variable so routers can call
get_pool() without needing a FastAPI Depends chain. set_pool() is
called once from the lifespan context manager in main.py.
"""
from typing import Optional

import asyncpg

from app.core.config import USER_ID, DEMO_PROJECT_ID
import uuid

_pool: Optional[asyncpg.Pool] = None


def get_pool() -> asyncpg.Pool:
    """Return the active connection pool (guaranteed non-None after lifespan startup)."""
    return _pool  # type: ignore[return-value]


def set_pool(p: asyncpg.Pool) -> None:
    global _pool
    _pool = p


# ── Schema initialisation ─────────────────────────────────────────────────────

async def init_db(conn: asyncpg.Connection) -> None:
    """Create all core tables and seed the demo user/project if absent."""
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            email          TEXT UNIQUE NOT NULL,
            name           TEXT,
            password_hash  TEXT,
            email_verified BOOLEAN NOT NULL DEFAULT false,
            avatar_url     TEXT,
            created_at     TIMESTAMPTZ DEFAULT NOW()
        )
    ''')
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS projects (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name        VARCHAR(100) NOT NULL,
            description TEXT,
            status      VARCHAR(50) DEFAULT 'active',
            created_at  TIMESTAMPTZ DEFAULT NOW(),
            updated_at  TIMESTAMPTZ DEFAULT NOW()
        )
    ''')
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS conversations (
            id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            title      VARCHAR(200) NOT NULL DEFAULT 'New conversation',
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
    ''')
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            role            VARCHAR(20) NOT NULL,
            content         TEXT NOT NULL,
            created_at      TIMESTAMPTZ DEFAULT NOW()
        )
    ''')
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS agent_runs (
            id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id   UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            agent_type   VARCHAR(50) NOT NULL,
            input_data   JSONB,
            output_data  JSONB,
            status       VARCHAR(50) DEFAULT 'pending',
            started_at   TIMESTAMPTZ DEFAULT NOW(),
            completed_at TIMESTAMPTZ,
            error_message TEXT
        )
    ''')
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS usage_logs (
            id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            action     VARCHAR(100) NOT NULL,
            details    JSONB,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    ''')
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS subscriptions (
            id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            email                    TEXT UNIQUE NOT NULL,
            stripe_customer_id       TEXT,
            stripe_subscription_id   TEXT,
            status                   TEXT DEFAULT 'inactive',
            current_period_end       TIMESTAMPTZ,
            created_at               TIMESTAMPTZ DEFAULT NOW(),
            updated_at               TIMESTAMPTZ DEFAULT NOW()
        )
    ''')
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS trials (
            email      TEXT PRIMARY KEY,
            started_at TIMESTAMPTZ DEFAULT NOW()
        )
    ''')
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS design_canvases (
            id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id  UUID        NOT NULL,
            name        TEXT        NOT NULL DEFAULT 'Untitled Design',
            canvas_json JSONB       NOT NULL DEFAULT '{}',
            thumbnail   TEXT,
            width       INTEGER     NOT NULL DEFAULT 1080,
            height      INTEGER     NOT NULL DEFAULT 1080,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    ''')
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS dc_project_idx ON design_canvases(project_id)"
    )

    # Seed demo user only when explicitly requested (e.g. local dev / CI).
    # Never seed in production — the demo UUID is a known value and represents
    # a data isolation risk in a multi-user environment.
    import os as _os
    if _os.environ.get("SEED_DEMO_USER", "").lower() == "true":
        await conn.execute(
            "INSERT INTO users (id, email, name) VALUES ($1, $2, $3) ON CONFLICT (id) DO NOTHING",
            USER_ID, "test@example.com", "Test User",
        )
        await conn.execute(
            "INSERT INTO projects (id, user_id, name, description) VALUES ($1, $2, $3, $4) ON CONFLICT (id) DO NOTHING",
            DEMO_PROJECT_ID, USER_ID, "Demo Project", "Default project for the chat UI",
        )


async def ensure_agents_table() -> None:
    async with get_pool().acquire() as conn:
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS ai_agents (
                id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id        UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                project_id     UUID REFERENCES projects(id) ON DELETE SET NULL,
                name           VARCHAR(100) NOT NULL,
                avatar         VARCHAR(10) DEFAULT '🤖',
                description    TEXT,
                system_prompt  TEXT NOT NULL,
                model          VARCHAR(80) DEFAULT 'claude-sonnet-4-6',
                temperature    FLOAT DEFAULT 1.0,
                message_count  INT DEFAULT 0,
                created_at     TIMESTAMPTZ DEFAULT NOW(),
                updated_at     TIMESTAMPTZ DEFAULT NOW()
            )
        ''')


async def ensure_tasks_table() -> None:
    async with get_pool().acquire() as conn:
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS tasks (
                id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                owner_email     TEXT NOT NULL,
                project_id      UUID REFERENCES projects(id) ON DELETE SET NULL,
                conversation_id UUID REFERENCES conversations(id) ON DELETE SET NULL,
                title           TEXT NOT NULL,
                notes           TEXT,
                status          TEXT NOT NULL DEFAULT 'pending',
                priority        TEXT NOT NULL DEFAULT 'medium',
                category        TEXT,
                tags            TEXT[] NOT NULL DEFAULT '{}',
                due_date        TIMESTAMPTZ,
                recurrence      TEXT NOT NULL DEFAULT 'none',
                source          TEXT NOT NULL DEFAULT 'manual',
                created_at      TIMESTAMPTZ DEFAULT NOW(),
                updated_at      TIMESTAMPTZ DEFAULT NOW(),
                completed_at    TIMESTAMPTZ
            )
        ''')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_tasks_owner   ON tasks(owner_email)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id)')

        # Auth tables
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS user_sessions (
                id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                refresh_token TEXT NOT NULL UNIQUE,
                ip_address    TEXT,
                user_agent    TEXT,
                created_at    TIMESTAMPTZ DEFAULT NOW(),
                last_used_at  TIMESTAMPTZ,
                expires_at    TIMESTAMPTZ NOT NULL
            )
        ''')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_sessions_user ON user_sessions(user_id)')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS email_verification_tokens (
                token      TEXT PRIMARY KEY,
                user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                expires_at TIMESTAMPTZ NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        ''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS password_reset_tokens (
                token      TEXT PRIMARY KEY,
                user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                expires_at TIMESTAMPTZ NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        ''')


async def ensure_audit_table() -> None:
    async with get_pool().acquire() as conn:
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS audit_logs (
                id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                actor_email  TEXT NOT NULL,
                action       VARCHAR(100) NOT NULL,
                resource     VARCHAR(100),
                resource_id  TEXT,
                details      JSONB,
                ip_address   TEXT,
                created_at   TIMESTAMPTZ DEFAULT NOW()
            )
        ''')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_audit_actor    ON audit_logs(actor_email)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_audit_action   ON audit_logs(action)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_audit_created  ON audit_logs(created_at)')


async def write_audit(
    actor_email: str,
    action: str,
    *,
    resource: str | None = None,
    resource_id: str | None = None,
    details: dict | None = None,
    ip_address: str | None = None,
) -> None:
    """Fire-and-forget audit record — errors are swallowed to never break the request path."""
    import json
    try:
        async with get_pool().acquire() as conn:
            await conn.execute(
                "INSERT INTO audit_logs (actor_email, action, resource, resource_id, details, ip_address) "
                "VALUES ($1, $2, $3, $4, $5, $6)",
                actor_email, action, resource, resource_id,
                json.dumps(details) if details else None, ip_address,
            )
    except Exception:
        pass
