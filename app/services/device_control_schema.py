"""
Device Control schema — Multi-Device Control feature.

Tables:
  devices                        — registered physical computers
  device_enrollment_tokens       — short-lived enrollment codes (hashed)
  device_control_sessions        — multi-device control sessions
  device_control_session_members — devices in a session + layout geometry
  device_session_authorizations  — short-lived per-session credentials for agents

Follows the repository's idempotent init_*_schema(conn) startup pattern.
DO NOT reference alembic — this is the production migration mechanism here.
"""
from __future__ import annotations

import logging

import asyncpg

log = logging.getLogger(__name__)

DEVICE_CONTROL_SCHEMA = """
-- ─── Devices ──────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS devices (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id  UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    workspace_id     UUID,                       -- optional workspace scope (project-level)
    created_by       UUID REFERENCES users(id) ON DELETE SET NULL,
    name             VARCHAR(120) NOT NULL,
    platform         VARCHAR(20)  NOT NULL DEFAULT 'windows'
                     CHECK (platform IN ('windows','macos','linux','unknown')),
    hostname         VARCHAR(255),
    agent_version    VARCHAR(40),
    status           VARCHAR(30)  NOT NULL DEFAULT 'offline'
                     CHECK (status IN ('online','offline','connecting','revoked','control_active','control_disabled')),
    -- Screen geometry reported by the agent (primary monitor)
    screen_width     INTEGER,
    screen_height    INTEGER,
    -- Virtual canvas position for multi-device layout
    screen_position  JSONB NOT NULL DEFAULT '{"x":0,"y":0}',
    -- Full display config (all monitors) reported by agent
    display_config   JSONB NOT NULL DEFAULT '[]',
    -- Capabilities declared by the agent
    capabilities     JSONB NOT NULL DEFAULT '{}',
    -- Hashed device credential (PBKDF2/SHA-256) — never store plaintext
    credential_hash  TEXT,
    credential_version INTEGER NOT NULL DEFAULT 1,
    -- Fingerprint: deterministic hash of hardware identifiers
    device_fingerprint TEXT,
    -- Timestamps
    registered_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at     TIMESTAMPTZ,
    last_connected_at   TIMESTAMPTZ,
    last_disconnected_at TIMESTAMPTZ,
    revoked_at       TIMESTAMPTZ,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_devices_org        ON devices(organization_id) WHERE revoked_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_devices_org_status ON devices(organization_id, status) WHERE revoked_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_devices_workspace  ON devices(workspace_id) WHERE workspace_id IS NOT NULL AND revoked_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_devices_last_seen  ON devices(last_seen_at DESC) WHERE revoked_at IS NULL;


-- ─── Enrollment tokens (single-use, hashed, short-lived) ────────────────────
CREATE TABLE IF NOT EXISTS device_enrollment_tokens (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id  UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    workspace_id     UUID,
    created_by       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    -- SHA-256 hex of the raw token — never store plaintext
    token_hash       TEXT UNIQUE NOT NULL,
    -- Display hint only: first 4 chars of the raw token so the UI can show "ABCD-****"
    token_prefix     CHAR(4) NOT NULL,
    expires_at       TIMESTAMPTZ NOT NULL,
    used_at          TIMESTAMPTZ,                -- set on first (only) use
    device_id        UUID REFERENCES devices(id) ON DELETE SET NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_enrollment_org     ON device_enrollment_tokens(organization_id);
CREATE INDEX IF NOT EXISTS idx_enrollment_expires ON device_enrollment_tokens(expires_at) WHERE used_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_enrollment_hash    ON device_enrollment_tokens(token_hash) WHERE used_at IS NULL;


-- ─── Device Control Sessions ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS device_control_sessions (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id  UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    workspace_id     UUID,
    created_by       UUID REFERENCES users(id) ON DELETE SET NULL,
    primary_device_id UUID REFERENCES devices(id) ON DELETE SET NULL,
    status           VARCHAR(20) NOT NULL DEFAULT 'draft'
                     CHECK (status IN ('draft','starting','active','stopping','stopped','expired','failed')),
    started_at       TIMESTAMPTZ,
    ended_at         TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_dcs_org        ON device_control_sessions(organization_id);
CREATE INDEX IF NOT EXISTS idx_dcs_org_status ON device_control_sessions(organization_id, status);
CREATE INDEX IF NOT EXISTS idx_dcs_primary    ON device_control_sessions(primary_device_id);


-- ─── Session Members (max 5 enforced in service layer + CHECK) ───────────────
CREATE TABLE IF NOT EXISTS device_control_session_members (
    session_id       UUID NOT NULL REFERENCES device_control_sessions(id) ON DELETE CASCADE,
    device_id        UUID NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    -- Virtual canvas coordinates for edge-switching layout
    position_x       INTEGER NOT NULL DEFAULT 0,
    position_y       INTEGER NOT NULL DEFAULT 0,
    width            INTEGER NOT NULL DEFAULT 1920,
    height           INTEGER NOT NULL DEFAULT 1080,
    sort_order       INTEGER NOT NULL DEFAULT 0,
    enabled          BOOLEAN NOT NULL DEFAULT TRUE,
    last_focus_at    TIMESTAMPTZ,
    PRIMARY KEY (session_id, device_id)
);

CREATE INDEX IF NOT EXISTS idx_dcsm_session ON device_control_session_members(session_id);
CREATE INDEX IF NOT EXISTS idx_dcsm_device  ON device_control_session_members(device_id);


-- ─── Per-session agent authorizations (short-lived, rotated on session stop) ─
CREATE TABLE IF NOT EXISTS device_session_authorizations (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id       UUID NOT NULL REFERENCES device_control_sessions(id) ON DELETE CASCADE,
    device_id        UUID NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    organization_id  UUID NOT NULL,
    -- SHA-256 hex of the raw session token — never store plaintext
    token_hash       TEXT UNIQUE NOT NULL,
    issued_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at       TIMESTAMPTZ NOT NULL,
    revoked_at       TIMESTAMPTZ,
    UNIQUE (session_id, device_id)
);

CREATE INDEX IF NOT EXISTS idx_dsa_session ON device_session_authorizations(session_id) WHERE revoked_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_dsa_device  ON device_session_authorizations(device_id)  WHERE revoked_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_dsa_hash    ON device_session_authorizations(token_hash)  WHERE revoked_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_dsa_expires ON device_session_authorizations(expires_at)  WHERE revoked_at IS NULL;
"""

