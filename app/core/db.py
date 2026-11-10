"""
Axon Automation Studio — database access.

Two access paths live here:

1. SQLAlchemy async engine + tenant-scoped sessions (the Axon core, schema
   ``axon`` created by init_db.sql). Every session is bound to exactly one
   ``TenantContext``. At the start of *every* transaction the session switches
   to the non-privileged role ``axon_app`` (``SET LOCAL ROLE``) and sets the
   ``app.current_tenant_id`` / ``app.current_user_id`` / ``app.current_scopes``
   GUCs with ``is_local => true``. PostgreSQL row level security then confines
   every statement to that tenant. Because the settings are transaction-local
   they are discarded on commit/rollback, so a pooled connection never carries
   one tenant's identity into another request; the ``after_begin`` hook
   re-applies them if a caller commits and keeps working. A session without a
   tenant refuses to open a transaction at all (fail closed).

2. The legacy asyncpg pool (``get_pool`` / ``acquire_scoped`` / ``init_db``)
   used by the existing routers on the ``public`` schema. Its API is
   unchanged so the current call sites keep working while modules move to
   the tenant-scoped sessions.
"""
from __future__ import annotations

import logging
import os
import re
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Annotated, Any

import asyncpg
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import event, text
from sqlalchemy.engine import URL, Connection, make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, SessionTransaction

from app.core.config import DEMO_PROJECT_ID, USER_ID, AxonSettings, settings
from app.core.observability.tracer import get_tracer

log = logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════════════════════════
# Tenant context
# ═════════════════════════════════════════════════════════════════════════════

_SCOPE_RE = re.compile(r"^(?:\*|[a-z][a-z_]*:(?:[a-z][a-z_]*|\*))$")


class TenantContextError(PermissionError):
    """A database session was used without a valid tenant context."""


class ScopeError(PermissionError):
    """The current principal lacks a required scope."""


def scope_covers(held: frozenset[str] | set[str], required: str) -> bool:
    """Python twin of ``axon.scope_covers()`` in init_db.sql — keep them identical."""
    if required in held or "*" in held:
        return True
    resource = required.split(":", 1)[0]
    return f"{resource}:*" in held


@dataclass(frozen=True, slots=True)
class TenantContext:
    """Who is acting, on behalf of which tenant, with which scopes.

    Built by the authentication layer from a verified session or API key —
    never from client-supplied headers or body fields.
    """

    tenant_id: uuid.UUID
    user_id: uuid.UUID | None = None
    scopes: frozenset[str] = field(default_factory=frozenset)
    api_key_id: uuid.UUID | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.tenant_id, uuid.UUID):
            raise TenantContextError("tenant_id must be a uuid.UUID")
        for name in ("user_id", "api_key_id"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, uuid.UUID):
                raise TenantContextError(f"{name} must be a uuid.UUID or None")
        if not isinstance(self.scopes, frozenset):
            object.__setattr__(self, "scopes", frozenset(self.scopes))
        bad = sorted(s for s in self.scopes if not isinstance(s, str) or not _SCOPE_RE.match(s))
        if bad:
            raise TenantContextError(f"invalid scope(s): {bad!r}")

    def has_scope(self, required: str) -> bool:
        return scope_covers(self.scopes, required)

    def require_scope(self, *required: str) -> None:
        missing = [s for s in required if not self.has_scope(s)]
        if missing:
            raise ScopeError(f"missing scope(s): {', '.join(missing)}")


_current_tenant: ContextVar[TenantContext | None] = ContextVar("axon_current_tenant", default=None)


def current_tenant() -> TenantContext | None:
    """The tenant bound to the running task, if a tenant session is open."""
    return _current_tenant.get()


def require_tenant() -> TenantContext:
    ctx = _current_tenant.get()
    if ctx is None:
        raise TenantContextError("no tenant context is active")
    return ctx


# ═════════════════════════════════════════════════════════════════════════════
# Engine and sessions (SQLAlchemy async)
# ═════════════════════════════════════════════════════════════════════════════

_TENANT_KEY = "axon.tenant"
_SYSTEM_KEY = "axon.system_reason"

_SSLMODE_TO_ASYNCPG: dict[str, Any] = {
    "disable": False,
    "allow": "allow",
    "prefer": "prefer",
    "require": "require",
    "verify-ca": "verify-ca",
    "verify-full": "verify-full",
}


def build_async_url(raw_url: str) -> tuple[URL, dict[str, Any]]:
    """Turn a libpq-style DATABASE_URL into an asyncpg SQLAlchemy URL + connect args.

    ``sslmode`` is a libpq option asyncpg does not accept as a query parameter,
    so it is moved into ``connect_args["ssl"]``.
    """
    url = make_url(raw_url)
    if url.get_backend_name() not in {"postgresql", "postgres"}:
        raise ValueError("only PostgreSQL is supported")
    query = dict(url.query)
    connect_args: dict[str, Any] = {}
    sslmode = query.pop("sslmode", None) or query.pop("ssl", None)
    if sslmode is not None:
        mode = str(sslmode if isinstance(sslmode, str) else sslmode[0]).lower()
        if mode not in _SSLMODE_TO_ASYNCPG:
            raise ValueError(f"unsupported sslmode {mode!r}")
        connect_args["ssl"] = _SSLMODE_TO_ASYNCPG[mode]
    url = url.set(drivername="postgresql+asyncpg", query=query)
    return url, connect_args


