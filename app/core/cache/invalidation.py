"""
Get-or-compute caching with cross-instance invalidation.

Built entirely on the existing RedisAdapter (Redis or local backend — the
API is identical either way):

    from app.core.cache.invalidation import cached, invalidate

    settings = await cached(f"org:settings:{org_id}", load_fn, ttl=300)
    ...
    await invalidate(f"org:settings:{org_id}")   # after a write

Invalidation does two things: deletes the cache key, and publishes the key
on one shared pub/sub channel. Every instance subscribes to that channel
(lazily, on first use) and runs any callbacks registered for the key's
prefix — this is how purely in-process caches that predate this module
(TenancyService._perm_cache, PlanService._cache) get refreshed on OTHER
instances when one instance writes. On a single instance with the local
backend, publish dispatches in-process, so behavior is identical — just
with the invalidation made explicit.
"""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from app.core.cache.redis_adapter import get_redis

log = logging.getLogger(__name__)

_CHANNEL = "cache-invalidate"

# prefix → [callbacks]; each callback receives the full invalidated key.
_listeners: dict[str, list[Callable[[str], Any]]] = {}
_subscribed = False


async def _ensure_subscribed() -> None:
    global _subscribed
    if _subscribed:
        return
    r = await get_redis()
    await r.subscribe(_CHANNEL, _dispatch)
    _subscribed = True


async def _dispatch(key: str) -> None:
    for prefix, callbacks in _listeners.items():
        if not key.startswith(prefix):
            continue
        for cb in callbacks:
            try:
                result = cb(key)
                if hasattr(result, "__await__"):
                    await result
            except Exception:
                log.exception("invalidation callback failed for %s", key)


async def on_invalidate(prefix: str, callback: Callable[[str], Any]) -> None:
    """Run `callback(key)` on this instance whenever any instance
    invalidates a key starting with `prefix`."""
    _listeners.setdefault(prefix, []).append(callback)
    await _ensure_subscribed()


async def cached(
    key: str,
    compute: Callable[[], Awaitable[Any]],
    *,
    ttl: int = 300,
) -> Any:
    """Get-or-compute: JSON-serializable values only (the hot reads this is
    applied to — org settings, marketplace listings — are already dicts)."""
    r = await get_redis()
    hit = await r.get_json(key)
    if hit is not None:
        return hit
    value = await compute()
    if value is not None:
        try:
            await r.set_json(key, value, ttl=ttl)
        except (TypeError, ValueError):
            log.warning("cached(%s): value not JSON-serializable, not cached", key)
    return value


async def invalidate(key: str) -> None:
    r = await get_redis()
    await r.delete(key)
    await r.publish(_CHANNEL, key)


async def invalidate_prefix(prefix: str) -> None:
    """Delete every cache key under `prefix` and broadcast the prefix so
    other instances drop theirs too."""
    r = await get_redis()
    await r.delete_prefix(prefix)
    await r.publish(_CHANNEL, prefix)
