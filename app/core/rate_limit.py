"""
In-process sliding-window rate limiter.

Thread-safe for asyncio (GIL protects the dict operations).
For multi-process deployments (Render multi-instance), replace
rl_store with a Redis backend via the same interface.
"""
import time
from collections import defaultdict
from typing import Optional

from fastapi import HTTPException, Request

# Shared mutable store — one entry per (key, window) pair.
rl_store: dict[str, list[float]] = defaultdict(list)


def check_rate_limit(key: str, max_calls: int = 10, window: int = 60) -> bool:
    """Return True if the call is allowed; False if the limit is exceeded.

    Prunes expired timestamps before checking, so the window slides correctly.
    """
    now = time.time()
    rl_store[key] = [t for t in rl_store[key] if now - t < window]
    if len(rl_store[key]) >= max_calls:
        return False
    rl_store[key].append(now)
    return True


def require_rate_limit(
    request: Request,
    *,
    key_prefix: str = "req",
    max_calls: int = 60,
    window: int = 60,
    error_detail: Optional[str] = None,
) -> None:
    """FastAPI dependency: raise HTTP 429 when the limit is exceeded.

    Key is scoped to (prefix, client IP) to prevent per-IP flooding.
    """
    xff = request.headers.get("X-Forwarded-For", "")
    ips = [x.strip() for x in xff.split(",") if x.strip()]
    # Use the rightmost IP — reverse-proxy infrastructure (e.g. Render) appends
    # the real client IP as the last entry, so attackers cannot spoof it by
    # prepending values to the header.
    ip = ips[-1] if ips else (request.client.host if request.client else "unknown")
    key = f"{key_prefix}:{ip}"
    if not check_rate_limit(key, max_calls=max_calls, window=window):
        raise HTTPException(
            status_code=429,
            detail=error_detail or "Too many requests — please slow down.",
            headers={"Retry-After": str(window)},
        )


def make_rate_limit_dep(
    key_prefix: str,
    max_calls: int,
    window: int = 60,
    error_detail: Optional[str] = None,
):
    """Return a FastAPI dependency that enforces a per-IP rate limit.

    Usage::

        from fastapi import Depends
        _dep = make_rate_limit_dep("auth", max_calls=10)

        @router.post("/login")
        async def login(_, _rl=Depends(_dep)):
            ...
    """
    def _dep(request: Request) -> None:
        require_rate_limit(
            request,
            key_prefix=key_prefix,
            max_calls=max_calls,
            window=window,
            error_detail=error_detail,
        )
    return _dep


def ai_rate_limit(request: Request, max_calls: int = 20, window: int = 60) -> None:
    """Stricter limit for AI inference endpoints (cost-exposure protection)."""
    from app.core.auth import owner_email as _owner_email
    owner = _owner_email(request)
    xff = request.headers.get("X-Forwarded-For", "")
    ips = [x.strip() for x in xff.split(",") if x.strip()]
    ip = ips[-1] if ips else (request.client.host if request.client else "unknown")
    key = f"ai:{owner}:{ip}"
    if not check_rate_limit(key, max_calls=max_calls, window=window):
        raise HTTPException(429, "Too many AI requests — please wait a moment.")
