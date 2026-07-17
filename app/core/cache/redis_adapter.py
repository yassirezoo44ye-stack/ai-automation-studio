"""
Unified cache / Redis adapter.

Priority order:
  1. Redis (REDIS_URL env var)               — shared across all instances
  2. In-process TTL dict                     — single-process fallback (no dep)

All public methods are async and have identical signatures regardless of backend.
Callers never know which backend is active.

Usage:
    redis = await get_redis()
    await redis.set("key", "value", ttl=300)
    val = await redis.get("key")            # None if missing / expired
    await redis.delete("key")
    await redis.incr("counter")             # atomic increment
    keys = await redis.keys("prefix:*")
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from abc import ABC, abstractmethod
from typing import Any, Optional

log = logging.getLogger(__name__)

# ── Abstract backend ──────────────────────────────────────────────────────────

class CacheBackend(ABC):
    @abstractmethod
    async def get(self, key: str) -> Optional[str]: ...

    @abstractmethod
    async def set(self, key: str, value: str, ttl: Optional[int] = None) -> None: ...

    @abstractmethod
    async def delete(self, key: str) -> None: ...

    @abstractmethod
    async def incr(self, key: str) -> int: ...

    @abstractmethod
    async def expire(self, key: str, ttl: int) -> None: ...

    @abstractmethod
    async def keys(self, pattern: str) -> list[str]: ...

    @abstractmethod
    async def mget(self, *keys: str) -> list[Optional[str]]: ...

    @abstractmethod
    async def hset(self, name: str, mapping: dict) -> None: ...

    @abstractmethod
    async def hget(self, name: str, field: str) -> Optional[str]: ...

    @abstractmethod
    async def hgetall(self, name: str) -> dict[str, str]: ...

    @abstractmethod
    async def lpush(self, key: str, *values: str) -> None: ...

    @abstractmethod
    async def lrange(self, key: str, start: int, end: int) -> list[str]: ...

    @abstractmethod
    async def publish(self, channel: str, message: str) -> None: ...

    @abstractmethod
    async def subscribe(self, channel: str, callback) -> None: ...

    @property
    @abstractmethod
    def backend_name(self) -> str: ...


# ── In-process fallback ───────────────────────────────────────────────────────

class _Entry:
    __slots__ = ("value", "expires_at")

    def __init__(self, value: str, ttl: Optional[int]) -> None:
        self.value      = value
        self.expires_at = (time.monotonic() + ttl) if ttl else None

    def is_alive(self) -> bool:
        return self.expires_at is None or time.monotonic() < self.expires_at


class LocalCacheBackend(CacheBackend):
    """Thread-safe in-memory backend. No external dependencies."""

    def __init__(self) -> None:
        self._store  : dict[str, _Entry]       = {}
        self._hashes : dict[str, dict[str, str]] = {}
        self._lists  : dict[str, list[str]]    = {}
        self._counters: dict[str, int]         = {}
        self._pubsub : dict[str, list]         = {}   # channel → [callbacks]

    def _get_raw(self, key: str) -> Optional[_Entry]:
        e = self._store.get(key)
        if e and not e.is_alive():
            del self._store[key]
            return None
        return e

    async def get(self, key: str) -> Optional[str]:
        e = self._get_raw(key)
        return e.value if e else None

    async def set(self, key: str, value: str, ttl: Optional[int] = None) -> None:
        self._store[key] = _Entry(str(value), ttl)

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)
        self._hashes.pop(key, None)
        self._lists.pop(key, None)
        self._counters.pop(key, None)

    async def incr(self, key: str) -> int:
        self._counters[key] = self._counters.get(key, 0) + 1
        return self._counters[key]

    async def expire(self, key: str, ttl: int) -> None:
        e = self._get_raw(key)
        if e:
            e.expires_at = time.monotonic() + ttl

    async def keys(self, pattern: str) -> list[str]:
        import fnmatch
        return [k for k in self._store if fnmatch.fnmatch(k, pattern)
                and self._get_raw(k) is not None]

    async def mget(self, *keys: str) -> list[Optional[str]]:
        return [await self.get(k) for k in keys]

    async def hset(self, name: str, mapping: dict) -> None:
        if name not in self._hashes:
            self._hashes[name] = {}
        self._hashes[name].update({str(k): str(v) for k, v in mapping.items()})

    async def hget(self, name: str, field: str) -> Optional[str]:
        return self._hashes.get(name, {}).get(field)

    async def hgetall(self, name: str) -> dict[str, str]:
        return dict(self._hashes.get(name, {}))

    async def lpush(self, key: str, *values: str) -> None:
        if key not in self._lists:
            self._lists[key] = []
        for v in reversed(values):
            self._lists[key].insert(0, str(v))

    async def lrange(self, key: str, start: int, end: int) -> list[str]:
        lst = self._lists.get(key, [])
        return lst[start : end + 1 if end >= 0 else None]

    async def publish(self, channel: str, message: str) -> None:
        for cb in self._pubsub.get(channel, []):
            try:
                if asyncio.iscoroutinefunction(cb):
                    asyncio.create_task(cb(message))
                else:
                    cb(message)
            except Exception:
                pass

    async def subscribe(self, channel: str, callback) -> None:
        self._pubsub.setdefault(channel, []).append(callback)

    @property
    def backend_name(self) -> str:
        return "local"


# ── Redis backend ─────────────────────────────────────────────────────────────

class RedisCacheBackend(CacheBackend):
    """
    Thin async wrapper around redis.asyncio.
    Requires REDIS_URL env var and `redis` package installed.
    """

    def __init__(self, client) -> None:
        self._r = client
        self._subs: dict[str, list] = {}       # channel → [callbacks]
        self._pubsub_conn = None               # created lazily on first subscribe
        self._listener_task: Optional[asyncio.Task] = None

    async def get(self, key: str) -> Optional[str]:
        val = await self._r.get(key)
        return val.decode() if isinstance(val, bytes) else val

    async def set(self, key: str, value: str, ttl: Optional[int] = None) -> None:
        if ttl:
            await self._r.setex(key, ttl, value)
        else:
            await self._r.set(key, value)

    async def delete(self, key: str) -> None:
        await self._r.delete(key)

    async def incr(self, key: str) -> int:
        return await self._r.incr(key)

    async def expire(self, key: str, ttl: int) -> None:
        await self._r.expire(key, ttl)

    async def keys(self, pattern: str) -> list[str]:
        raw = await self._r.keys(pattern)
        return [k.decode() if isinstance(k, bytes) else k for k in raw]

    async def mget(self, *keys: str) -> list[Optional[str]]:
        vals = await self._r.mget(*keys)
        return [v.decode() if isinstance(v, bytes) else v for v in vals]

    async def hset(self, name: str, mapping: dict) -> None:
        await self._r.hset(name, mapping=mapping)

    async def hget(self, name: str, field: str) -> Optional[str]:
        val = await self._r.hget(name, field)
        return val.decode() if isinstance(val, bytes) else val

    async def hgetall(self, name: str) -> dict[str, str]:
        raw = await self._r.hgetall(name)
        return {
            (k.decode() if isinstance(k, bytes) else k):
            (v.decode() if isinstance(v, bytes) else v)
            for k, v in raw.items()
        }

    async def lpush(self, key: str, *values: str) -> None:
        await self._r.lpush(key, *values)

    async def lrange(self, key: str, start: int, end: int) -> list[str]:
        raw = await self._r.lrange(key, start, end)
        return [v.decode() if isinstance(v, bytes) else v for v in raw]

    async def publish(self, channel: str, message: str) -> None:
        await self._r.publish(channel, message)

    async def subscribe(self, channel: str, callback) -> None:
        self._subs.setdefault(channel, []).append(callback)
        if self._pubsub_conn is None:
            self._pubsub_conn = self._r.pubsub()
        await self._pubsub_conn.subscribe(channel)
        if self._listener_task is None or self._listener_task.done():
            self._listener_task = asyncio.create_task(self._listen())

    async def _listen(self) -> None:
        try:
            async for msg in self._pubsub_conn.listen():
                if msg.get("type") != "message":
                    continue
                ch = msg["channel"]
                ch = ch.decode() if isinstance(ch, bytes) else ch
                data = msg["data"]
                data = data.decode() if isinstance(data, bytes) else str(data)
                for cb in self._subs.get(ch, []):
                    try:
                        if asyncio.iscoroutinefunction(cb):
                            asyncio.create_task(cb(data))
                        else:
                            cb(data)
                    except Exception:
                        log.exception("pubsub callback failed for channel %s", ch)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Listener death must never take the app down — log and stop;
            # the next subscribe() call restarts it.
            log.warning("pubsub listener stopped: %s", exc)
            self._listener_task = None

    @property
    def backend_name(self) -> str:
        return "redis"


# ── Public adapter ────────────────────────────────────────────────────────────

class RedisAdapter:
    """
    Namespace-aware cache adapter.
    Prepends `{namespace}:` to every key automatically.
    Delegates to whichever backend was resolved at init time.
    """

    def __init__(self, backend: CacheBackend, namespace: str = "axon") -> None:
        self._b  = backend
        self._ns = namespace

    def _k(self, key: str) -> str:
        return f"{self._ns}:{key}"

    async def get(self, key: str) -> Optional[str]:
        return await self._b.get(self._k(key))

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        await self._b.set(self._k(key), str(value), ttl=ttl)

    async def delete(self, key: str) -> None:
        await self._b.delete(self._k(key))

    async def delete_prefix(self, prefix: str) -> int:
        """Delete every key under `prefix` (namespaced). Returns the count."""
        keys = await self._b.keys(self._k(prefix) + "*")
        for k in keys:
            await self._b.delete(k)
        return len(keys)

    async def incr(self, key: str, ttl: Optional[int] = None) -> int:
        n = await self._b.incr(self._k(key))
        if ttl and n == 1:          # set TTL on first increment only
            await self._b.expire(self._k(key), ttl)
        return n

    async def get_int(self, key: str, default: int = 0) -> int:
        val = await self.get(key)
        return int(val) if val is not None else default

    async def mget(self, *keys: str) -> list[Optional[str]]:
        return await self._b.mget(*[self._k(k) for k in keys])

    async def hset(self, name: str, mapping: dict) -> None:
        await self._b.hset(self._k(name), mapping)

    async def hget(self, name: str, field: str) -> Optional[str]:
        return await self._b.hget(self._k(name), field)

    async def hgetall(self, name: str) -> dict[str, str]:
        return await self._b.hgetall(self._k(name))

    async def lpush(self, key: str, *values: str) -> None:
        await self._b.lpush(self._k(key), *values)

    async def lrange(self, key: str, start: int = 0, end: int = -1) -> list[str]:
        return await self._b.lrange(self._k(key), start, end)

    async def publish(self, channel: str, message: str) -> None:
        await self._b.publish(f"{self._ns}:{channel}", message)

    async def subscribe(self, channel: str, callback) -> None:
        """Register a callback for messages on `channel` (namespaced the same
        way publish() namespaces, so publish/subscribe pairs line up). Works
        on both backends: Redis uses a real pub/sub listener; local dispatches
        in-process — which makes cross-instance invalidation a no-op extra
        hop on single-instance deployments, not a behavior change."""
        await self._b.subscribe(f"{self._ns}:{channel}", callback)

    @property
    def backend(self) -> str:
        return self._b.backend_name

    # ── Convenience helpers ───────────────────────────────────────────────────

    async def get_json(self, key: str) -> Optional[Any]:
        import json
        val = await self.get(key)
        if val is None:
            return None
        try:
            return json.loads(val)
        except Exception:
            return val

    async def set_json(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        import json
        await self.set(key, json.dumps(value), ttl=ttl)


# ── Singleton factory ─────────────────────────────────────────────────────────

_instance: Optional[RedisAdapter] = None


async def get_redis(namespace: str = "axon") -> RedisAdapter:
    global _instance
    if _instance is not None:
        return _instance

    redis_url = os.getenv("REDIS_URL", "")
    if redis_url:
        try:
            import redis.asyncio as aioredis
            client  = aioredis.from_url(redis_url, decode_responses=False)
            await client.ping()
            _instance = RedisAdapter(RedisCacheBackend(client), namespace)
            log.info("cache: Redis backend connected (%s)", redis_url.split("@")[-1])
        except Exception as exc:
            log.warning("cache: Redis unavailable (%s) — using local backend", exc)
            _instance = RedisAdapter(LocalCacheBackend(), namespace)
    else:
        log.info("cache: REDIS_URL not set — using local in-process backend")
        _instance = RedisAdapter(LocalCacheBackend(), namespace)

    return _instance
