"""
Response cache for the AI gateway.

Uses an in-process TTL cache (no Redis dependency).
Caching is keyed on a deterministic hash of the request content.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Optional

from app.ai.models import CompletionRequest, CompletionResponse

log = logging.getLogger(__name__)


class _CacheEntry:
    __slots__ = ("response", "expires_at")

    def __init__(self, response: CompletionResponse, ttl: int) -> None:
        self.response   = response
        self.expires_at = time.monotonic() + ttl


class ResponseCache:
    """LRU-ish in-memory cache with TTL eviction."""

    def __init__(self, max_size: int = 1000) -> None:
        self._store: dict[str, _CacheEntry] = {}
        self._max   = max_size

    # ── Public interface ──────────────────────────────────────────────────────

    def get(self, key: str) -> Optional[CompletionResponse]:
        entry = self._store.get(key)
        if not entry:
            return None
        if time.monotonic() > entry.expires_at:
            del self._store[key]
            return None
        log.debug("Cache HIT  key=%s…", key[:12])
        resp = entry.response.model_copy()
        resp.cached = True
        resp.usage  = resp.usage.model_copy(update={"cached": True})
        return resp

    def set(self, key: str, response: CompletionResponse, ttl: int) -> None:
        if ttl <= 0:
            return
        self._evict_expired()
        if len(self._store) >= self._max:
            # Evict the oldest entry
            oldest = next(iter(self._store))
            del self._store[oldest]
        self._store[key] = _CacheEntry(response, ttl)
        log.debug("Cache STORE key=%s… ttl=%ds", key[:12], ttl)

    def invalidate(self, key: str) -> None:
        self._store.pop(key, None)

    def clear(self) -> None:
        self._store.clear()

    def stats(self) -> dict:
        now = time.monotonic()
        live  = sum(1 for e in self._store.values() if e.expires_at > now)
        return {"total": len(self._store), "live": live, "max": self._max}

    # ── Key generation ────────────────────────────────────────────────────────

    @staticmethod
    def make_key(request: CompletionRequest) -> str:
        """Deterministic cache key based on all request fields that affect the response."""
        payload = {
            "provider":    request.provider,
            "model":       request.model,
            "messages":    [m.model_dump() for m in request.messages],
            "max_tokens":  request.max_tokens,
            "temperature": request.temperature,
            "system":      request.system,
            "tools":       [t.model_dump() for t in (request.tools or [])],
        }
        raw = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _evict_expired(self) -> None:
        now = time.monotonic()
        dead = [k for k, e in self._store.items() if e.expires_at <= now]
        for k in dead:
            del self._store[k]


# Module-level singleton
cache = ResponseCache()
