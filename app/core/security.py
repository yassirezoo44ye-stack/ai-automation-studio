"""
Rate limiting and per-request cost-protection guards.
"""
import time as _time
from collections import defaultdict

from fastapi import HTTPException, Request

from app.core.auth import owner_email

# In-memory sliding-window store  {key: [timestamp, ...]}
_rl_store: dict[str, list[float]] = defaultdict(list)
_last_gc: float = 0.0
_GC_INTERVAL = 300.0  # evict empty/stale buckets every 5 minutes


def _maybe_gc(now: float, window: int) -> None:
    global _last_gc
    if now - _last_gc < _GC_INTERVAL:
        return
    _last_gc = now
    dead = [k for k, ts in _rl_store.items() if not any(now - t < window for t in ts)]
    for k in dead:
        del _rl_store[k]


def check_rate_limit(key: str, max_calls: int = 10, window: int = 60) -> bool:
    """Return True if the request is within the limit, False if it must be blocked."""
    now = _time.time()
    _maybe_gc(now, window)
    _rl_store[key] = [t for t in _rl_store[key] if now - t < window]
    if len(_rl_store[key]) >= max_calls:
        return False
    _rl_store[key].append(now)
    return True


def ai_rate_limit(request: Request, max_calls: int = 20, window: int = 60) -> None:
    """Guard any Claude-backed endpoint against cost abuse by a single account/IP.

    Raises HTTP 429 if the caller exceeds `max_calls` within `window` seconds.
    Keyed by (owner_email, client_ip) so different users don't share a bucket.
    """
    user  = owner_email(request)
    ip    = (
        request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or (request.client.host if request.client else "unknown")
    )
    if not check_rate_limit(f"ai:{user}:{ip}", max_calls=max_calls, window=window):
        raise HTTPException(429, "Too many AI requests. Please wait a moment and try again.")
