"""
API Key Authentication — Layer 2 enhancement.

Programmatic access without requiring a user session.
Keys are SHA-256 hashed before storage — the raw key is shown once at creation.

Scopes:
    read        — GET endpoints only
    write       — GET + POST/PUT/PATCH
    admin       — full access including DELETE and admin routes
    agents      — agent execution endpoints only
    marketplace — marketplace read/write only

Usage (FastAPI dependency):
    @router.get("/secure")
    async def endpoint(key_info = Depends(require_api_key(scopes=["read"]))):
        ...

Header format:  Authorization: ApiKey axon_<random_hex>

Storage: Postgres-backed (api_keys table) so keys survive restarts and can be
scoped to an organization. The AXON_DEV_API_KEY env var still works exactly
as before — it is checked in-memory (no DB row, no restart dependency) so
local dev / CI never needs a database to authenticate as the seeded admin key.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import secrets
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional

import asyncpg
from fastapi import HTTPException, Request

log = logging.getLogger(__name__)

_PREFIX      = "axon_"
_KEY_LENGTH  = 32            # bytes → 64 hex chars
_RATE_LIMIT  = 1000          # requests per minute per key
_DEV_KEY_RAW = os.getenv("AXON_DEV_API_KEY", "")


# ── Key record ────────────────────────────────────────────────────────────────

@dataclass
class ApiKeyRecord:
    key_id         : str
    key_hash       : str                    # SHA-256 of raw key
    name           : str
    scopes         : list[str]
    owner_id       : str                    = "system"
    organization_id: Optional[str]          = None
    created_at     : float                  = field(default_factory=time.time)
    expires_at     : Optional[float]        = None
    last_used      : Optional[float]        = None
    request_count  : int                    = 0
    active         : bool                   = True

    def is_expired(self) -> bool:
        return self.expires_at is not None and time.time() > self.expires_at

    def has_scope(self, required: list[str]) -> bool:
        if "admin" in self.scopes:
            return True
        return any(s in self.scopes for s in required)

    def to_dict(self, *, redact: bool = True) -> dict:
        d = asdict(self)
        if redact:
            del d["key_hash"]
        return d


# ── Schema ────────────────────────────────────────────────────────────────────

API_KEYS_SCHEMA = """
CREATE TABLE IF NOT EXISTS api_keys (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    key_id           VARCHAR(32) UNIQUE NOT NULL,
    key_hash         TEXT UNIQUE NOT NULL,
    name             VARCHAR(120) NOT NULL,
    scopes           TEXT[] NOT NULL DEFAULT '{}',
    organization_id  UUID REFERENCES organizations(id) ON DELETE CASCADE,
    owner_id         VARCHAR(120) NOT NULL DEFAULT 'system',
    created_by       UUID,
    updated_by       UUID,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at       TIMESTAMPTZ,
    last_used        TIMESTAMPTZ,
    request_count    INTEGER NOT NULL DEFAULT 0,
    active           BOOLEAN NOT NULL DEFAULT true,
    deleted_at       TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_api_keys_org  ON api_keys(organization_id) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON api_keys(key_hash) WHERE deleted_at IS NULL;
"""


async def init_api_keys_schema(conn: asyncpg.Connection) -> None:
    await conn.execute(API_KEYS_SCHEMA)
    log.info("api_keys schema initialised")


def _hash(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def _dt(ts: Optional[float]) -> Optional[datetime]:
    return datetime.fromtimestamp(ts, tz=timezone.utc) if ts is not None else None


def _epoch(dt: Optional[datetime]) -> Optional[float]:
    return dt.timestamp() if dt is not None else None


def _row_to_record(row: asyncpg.Record) -> ApiKeyRecord:
    return ApiKeyRecord(
        key_id=row["key_id"],
        key_hash=row["key_hash"],
        name=row["name"],
        scopes=list(row["scopes"] or []),
        owner_id=row["owner_id"],
        organization_id=str(row["organization_id"]) if row["organization_id"] else None,
        created_at=_epoch(row["created_at"]),
        expires_at=_epoch(row["expires_at"]),
        last_used=_epoch(row["last_used"]),
        request_count=row["request_count"],
        active=row["active"],
    )


def _dev_key_record() -> ApiKeyRecord:
    return ApiKeyRecord(
        key_id="dev-seed", key_hash=_hash(_DEV_KEY_RAW), name="dev-seed",
        scopes=["admin"], owner_id="system", organization_id=None,
    )


# ── Key management ────────────────────────────────────────────────────────────

async def create_api_key(
    name: str,
    scopes: list[str],
    owner_id: str = "system",
    expires_in_days: Optional[int] = None,
    *,
    organization_id: Optional[str] = None,
    actor_id: Optional[str] = None,
) -> tuple[str, ApiKeyRecord]:
    """
    Generate a new API key.
    Returns (raw_key, record) — raw_key is shown ONCE and never stored.
    """
    from app.core.db import get_pool
    import uuid as _uuid

    raw     = _PREFIX + secrets.token_hex(_KEY_LENGTH)
    h       = _hash(raw)
    key_id  = secrets.token_hex(8)
    expires = time.time() + expires_in_days * 86400 if expires_in_days else None
    actor   = _uuid.UUID(actor_id) if actor_id else None

    row = await get_pool().fetchrow(
        """INSERT INTO api_keys
             (key_id, key_hash, name, scopes, organization_id, owner_id,
              created_by, updated_by, expires_at)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$7,$8)
           RETURNING *""",
        key_id, h, name, scopes,
        _uuid.UUID(organization_id) if organization_id else None,
        owner_id, actor, _dt(expires),
    )
    rec = _row_to_record(row)
    log.info("api_key created key_id=%s name=%r scopes=%s org=%s", key_id, name, scopes, organization_id)
    return raw, rec


async def revoke_api_key(
    key_id: str, *, organization_id: Optional[str] = None, owner_id: Optional[str] = None,
) -> bool:
    """Revoke by key_id. If organization_id/owner_id are given, the key must
    match — prevents revoking a key you don't own via a shared endpoint."""
    from app.core.db import get_pool
    import uuid as _uuid

    clauses, params = ["key_id=$1", "deleted_at IS NULL"], [key_id]
    if organization_id is not None:
        params.append(_uuid.UUID(organization_id))
        clauses.append(f"organization_id=${len(params)}")
    elif owner_id is not None:
        # Personal-key revoke path (no organization_id given): never touch an
        # org-scoped key even if the caller happens to be its owner_id — org
        # keys are only managed via /api/orgs/{org_id}/api-keys.
        clauses.append("organization_id IS NULL")
    if owner_id is not None:
        params.append(owner_id)
        clauses.append(f"owner_id=${len(params)}")
    result = await get_pool().execute(
        f"UPDATE api_keys SET active=false, updated_at=NOW() WHERE {' AND '.join(clauses)}",
        *params,
    )
    return result != "UPDATE 0"