class AxonSyncSession(Session):
    """Session class whose transactions always carry the tenant context."""


@event.listens_for(AxonSyncSession, "after_begin")
def _apply_tenant_context(session: Session, transaction: SessionTransaction, connection: Connection) -> None:
    ctx: TenantContext | None = session.info.get(_TENANT_KEY)
    if ctx is None:
        if session.info.get(_SYSTEM_KEY):
            # Trusted maintenance work: make sure no tenant identity lingers.
            connection.execute(text("SELECT set_config('app.current_tenant_id', '', true)"))
            return
        raise TenantContextError("refusing to open a transaction without a tenant context")

    role = session.info.get("axon.rls_role")
    if role:
        # Identifier validated by AxonSettings (lowercase PostgreSQL identifier).
        connection.exec_driver_sql(f'SET LOCAL ROLE "{role}"')
    connection.execute(
        text(
            "SELECT set_config('app.current_tenant_id', :tenant_id, true), "
            "set_config('app.current_user_id', :user_id, true), "
            "set_config('app.current_scopes', :scopes, true)"
        ),
        {
            "tenant_id": str(ctx.tenant_id),
            "user_id": str(ctx.user_id) if ctx.user_id else "",
            "scopes": " ".join(sorted(ctx.scopes)),
        },
    )


class Database:
    """Owns one async engine and its session factory."""

    def __init__(self, cfg: AxonSettings, *, url: str | None = None) -> None:
        self._cfg = cfg
        async_url, connect_args = build_async_url(url or cfg.database_url.get_secret_value())
        server_settings = {"application_name": "axon-api"}
        if cfg.db_statement_timeout_ms:
            server_settings["statement_timeout"] = str(cfg.db_statement_timeout_ms)
        connect_args["server_settings"] = server_settings
        self.engine: AsyncEngine = create_async_engine(
            async_url,
            pool_size=cfg.db_pool_size,
            max_overflow=cfg.db_max_overflow,
            pool_timeout=cfg.db_pool_timeout_s,
            pool_recycle=cfg.db_pool_recycle_s,
            pool_pre_ping=True,
            echo=cfg.db_echo,
            connect_args=connect_args,
        )
        self._factory = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            sync_session_class=AxonSyncSession,
            expire_on_commit=False,
            autoflush=False,
        )

    @property
    def rls_role(self) -> str:
        return self._cfg.db_rls_role

    @asynccontextmanager
    async def tenant_session(self, ctx: TenantContext) -> AsyncIterator[AsyncSession]:
        """Session confined to ``ctx.tenant_id``. Commits on success, rolls back on error."""
        if not isinstance(ctx, TenantContext):
            raise TenantContextError("tenant_session() needs a TenantContext")
        session = self._factory()
        session.info[_TENANT_KEY] = ctx
        session.info["axon.rls_role"] = self.rls_role
        token = _current_tenant.set(ctx)
        tracer = get_tracer()
        try:
            with tracer.start_span("db.tenant_session", service="database") as span:
                span.set_tag("tenant_id", str(ctx.tenant_id))
                try:
                    yield session
                    await session.commit()
                except BaseException:
                    await session.rollback()
                    raise
        finally:
            _current_tenant.reset(token)
            await session.close()

    @asynccontextmanager
    async def system_session(self, reason: str) -> AsyncIterator[AsyncSession]:
        """Session WITHOUT tenant scoping, for bootstrap, migrations and provisioning.

        Runs as the login role with the tenant GUC cleared. ``reason`` is
        required and logged so every unscoped access is attributable.
        """
        if not reason or not reason.strip():
            raise ValueError("system_session() requires a reason")
        if _current_tenant.get() is not None:
            raise TenantContextError("system_session() cannot be opened inside a tenant session")
        log.info("axon db: system session opened (%s)", reason)
        session = self._factory()
        session.info[_SYSTEM_KEY] = reason
        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def ping(self) -> bool:
        async with self.engine.connect() as conn:
            return (await conn.scalar(text("SELECT 1"))) == 1

    async def dispose(self) -> None:
        await self.engine.dispose()


_database: Database | None = None


def get_database() -> Database:
    """Process-wide Database, created lazily on first use."""
    global _database
    if _database is None:
        _database = Database(settings)
    return _database


def set_database(db: Database | None) -> None:
    """Replace the process-wide Database (tests, alternate URLs)."""
    global _database
    _database = db


def get_engine() -> AsyncEngine:
    return get_database().engine


def tenant_session(ctx: TenantContext):
    """Shortcut for ``get_database().tenant_session(ctx)``."""
    return get_database().tenant_session(ctx)


