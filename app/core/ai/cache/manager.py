"""
CacheManager — extends the base ResponseCache with:
- Model list caching (TTL: 1 hour)
- Provider health caching (TTL: 5 minutes)
- Tool schema caching (TTL: indefinite until invalidated)
- Prompt version caching (TTL: 5 minutes)

The response cache for AI completions remains in app.ai.cache (unchanged).
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Optional


class _TTLStore:
    """Simple TTL key-value store."""

    def __init__(self) -> None:
        self._data: dict[str, tuple[Any, float]] = {}  # key → (value, expires_at)

    def get(self, key: str) -> Optional[Any]:
        entry = self._data.get(key)
        if not entry:
            return None
        value, exp = entry
        if time.monotonic() > exp:
            del self._data[key]
            return None
        return value

    def set(self, key: str, value: Any, ttl: int) -> None:
        self._data[key] = (value, time.monotonic() + ttl)

    def delete(self, key: str) -> None:
        self._data.pop(key, None)

    def clear_prefix(self, prefix: str) -> int:
        keys = [k for k in self._data if k.startswith(prefix)]
        for k in keys:
            del self._data[k]
        return len(keys)

    def stats(self) -> dict:
        now  = time.monotonic()
        live = sum(1 for _, exp in self._data.values() if exp > now)
        return {"total": len(self._data), "live": live}


class CacheManager:
    """
    Platform-level cache for non-completion data.

    All TTLs are in seconds.
    """

    _MODEL_LIST_TTL    = 3_600   # 1 hour
    _HEALTH_TTL        = 300     # 5 minutes
    _TOOL_SCHEMA_TTL   = 0       # indefinite (manual invalidation)
    _PROMPT_TTL        = 300     # 5 minutes

    def __init__(self) -> None:
        self._store = _TTLStore()

    # ── Model list ────────────────────────────────────────────────────────────

    def get_model_list(self, provider_id: str) -> Optional[list]:
        return self._store.get(f"models:{provider_id}")

    def set_model_list(self, provider_id: str, models: list) -> None:
        self._store.set(f"models:{provider_id}", models, self._MODEL_LIST_TTL)

    # ── Provider health ───────────────────────────────────────────────────────

    def get_health(self) -> Optional[dict]:
        return self._store.get("health")

    def set_health(self, health: dict) -> None:
        self._store.set("health", health, self._HEALTH_TTL)

    # ── Tool schemas ──────────────────────────────────────────────────────────

    def get_tool_schemas(self) -> Optional[list]:
        return self._store.get("tool_schemas")

    def set_tool_schemas(self, schemas: list) -> None:
        # Infinite TTL — invalidate manually when tools are registered
        self._store.set("tool_schemas", schemas, 86_400)

    def invalidate_tools(self) -> None:
        self._store.delete("tool_schemas")

    # ── Prompt versions ───────────────────────────────────────────────────────

    def get_prompt(self, prompt_id: str) -> Optional[Any]:
        return self._store.get(f"prompt:{prompt_id}")

    def set_prompt(self, prompt_id: str, version) -> None:
        self._store.set(f"prompt:{prompt_id}", version, self._PROMPT_TTL)

    def invalidate_prompt(self, prompt_id: str) -> None:
        self._store.delete(f"prompt:{prompt_id}")

    # ── Generic ───────────────────────────────────────────────────────────────

    def get(self, key: str) -> Optional[Any]:
        return self._store.get(key)

    def set(self, key: str, value: Any, ttl: int) -> None:
        self._store.set(key, value, ttl)

    def stats(self) -> dict:
        return self._store.stats()

    # ── Key helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def make_key(*parts: str) -> str:
        raw = ":".join(parts)
        return hashlib.md5(raw.encode()).hexdigest()


# Module-level singleton
cache_manager = CacheManager()