async def list_api_keys(
    owner_id: Optional[str] = None, *, organization_id: Optional[str] = None,
) -> list[ApiKeyRecord]:
    from app.core.db import get_pool, acquire_scoped
    import uuid as _uuid

    if organization_id is not None:
        async with acquire_scoped(organization_id) as conn:
            rows = await conn.fetch(
                "SELECT * FROM api_keys WHERE organization_id=$1 AND deleted_at IS NULL "
                "ORDER BY created_at DESC",
                _uuid.UUID(organization_id),
            )
    elif owner_id is not None:
        # Personal-key listing (no organization_id given): exclude org-scoped
        # keys even if this owner_id created some — they belong to the org
        # key-management surface, not the personal one.
        rows = await get_pool().fetch(
            "SELECT * FROM api_keys WHERE owner_id=$1 AND organization_id IS NULL "
            "AND deleted_at IS NULL ORDER BY created_at DESC",
            owner_id,
        )
    else:
        rows = await get_pool().fetch(
            "SELECT * FROM api_keys WHERE deleted_at IS NULL ORDER BY created_at DESC",
        )
    return [_row_to_record(r) for r in rows]


async def lookup_key(raw_key: str) -> Optional[ApiKeyRecord]:
    if _DEV_KEY_RAW and secrets.compare_digest(raw_key, _DEV_KEY_RAW):
        return _dev_key_record()
    from app.core.db import get_pool
    row = await get_pool().fetchrow(
        "SELECT * FROM api_keys WHERE key_hash=$1 AND deleted_at IS NULL", _hash(raw_key),
    )
    return _row_to_record(row) if row else None


async def _touch_usage(key_hash: str) -> None:
    """Best-effort last_used/request_count bump — never breaks auth."""
    if key_hash == _hash(_DEV_KEY_RAW) and _DEV_KEY_RAW:
        return  # dev key has no DB row to update
    try:
        from app.core.db import get_pool
        await get_pool().execute(
            "UPDATE api_keys SET last_used=NOW(), request_count=request_count+1 WHERE key_hash=$1",
            key_hash,
        )
    except Exception:
        log.debug("api_key usage update failed", exc_info=True)


# ── FastAPI dependency ────────────────────────────────────────────────────────

def require_api_key(scopes: list[str] | None = None):
    """
    FastAPI dependency factory.

        key_info = Depends(require_api_key(["write"]))

    Accepts header:  Authorization: ApiKey axon_<token>
    Also accepts:    X-API-Key: axon_<token>
    """
    required = scopes or []

    async def _dep(request: Request) -> ApiKeyRecord:
        # Extract token
        auth   = request.headers.get("Authorization", "")
        raw    = (
            auth.removeprefix("ApiKey ").strip()
            or request.headers.get("X-API-Key", "").strip()
        )
        if not raw or not raw.startswith(_PREFIX):
            raise HTTPException(401, "Valid API key required (Authorization: ApiKey axon_...)")

        rec = await lookup_key(raw)
        if not rec:
            raise HTTPException(401, "Invalid API key")
        if not rec.active:
            raise HTTPException(401, "API key has been revoked")
        if rec.is_expired():
            raise HTTPException(401, "API key has expired")
        if required and not rec.has_scope(required):
            raise HTTPException(403, f"API key lacks required scope: {required}")

        # Fire-and-forget — matches the org-metering pattern in app/factory.py's
        # metrics_middleware: a DB hiccup must never add latency to (or fail)
        # the actual authenticated request.
        asyncio.create_task(_touch_usage(rec.key_hash))
        rec.last_used = time.time()
        rec.request_count += 1
        return rec

    return _dep
