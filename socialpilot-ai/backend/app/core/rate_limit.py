"""Rate limiting for abuse-prone endpoints (auth, etc.), backed by slowapi.

Uses Redis as the shared limiter storage when configured, so limits hold across
multiple API replicas. Falls back to in-memory storage (single-process only —
fine for local dev/tests, not for a multi-replica production deployment).
"""
from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import get_settings

settings = get_settings()

_storage_uri = settings.rate_limit_storage_url or settings.redis_url

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=_storage_uri,
    strategy="fixed-window",
)
