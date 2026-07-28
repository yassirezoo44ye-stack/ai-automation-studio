"""
PresenceService — heartbeat-based online/offline tracking with pub/sub
fan-out, layered on the existing notifications WS channel
(app/routers/ws.py's `/ws/notifications`) rather than a new socket.

Model (matches the standard heartbeat-presence pattern): the client sends a
lightweight `{"type": "ping"}` frame every ~15s over its already-open
notifications socket; each ping refreshes a short-TTL Redis key
(`presence:{user_id}`, PRESENCE_TTL_SECONDS). A user is "online" exactly
while that key exists. Going offline is detected two ways:
  1. Fast path — the socket's `finally` block calls mark_offline() the
     moment a user's last open connection closes cleanly.
  2. Slow path — for a hard disconnect (crash, network cut, laptop closed)
     nothing fires proactively; the key simply expires and the next read
     (bulk_status/is_online) reports offline. No background sweep task is
     needed to satisfy "server-side offline-after-timeout detection" — the
     TTL *is* the timeout, and eventual-consistency here is the same
     trade-off Slack/Discord-style presence makes.

Fan-out: a status *transition* (not every heartbeat) is published on a
Redis pub/sub channel so every app instance — not just the one the user
happens to be connected to — can push the change to that user's org-mates.
wire_fanout() subscribes once per process and rebroadcasts locally via the
existing `_ConnectionManager`, onto topic `presence:{user_id}` for each
org-mate — the same in-process broadcast primitive the notification
dispatcher already uses for `notifications:{user_id}`.
"""
from __future__ import annotations

import json
import logging
import time

from app.core.cache.redis_adapter import get_redis

log = logging.getLogger(__name__)

PRESENCE_TTL_SECONDS = 45
PRESENCE_CHANNEL = "presence:changes"


class PresenceService:
    def __init__(self) -> None:
        self._fanout_wired = False

    async def touch(self, user_id: str) -> bool:
        """Refresh a user's online TTL (call on connect + every heartbeat
        ping). Returns True if this was an offline -> online transition."""
        redis = await get_redis()
        was_online = (await redis.get(f"presence:{user_id}")) is not None
        await redis.set(f"presence:{user_id}", str(time.time()), ttl=PRESENCE_TTL_SECONDS)
        if not was_online:
            await self._publish_change(user_id, online=True)
        return not was_online

    async def mark_offline(self, user_id: str) -> None:
        redis = await get_redis()
        existed = (await redis.get(f"presence:{user_id}")) is not None
        await redis.delete(f"presence:{user_id}")
        if existed:
            await self._publish_change(user_id, online=False)

    async def is_online(self, user_id: str) -> bool:
        redis = await get_redis()
        return (await redis.get(f"presence:{user_id}")) is not None

    async def bulk_status(self, user_ids: list[str]) -> dict[str, bool]:
        if not user_ids:
            return {}
        redis = await get_redis()
        vals = await redis.mget(*[f"presence:{uid}" for uid in user_ids])
        return {uid: (val is not None) for uid, val in zip(user_ids, vals)}

    async def _publish_change(self, user_id: str, *, online: bool) -> None:
        redis = await get_redis()
        payload = json.dumps({"user_id": user_id, "online": online, "ts": time.time()})
        await redis.publish(PRESENCE_CHANNEL, payload)

    async def wire_fanout(self) -> None:
        """Subscribe once per process to presence changes and rebroadcast
        each one to the affected user's org-mates over their already-open
        notifications socket. Idempotent — safe to call from factory setup
        on every worker."""
        if self._fanout_wired:
            return
        self._fanout_wired = True

        redis = await get_redis()

        async def _on_change(raw: str) -> None:
            try:
                data = json.loads(raw)
                user_id = data["user_id"]
                online = bool(data["online"])
            except Exception:
                return
            try:
                await self._fanout_to_org_mates(user_id, online)
            except Exception:
                log.warning("presence fan-out failed for user %s", user_id, exc_info=True)

        await redis.subscribe(PRESENCE_CHANNEL, _on_change)
        log.info("presence: pub/sub fan-out wired")

    async def _fanout_to_org_mates(self, user_id: str, online: bool) -> None:
        from app.core.notifications.service import get_notification_service
        from app.routers.ws import manager as ws_manager

        svc = get_notification_service()
        org_ids = await svc.org_ids_for_user(user_id=user_id)
        mate_ids: set[str] = set()
        for org_id in org_ids:
            mate_ids.update(await svc.org_member_ids(organization_id=org_id))
        mate_ids.discard(user_id)

        frame = {"user_id": user_id, "online": online}
        for mate_id in mate_ids:
            await ws_manager.broadcast(f"presence:{mate_id}", frame)


_presence_service: PresenceService | None = None


def get_presence_service() -> PresenceService:
    global _presence_service
    if _presence_service is None:
        _presence_service = PresenceService()
    return _presence_service


async def wire_presence_fanout() -> None:
    await get_presence_service().wire_fanout()
