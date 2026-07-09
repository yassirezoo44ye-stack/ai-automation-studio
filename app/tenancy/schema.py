"""
Multi-tenant schema — Layer 12 (Enterprise).

Tables created here follow the platform tenancy contract:
every business entity carries organization_id, created_by, updated_by,
created_at, updated_at, and deleted_at (soft delete).

Idempotent: safe to run on every boot alongside init_db().
"""
from __future__ import annotations

import logging

import asyncpg

log = logging.getLogger(__name__)

TENANCY_SCHEMA = """
CREATE TABLE IF NOT EXISTS organizations (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name         VARCHAR(120) NOT NULL,
    slug         VARCHAR(120) UNIQUE NOT NULL,
    kind         VARCHAR(20)  NOT NULL DEFAULT 'organization'
                 CHECK (kind IN ('personal', 'organization', 'enterprise')),
    plan         VARCHAR(20)  NOT NULL DEFAULT 'free',
    settings     JSONB        NOT NULL DEFAULT '{}',
    created_by   UUID REFERENCES users(id) ON DELETE SET NULL,
    updated_by   UUID,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    deleted_at   TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_orgs_slug    ON organizations(slug) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_orgs_creator ON organizations(created_by);

CREATE TABLE IF NOT EXISTS organization_members (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role            VARCHAR(20) NOT NULL DEFAULT 'viewer'
                    CHECK (role IN ('owner','admin','manager','developer','operator','viewer')),
    created_by      UUID,
    updated_by      UUID,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at      TIMESTAMPTZ,
    UNIQUE (organization_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_org_members_org  ON organization_members(organization_id) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_org_members_user ON organization_members(user_id)         WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS invitations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    email           TEXT NOT NULL,
    role            VARCHAR(20) NOT NULL DEFAULT 'viewer',
    token           TEXT UNIQUE NOT NULL,
    status          VARCHAR(20) NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','accepted','revoked','expired')),
    expires_at      TIMESTAMPTZ NOT NULL,
    created_by      UUID,
    updated_by      UUID,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at      TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_invitations_org   ON invitations(organization_id) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_invitations_email ON invitations(email)           WHERE status = 'pending';

CREATE TABLE IF NOT EXISTS teams (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name            VARCHAR(120) NOT NULL,
    description     TEXT,
    created_by      UUID,
    updated_by      UUID,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at      TIMESTAMPTZ,
    UNIQUE (organization_id, name)
);
CREATE INDEX IF NOT EXISTS idx_teams_org ON teams(organization_id) WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS team_members (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id    UUID NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_by UUID,
    updated_by UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ,
    UNIQUE (team_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_team_members_team ON team_members(team_id) WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS role_permissions (
    role       VARCHAR(20)  NOT NULL,
    resource   VARCHAR(60)  NOT NULL,
    action     VARCHAR(30)  NOT NULL,
    PRIMARY KEY (role, resource, action)
);

CREATE TABLE IF NOT EXISTS activity_logs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
    actor_id        UUID,
    actor_email     TEXT,
    action          VARCHAR(100) NOT NULL,
    resource        VARCHAR(100),
    resource_id     TEXT,
    details         JSONB,
    ip_address      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_activity_org     ON activity_logs(organization_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_activity_action  ON activity_logs(action);
"""

# Resource-based permission matrix: role -> [(resource, action)].
# "*" resource grants the action on every resource.
DEFAULT_PERMISSIONS: dict[str, list[tuple[str, str]]] = {
    "owner": [("*", "*")],
    "admin": [
        ("*", "read"), ("*", "create"), ("*", "update"), ("*", "delete"),
        ("members", "manage"), ("billing", "manage"), ("api_keys", "manage"),
        ("teams", "manage"),
    ],
    "manager": [
        ("*", "read"),
        ("projects", "create"), ("projects", "update"),
        ("workflows", "create"), ("workflows", "update"), ("workflows", "execute"),
        ("agents", "create"), ("agents", "update"),
        ("members", "read"), ("teams", "manage"),
    ],
    "developer": [
        ("*", "read"),
        ("projects", "create"), ("projects", "update"),
        ("workflows", "create"), ("workflows", "update"), ("workflows", "execute"),
        ("agents", "create"), ("agents", "update"), ("agents", "execute"),
        ("marketplace", "install"),
    ],
    "operator": [
        ("*", "read"),
        ("workflows", "execute"), ("agents", "execute"), ("jobs", "manage"),
    ],
    "viewer": [("*", "read")],
}


_MIGRATIONS: tuple[str, ...] = (
    # team_members originally shipped without updated_by/updated_at — backfill
    # on deployments where the table already exists from an earlier boot.
    "ALTER TABLE team_members ADD COLUMN IF NOT EXISTS updated_by UUID",
    "ALTER TABLE team_members ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()",
)


async def init_tenancy_schema(conn: asyncpg.Connection) -> None:
    """Create tenancy tables and seed the role-permission matrix (idempotent)."""
    await conn.execute(TENANCY_SCHEMA)
    for stmt in _MIGRATIONS:
        await conn.execute(stmt)
    for role, perms in DEFAULT_PERMISSIONS.items():
        for resource, action in perms:
            await conn.execute(
                "INSERT INTO role_permissions (role, resource, action) VALUES ($1,$2,$3) "
                "ON CONFLICT DO NOTHING",
                role, resource, action,
            )
    log.info("tenancy schema initialised")
