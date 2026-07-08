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
"""
from __future__ import annotations

import hashlib
import logging
import os
import secrets
import time
from dataclasses import dataclass, field, asdict
from typing import Optional

from fastapi import HTTPException, Request

log = logging.getLogger(__name__)

_PREFIX      = "axon_"
_KEY_LENGTH  = 32            # bytes → 64 hex chars
_RATE_LIMIT  = 1000          # requests per minute per key


# ── Key record ────────────────────────────────────────────────────────────────

@dataclass
class ApiKeyRecord:
    key_id     : str
    key_hash   : str                    # SHA-256 of raw key
    name       : str
    scopes     : list[str]
    owner_id   : str                    = "system"
    created_at : float                  = field(default_factory=time.time)
    expires_at : Optional[float]        = None
    last_used  : Optional[float]        = None
    request_count: int                  = 0
    active     : bool                   = True

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


# ── In-memory registry (replace with DB table in production) ──────────────────

_registry: dict[str, ApiKeyRecord] = {}   # key_hash → record


def _hash(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


# ── Key management ────────────────────────────────────────────────────────────

def create_api_key(
    name     : str,
    scopes   : list[str],
    owner_id : str             = "system",
    expires_in_days: Optional[int] = None,
) -> tuple[str, ApiKeyRecord]:
    """
    Generate a new API key.
    Returns (raw_key, record) — raw_key is shown ONCE and never stored.
    """
    raw    = _PREFIX + secrets.token_hex(_KEY_LENGTH)
    h      = _hash(raw)
    key_id = secrets.token_hex(8)
    rec    = ApiKeyRecord(
        key_id     = key_id,
        key_hash   = h,
        name       = name,
        scopes     = scopes,
        owner_id   = owner_id,
        expires_at = time.time() + expires_in_days * 86400 if expires_in_days else None,
    )
    _registry[h] = rec
    log.info("api_key created key_id=%s name=%r scopes=%s", key_id, name, scopes)
    return raw, rec


def revoke_api_key(key_id: str) -> bool:
    for rec in _registry.values():
        if rec.key_id == key_id:
            rec.active = False
            return True
    return False


def list_api_keys(owner_id: Optional[str] = None) -> list[ApiKeyRecord]:
    recs = list(_registry.values())
    if owner_id:
        recs = [r for r in recs if r.owner_id == owner_id]
    return recs


def lookup_key(raw_key: str) -> Optional[ApiKeyRecord]:
    return _registry.get(_hash(raw_key))


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

        rec = lookup_key(raw)
        if not rec:
            raise HTTPException(401, "Invalid API key")
        if not rec.active:
            raise HTTPException(401, "API key has been revoked")
        if rec.is_expired():
            raise HTTPException(401, "API key has expired")
        if required and not rec.has_scope(required):
            raise HTTPException(403, f"API key lacks required scope: {required}")

        # Update usage stats
        rec.last_used     = time.time()
        rec.request_count += 1
        return rec

    return _dep


# ── Seed a default admin key for local dev ────────────────────────────────────

def _seed_dev_key() -> None:
    """Create a long-lived dev key when AXON_DEV_API_KEY env var is set."""
    raw = os.getenv("AXON_DEV_API_KEY", "")
    if not raw:
        return
    h   = _hash(raw)
    if h in _registry:
        return
    _registry[h] = ApiKeyRecord(
        key_id   = "dev-seed",
        key_hash = h,
        name     = "dev-seed",
        scopes   = ["admin"],
        owner_id = "system",
    )
    log.info("api_key: dev seed key registered")


_seed_dev_key()
