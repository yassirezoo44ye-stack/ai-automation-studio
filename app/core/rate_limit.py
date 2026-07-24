"""
Sliding-window rate limiter.

Backend priority:
  1. Redis  (REDIS_URL set)  — shared across all instances, atomic INCR
  2. In-process dict         — single-instance fallback (original behaviour)

The public interface is unchanged so all existing callers work without modification.
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Optional

from fastapi import HTTPException, Request

log = logging.getLogger(__name__)

# ── In-process fallback (unchanged from original) ────────────────────────────

rl_store: dict[str, list[float]] = defaultdict(list)

# Every distinct key (one per client IP, or per user+IP for ai_rate_limit)
# lives in rl_store forever once created — check_rate_limit only ever
# trims a key's OWN list, it never removes the key itself, even once that
# list is empty. On a long-running process this is unbounded growth keyed
# by every IP/user that has ever made one request: factory.py's global
# middleware alone creates one "global:{ip}" entry per distinct visitor,
# with no upper bound. This periodic sweep — ported from the per-module
# store app/core/security.py used to keep before it became a re-export
# shim over this module (see that module's docstring) — evicts any key
# whose entire list has aged out of its own window, bounding memory to
# "keys actually active in the last ~window seconds" instead of "every
# key ever seen".
_last_gc: float = 0.0
_GC_INTERVAL = 300.0  # sweep at most once per 5 minutes


def _maybe_gc(now: float, window: int) -> None:
    global _last_gc
    if now - _last_gc < _GC_INTERVAL:
        return
    _last_gc = now
    dead = [k for k, ts in rl_store.items() if not any(now - t < window for t in ts)]
    for k in dead:
        del rl_store[k]


def check_rate_limit(key: str, max_calls: int = 10, window: int = 60) -> bool:
    """Return True if the call is allowed; False if the limit is exceeded."""
    now = time.time()
    _maybe_gc(now, window)
    rl_store[key] = [t for t in rl_store[key] if now - t < window]
    if len(rl_store[key]) >= max_calls:
        return False
    rl_store[key].append(now)
    return True


# ── Redis-backed async version ────────────────────────────────────────────────

async def check_rate_limit_async(
    key      : str,
    max_calls: int = 10,
    window   : int = 60,
) -> bool:
    """
    Async rate limiter — uses Redis when available, falls back to in-process.
    Atomic: safe under concurrent requests across multiple processes.
    """
    try:
        from app.core.cache import get_redis
        cache = await get_redis()
        if cache.backend == "redis":
            rkey    = f"rl:{key}"
            count   = await cache.incr(rkey, ttl=window)
            allowed = count <= max_calls
            if not allowed:
                log.debug("rate_limit exceeded key=%s count=%d max=%d", key, count, max_calls)
            return allowed
    except Exception as exc:
        log.debug("rate_limit redis fallback: %s", exc)

    return check_rate_limit(key, max_calls, window)


def _real_ip(request: Request) -> str:
    """The rightmost X-Forwarded-For entry — appended by the nearest (trusted)
    proxy. Any earlier entries are client-supplied and spoofable, so using
    them as the rate-limit key would let an attacker evade or conflate limits
    by varying a fake leftmost IP (M-13)."""
    xff = request.headers.get("X-Forwarded-For", "")
    ips = [x.strip() for x in xff.split(",") if x.strip()]
    return ips[-1] if ips else (request.client.host if request.client else "unknown")


def require_rate_limit(
    request   : Request,
    *,
    key_prefix: str           = "req",
    max_calls : int           = 60,
    window    : int           = 60,
    error_detail: Optional[str] = None,
) -> None:
    """FastAPI sync dependency: raise HTTP 429 when the limit is exceeded."""
    key = f"{key_prefix}:{_real_ip(request)}"
    if not check_rate_limit(key, max_calls, window):
        raise HTTPException(
            status_code = 429,
            detail      = error_detail or f"Rate limit exceeded — max {max_calls} per {window}s",
            headers     = {"Retry-After": str(window)},
        )


def ai_rate_limit(request: Request, max_calls: int = 20, window: int = 60) -> None:
    """Stricter limit for AI inference endpoints (cost-exposure protection)."""
    from app.core.auth import owner_email as _owner_email
    owner = _owner_email(request)
    key = f"ai:{owner}:{_real_ip(request)}"
    if not check_rate_limit(key, max_calls=max_calls, window=window):
        raise HTTPException(429, "Too many AI requests — please wait a moment.")


def make_rate_limit_dep(
    key_prefix  : str = "req",
    max_calls   : int = 60,
    window      : int = 60,
    error_detail: Optional[str] = None,
):
    """
    Factory for FastAPI Depends() usage:
        _dep = Depends(make_rate_limit_dep("youtube", max_calls=20, window=60))
    """
    def _dep(request: Request) -> None:
        require_rate_limit(
            request,
            key_prefix   = key_prefix,
            max_calls    = max_calls,
            window       = window,
            error_detail = error_detail,
        )
    return _dep


async def require_rate_limit_async(
    request   : Request,
    *,
    key_prefix: str           = "req",
    max_calls : int           = 60,
    window    : int           = 60,
    error_detail: Optional[str] = None,
) -> None:
    """FastAPI async dependency — uses Redis when available."""
    key = f"{key_prefix}:{_real_ip(request)}"
    if not await check_rate_limit_async(key, max_calls, window):
        raise HTTPException(
            status_code = 429,
            detail      = error_detail or f"Rate limit exceeded — max {max_calls} per {window}s",
            headers     = {"Retry-After": str(window)},
        )