def system_session(reason: str):
    """Shortcut for ``get_database().system_session(reason)``."""
    return get_database().system_session(reason)


async def dispose_engine() -> None:
    """Close the SQLAlchemy pool (called from the app lifespan on shutdown)."""
    global _database
    if _database is not None:
        await _database.dispose()
        _database = None


async def check_database_health() -> bool:
    try:
        return await get_database().ping()
    except Exception:
        log.warning("axon db: health check failed", exc_info=True)
        return False


# ── FastAPI dependencies ─────────────────────────────────────────────────────

REQUEST_TENANT_ATTR = "axon_tenant"


def tenant_from_request(request: Request) -> TenantContext:
    """The TenantContext the auth layer stored on ``request.state``; 401 if absent."""
    ctx = getattr(request.state, REQUEST_TENANT_ATTR, None)
    if not isinstance(ctx, TenantContext):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return ctx


TenantDep = Annotated[TenantContext, Depends(tenant_from_request)]


async def get_tenant_db(ctx: TenantDep) -> AsyncIterator[AsyncSession]:
    """``Depends(get_tenant_db)`` → a session scoped to the caller's tenant."""
    async with tenant_session(ctx) as session:
        yield session


def require_scopes(*scopes: str):
    """``Depends(require_scopes("workflows:execute"))`` → 403 unless every scope is held."""
    for s in scopes:
        if not _SCOPE_RE.match(s):
            raise ValueError(f"invalid scope {s!r}")

    def _check(ctx: TenantDep) -> TenantContext:
        try:
            ctx.require_scope(*scopes)
        except ScopeError:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient scope") from None
        return ctx

    return _check


# ═════════════════════════════════════════════════════════════════════════════
# Legacy asyncpg pool (public schema)
# ═════════════════════════════════════════════════════════════════════════════

_pool: asyncpg.Pool | None = None

# When the pool is saturated, waiting forever turns one slow spot into a
# platform-wide stall — fail fast instead so callers surface a clear error
# (and the request-level bulkheads shed load upstream).
_ACQUIRE_TIMEOUT_S = settings.db_pool_timeout_s


def get_pool() -> asyncpg.Pool:
    """Return the active connection pool (guaranteed non-None after lifespan startup)."""
    return _pool  # type: ignore[return-value]


def set_pool(p: asyncpg.Pool) -> None:
    global _pool
    _pool = p


@asynccontextmanager
async def acquire_scoped(org_id: str):
    """
    Acquire a connection with the Postgres session GUC `app.current_org_id`
    set for the duration of one transaction — Row Level Security policies
    (see app/tenancy/rls.py) read this to restrict visible rows to that
    organization.

    A plain `pool.acquire()` never sets this GUC, so RLS-protected tables
    remain fully visible to ordinary queries elsewhere in the app — this is
    additive defense-in-depth for the tenancy-critical services
    (TenancyService, UsageService), not a blanket access-control rewrite.
    """
    tracer = get_tracer()
    with tracer.start_span("db.acquire_scoped", service="database") as span:
        span.set_tag("organization_id", org_id)
        async with get_pool().acquire(timeout=_ACQUIRE_TIMEOUT_S) as conn, conn.transaction():
            await conn.execute("SELECT set_config('app.current_org_id', $1, true)", org_id)
            yield conn


# ── Schema initialisation ─────────────────────────────────────────────────────

async def init_db(conn: asyncpg.Connection) -> None:
    """Create all core tables and seed the demo user/project if absent."""
    from app.core.oauth_store import DDL as oauth_slots_ddl
    await conn.execute(oauth_slots_ddl)
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
    # Idempotent column migrations — safe to run on existing tables.
    for _col_sql in (
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash TEXT",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified BOOLEAN NOT NULL DEFAULT false",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_url TEXT",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS name TEXT",
    ):
        await conn.execute(_col_sql)
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
    if os.environ.get("SEED_DEMO_USER", "").lower() == "true":
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
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS mfa_secrets (
                user_id      UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                secret       TEXT NOT NULL,
                enabled      BOOLEAN NOT NULL DEFAULT false,
                backup_codes TEXT[] NOT NULL DEFAULT '{}',
                created_at   TIMESTAMPTZ DEFAULT NOW(),
                updated_at   TIMESTAMPTZ DEFAULT NOW()
            )
        ''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS mfa_challenges (
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

    from app.core.observability.config import get_observability_config
    if not get_observability_config().audit_enabled:
        return

    try:
        async with get_pool().acquire() as conn:
            await conn.execute(
                "INSERT INTO audit_logs (actor_email, action, resource, resource_id, details, ip_address) "
                "VALUES ($1, $2, $3, $4, $5, $6)",
                actor_email, action, resource, resource_id,
                json.dumps(details) if details else None, ip_address,
            )
    except Exception:
        # Never break the request path, but never lose an audit write silently.
        log.warning("audit write failed for action %s", action, exc_info=True)
