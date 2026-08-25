"""
WebSocket pre-auth ticket endpoint — POST /api/ws/ticket

WHY: WebSocket upgrade handshakes cannot include an Authorization header
(browser WebSocket API has no API for custom headers). The current
workaround passes the JWT as ?token=<jwt> in the upgrade URL, which is
logged verbatim by every reverse proxy (nginx, Render, Cloudflare) in its
access log — a live token in plaintext log files is a P1 security risk.

FIX: the client calls POST /api/ws/ticket (a normal HTTPS request with
an Authorization header — no exposure) to exchange its JWT for a
short-lived (30 s), single-use, opaque ticket. It then upgrades the WS
with ?ticket=<opaque> instead. The ticket is an unguessable random token,
not a JWT, so even if it appears in a log file it expires in 30 s and can
only be used once.

Ticket lifecycle:
  1. POST /api/ws/ticket  (Authorization: Bearer <jwt>)
     → 200 {"ticket": "<32-byte hex>", "expires_in": 30}
  2. Client opens WS ?ticket=<32-byte hex>
     → WS endpoint calls consume_ticket() to validate + mark used
     → ticket deleted immediately after first use
  3. Any unused ticket is purged after _TTL_S seconds

Implementation: an in-memory dict keyed by the opaque ticket string.
This is correct for single-instance deployments (Render free tier, local
dev). Multi-replica deployments would need a shared TTL store (Redis);
when DATABASE_URL is present a pg-backed store can be added without
changing the HTTP or WS protocol.
"""
from __future__ import annotations

import logging
import secrets
import time
from threading import Lock

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ws", tags=["websocket-auth"])


def _require_jwt_user_id(request: Request) -> str:
    """Extract user_id from JWT Bearer token. Raises 401 if missing or invalid."""
    bearer = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if not bearer:
        raise HTTPException(401, "Authorization header required")
    try:
        from app.core.jwt_utils import decode_access_token
        claims = decode_access_token(bearer)
        user_id = claims.get("sub")
        if not user_id:
            raise HTTPException(401, "Invalid token: missing sub claim")
        return user_id
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(401, "Invalid or expired token")

# ── Ticket store ──────────────────────────────────────────────────────────────

_TTL_S = 30.0          # ticket lifetime in seconds
_MAX_TICKETS = 10_000  # safety cap — prevent unbounded growth under attack

_store: dict[str, dict] = {}  # ticket → {user_id, exp}
_lock  = Lock()


def _purge() -> None:
    """Evict expired tickets. Called on every issue so the dict stays small."""
    now = time.monotonic()
    expired = [k for k, v in _store.items() if v["exp"] <= now]
    for k in expired:
        del _store[k]


def issue_ticket(user_id: str) -> str:
    """Create and store a single-use ticket bound to user_id. Returns the raw ticket."""
    ticket = secrets.token_hex(32)
    with _lock:
        _purge()
        if len(_store) >= _MAX_TICKETS:
            # Safety valve: if the store is full (sustained attack), reject.
            raise RuntimeError("ticket store full")
        _store[ticket] = {
            "user_id": user_id,
            "exp"    : time.monotonic() + _TTL_S,
        }
    log.debug("ws ticket issued user=%s", user_id)
    return ticket


def consume_ticket(ticket: str) -> str | None:
    """
    Validate and consume a ticket. Returns user_id on success, None on
    failure (not found, expired, or already used).

    Atomically deletes the ticket so it can only be used once.
    """
    with _lock:
        entry = _store.pop(ticket, None)
    if entry is None:
        log.debug("ws ticket not found or already used")
        return None
    if time.monotonic() > entry["exp"]:
        log.debug("ws ticket expired")
        return None
    return entry["user_id"]


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.post("/ticket")
async def create_ws_ticket(request: Request) -> dict:
    """
    Exchange a valid JWT for a single-use, 30-second WebSocket ticket.

    The client must include Authorization: Bearer <jwt> as usual.
    The returned ticket should be passed as ?ticket=<value> in the WS URL
    instead of ?token=<jwt>, keeping the JWT out of access logs.

    Response: {"ticket": "<64-char hex>", "expires_in": 30}
    """
    user_id = _require_jwt_user_id(request)
    try:
        ticket = issue_ticket(user_id)
    except RuntimeError:
        return JSONResponse(status_code=503, content={"error": "service busy — retry"})
    return {"ticket": ticket, "expires_in": int(_TTL_S)}
