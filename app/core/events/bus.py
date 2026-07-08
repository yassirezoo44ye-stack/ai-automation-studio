"""
EventBus — platform-wide event-driven backbone.

Backends:
  1. Redis Streams (REDIS_URL set) — durable, replayable, consumer groups,
     failed handler deliveries land in a dead-letter stream.
  2. In-process — same API, ring-buffer history for replay; used in dev/tests.

Canonical event types are declared in EVENT_TYPES; publishing an undeclared
type raises immediately so topic typos never ship.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Awaitable, Callable, Optional

log = logging.getLogger(__name__)

EVENT_TYPES = frozenset({
    "workflow.started", "workflow.completed", "workflow.failed",
    "agent.started", "agent.finished",
    "billing.updated",
    "marketplace.installed", "marketplace.published",
    "deployment.completed",
    "memory.created",
    "organization.created", "organization.member_added",
    "job.completed", "job.failed",
})

Handler = Callable[["Event"], Awaitable[None]]

_STREAM = "axon:events"
_DLQ    = "axon:events:dlq"
_MAXLEN = 10_000


@dataclass
class Event:
    type: str
    data: dict[str, Any] = field(default_factory=dict)
    organization_id: str | None = None
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Event":
        return cls(
            type=d["type"], data=d.get("data", {}),
            organization_id=d.get("organization_id"),
            id=d.get("id", uuid.uuid4().hex), ts=float(d.get("ts", time.time())),
        )


class EventBus:
    """Publish/subscribe with wildcard prefixes ('workflow.*' or '*')."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = {}
        self._history: list[Event] = []          # in-process replay buffer
        self._dlq: list[dict[str, Any]] = []     # in-process dead letters
        self._redis = None                       # redis.asyncio client when active
        self.backend = "memory"

    # ── Setup ─────────────────────────────────────────────────────────────────

    async def connect(self) -> None:
        """Try Redis Streams; stay in-process silently when unavailable."""
        import os
        url = os.getenv("REDIS_URL", "")
        if not url:
            return
        try:
            import redis.asyncio as aioredis
            client = aioredis.from_url(url, decode_responses=True)
            await client.ping()
            self._redis = client
            self.backend = "redis_streams"
            log.info("event bus: Redis Streams backend active")
        except Exception as exc:
            log.warning("event bus: redis unavailable (%s), using in-process", exc)

    # ── Publish ───────────────────────────────────────────────────────────────

    async def publish(self, type_: str, data: dict[str, Any] | None = None, *,
                      organization_id: str | None = None) -> Event:
        if type_ not in EVENT_TYPES:
            raise ValueError(f"undeclared event type {type_!r} — add it to EVENT_TYPES")
        event = Event(type=type_, data=data or {}, organization_id=organization_id)

        if self._redis is not None:
            try:
                await self._redis.xadd(
                    _STREAM, {"payload": json.dumps(event.to_dict())},
                    maxlen=_MAXLEN, approximate=True,
                )
            except Exception as exc:
                log.warning("event bus: xadd failed (%s)", exc)

        self._history.append(event)
        if len(self._history) > _MAXLEN:
            self._history = self._history[-_MAXLEN // 2:]

        await self._dispatch(event)
        return event

    async def _dispatch(self, event: Event) -> None:
        for pattern, handlers in self._handlers.items():
            if not _matches(pattern, event.type):
                continue
            for h in handlers:
                try:
                    await h(event)
                except Exception as exc:
                    log.error("event handler %s failed for %s: %s",
                              getattr(h, "__name__", h), event.type, exc)
                    entry = {"event": event.to_dict(), "handler": getattr(h, "__name__", str(h)),
                             "error": str(exc), "ts": time.time()}
                    self._dlq.append(entry)
                    if self._redis is not None:
                        try:
                            await self._redis.xadd(_DLQ, {"payload": json.dumps(entry)},
                                                   maxlen=1000, approximate=True)
                        except Exception:
                            pass

    # ── Subscribe ─────────────────────────────────────────────────────────────

    def subscribe(self, pattern: str, handler: Handler) -> None:
        """pattern: exact type, 'prefix.*', or '*' for everything."""
        self._handlers.setdefault(pattern, []).append(handler)

    def unsubscribe(self, pattern: str, handler: Handler) -> None:
        if pattern in self._handlers:
            self._handlers[pattern] = [h for h in self._handlers[pattern] if h is not handler]

    # ── Replay / introspection ────────────────────────────────────────────────

    async def replay(self, *, since_ts: float = 0.0, type_prefix: str = "",
                     limit: int = 100) -> list[Event]:
        """Return historical events (Redis stream when active, ring buffer otherwise)."""
        if self._redis is not None:
            try:
                entries = await self._redis.xrange(_STREAM, count=min(limit * 5, 5000))
                events = [Event.from_dict(json.loads(v["payload"])) for _, v in entries]
            except Exception:
                events = list(self._history)
        else:
            events = list(self._history)
        out = [
            e for e in events
            if e.ts >= since_ts and (not type_prefix or e.type.startswith(type_prefix))
        ]
        return out[-limit:]

    def dead_letters(self, limit: int = 50) -> list[dict[str, Any]]:
        return self._dlq[-limit:][::-1]

    def stats(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "subscriptions": {p: len(hs) for p, hs in self._handlers.items()},
            "history_size": len(self._history),
            "dead_letters": len(self._dlq),
        }


def _matches(pattern: str, event_type: str) -> bool:
    if pattern == "*":
        return True
    if pattern.endswith(".*"):
        return event_type.startswith(pattern[:-1])
    return pattern == event_type


# ── Singleton wiring ──────────────────────────────────────────────────────────

_bus: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    global _bus
    if _bus is None:
        _bus = EventBus()
    return _bus