# Idempotent column-level migrations — run after CREATE TABLE IF NOT EXISTS so
# fresh installs and existing ones both converge to the same schema.
_MIGRATIONS: tuple[str, ...] = (
    "ALTER TABLE devices ADD COLUMN IF NOT EXISTS device_fingerprint TEXT",
    "ALTER TABLE devices ADD COLUMN IF NOT EXISTS credential_version INTEGER NOT NULL DEFAULT 1",
    "ALTER TABLE devices ADD COLUMN IF NOT EXISTS last_connected_at TIMESTAMPTZ",
    "ALTER TABLE devices ADD COLUMN IF NOT EXISTS last_disconnected_at TIMESTAMPTZ",
    "ALTER TABLE devices ADD COLUMN IF NOT EXISTS display_config JSONB NOT NULL DEFAULT '[]'",
)

# Permissions to seed — follow the exact pattern used by app_builder and automation.
DEVICE_PERMISSIONS: list[tuple[str, str, str]] = [
    # viewer — read only
    ("viewer",    "devices",         "read"),
    ("viewer",    "device_sessions", "read"),
    # developer — can register and control
    ("developer", "devices",         "read"),
    ("developer", "devices",         "create"),
    ("developer", "device_sessions", "read"),
    ("developer", "device_sessions", "create"),
    ("developer", "device_sessions", "control"),
    # operator — can control but not register
    ("operator",  "devices",         "read"),
    ("operator",  "device_sessions", "read"),
    ("operator",  "device_sessions", "control"),
    # manager — full device management except revoke
    ("manager",   "devices",         "read"),
    ("manager",   "devices",         "create"),
    ("manager",   "devices",         "update"),
    ("manager",   "device_sessions", "read"),
    ("manager",   "device_sessions", "create"),
    ("manager",   "device_sessions", "control"),
    ("manager",   "device_sessions", "revoke"),
    # admin — full access (admin already has ("*","*") via DEFAULT_PERMISSIONS;
    # seeding here is a no-op due to ON CONFLICT DO NOTHING but is explicit).
    ("admin",     "devices",         "read"),
    ("admin",     "devices",         "create"),
    ("admin",     "devices",         "update"),
    ("admin",     "devices",         "delete"),
    ("admin",     "devices",         "revoke"),
    ("admin",     "device_sessions", "read"),
    ("admin",     "device_sessions", "create"),
    ("admin",     "device_sessions", "control"),
    ("admin",     "device_sessions", "revoke"),
]


async def init_device_control_schema(conn: asyncpg.Connection) -> None:
    """Create device-control tables and seed RBAC permissions. Idempotent."""
    await conn.execute(DEVICE_CONTROL_SCHEMA)
    for stmt in _MIGRATIONS:
        try:
            await conn.execute(stmt)
        except Exception:
            pass  # Column may already exist on older boots
    for role, resource, action in DEVICE_PERMISSIONS:
        await conn.execute(
            "INSERT INTO role_permissions (role, resource, action) VALUES ($1,$2,$3) "
            "ON CONFLICT DO NOTHING",
            role, resource, action,
        )
    log.info("device_control schema initialised")
