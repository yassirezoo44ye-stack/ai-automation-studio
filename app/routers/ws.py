"""
WebSocket real-time channel — Layer 16 surface.

Endpoints:
  WS /ws/agent/{session_id}       live agent output stream
  WS /ws/job/{job_id}             background job progress stream
  WS /ws/system                   system-wide broadcast (admin)
  WS /ws/system/{run_id}          one AgentOS run's live step narration
  WS /ws/notifications            per-user notification stream (auth required)

Protocol (JSON frames):
  → client sends:   {"type": "ping"}  |  {"type": "subscribe", "topic": "..."}
  ← server sends:   {"type": "pong"}  |  {"type": "event", "topic": "...", "data": {...}}
                    {"type": "error", "message": "..."}
                    {"type": "closed", "reason": "..."}

Reconnection: clients should reconnect with exponential backoff.
The server sends {"type": "ping"} every 30 s; clients may echo {"type": "pong"}.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

log = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])

# ── Connection manager ────────────────────────────────────────────────────────

class _ConnectionManager:
    def __init__(self) -> None:
        # topic → list of active websockets
        self._subs: dict[str, list[WebSocket]] = {}

    async def connect(self, ws: WebSocket, topic: str) -> None:
        # A socket already connected to one topic (e.g. notifications_ws
        # additionally subscribing itself to presence:{user_id}) must not be
        # accepted twice — a second accept() on an already-CONNECTED socket
        # is an invalid ASGI state transition and raises.
        if ws.application_state == WebSocketState.CONNECTING:
            await ws.accept()
        self._subs.setdefault(topic, []).append(ws)
        log.debug("ws connected topic=%s total=%d", topic, len(self._subs[topic]))

    def disconnect(self, ws: WebSocket, topic: str) -> None:
        subs = self._subs.get(topic, [])
        if ws in subs:
            subs.remove(ws)
        log.debug("ws disconnected topic=%s remaining=%d", topic, len(subs))

    async def broadcast(self, topic: str, payload: dict) -> None:
        """Send to all subscribers of a topic in parallel — a sequential
        loop lets one slow client's TCP backpressure delay every later
        subscriber (head-of-line blocking). Dead connections are pruned."""
        subs  = list(self._subs.get(topic, []))
        if not subs:
            return
        frame = json.dumps({"type": "event", "topic": topic,
                            "data": payload, "ts": round(time.time(), 3)})
        results = await asyncio.gather(
            *(ws.send_text(frame) for ws in subs), return_exceptions=True,
        )
        for ws, result in zip(subs, results):
            if isinstance(result, BaseException):
                self.disconnect(ws, topic)

    async def send(self, ws: WebSocket, payload: dict) -> bool:
        try:
            await ws.send_text(json.dumps(payload))
            return True
        except Exception:
            return False

    def subscriber_count(self, topic: str) -> int:
        return len(self._subs.get(topic, []))

    def all_topics(self) -> list[str]:
        return [t for t, subs in self._subs.items() if subs]


manager = _ConnectionManager()


def get_ws_manager() -> _ConnectionManager:
    return manager


# ── Heartbeat helper ──────────────────────────────────────────────────────────

async def _heartbeat(ws: WebSocket, interval: float = 30.0) -> None:
    """Send periodic pings so clients can detect stale connections."""
    while True:
        await asyncio.sleep(interval)
        ok = await manager.send(ws, {"type": "ping", "ts": round(time.time(), 3)})
        if not ok:
            break


# ── Agent output stream ───────────────────────────────────────────────────────

@router.websocket("/ws/agent/{session_id}")
async def agent_ws(ws: WebSocket, session_id: str):
    """
    Bidirectional channel for a live agent session.
    The agent publishes events to topic `agent:{session_id}`.
    Clients may send {"type": "cancel"} to abort the session.

    SECURITY FIX: this was the only one of the 5 WS endpoints in this file
    with no token check at all, AND its "subscribe" handler forwarded any
    client-supplied topic string verbatim to manager.connect() with zero
    validation — together, an unauthenticated connection could subscribe
    itself to any other topic in the app (another user's chat room,
    notifications, presence, or a live AgentOS run's step narration, which
    carries real prompt/search/URL content) just by knowing or guessing
    its name, bypassing every other endpoint's per-topic authorization
    entirely. Now gated the same way as every sibling endpoint here, and
    "subscribe" is restricted to this session's own sub-topics (the only
    pattern this file itself ever publishes, e.g. "{topic}:control").
    There is no per-session ownership registry for `session_id` today
    (unlike /ws/system/{run_id}'s run-owner check) — any authenticated
    user can still connect to any session_id, matching /ws/system's
    existing "any authenticated user" model; closing that gap fully would
    need a new ownership registry, out of scope for this minimal fix.
    Confirmed unused by the current frontend (no caller of /ws/agent/ or
    the "subscribe" message exists in src/renderer), so tightening this
    carries no regression risk to an active feature.
    """
    token   = ws.query_params.get("token", "")
    user_id = _user_id_from_ws_token(token)
    if not user_id:
        await ws.close(code=4401, reason="unauthorized")
        return

    topic = f"agent:{session_id}"
    subscribed = [topic]
    await manager.connect(ws, topic)
    hb    = asyncio.create_task(_heartbeat(ws))

    try:
        await manager.send(ws, {
            "type"      : "connected",
            "session_id": session_id,
            "topic"     : topic,
        })

        while True:
            try:
                raw  = await asyncio.wait_for(ws.receive_text(), timeout=120)
                msg  = json.loads(raw)
                kind = msg.get("type", "")

                if kind == "ping":
                    await manager.send(ws, {"type": "pong"})

                elif kind == "cancel":
                    # Signal the agent runner to abort
                    await manager.broadcast(f"{topic}:control", {"action": "cancel"})
                    await manager.send(ws, {"type": "ack", "action": "cancel"})

                elif kind == "subscribe":
                    extra = msg.get("topic", "")
                    # Only this session's own sub-topics — never an
                    # arbitrary caller-supplied topic (see docstring).
                    if extra and extra.startswith(f"{topic}:"):
                        await manager.connect(ws, extra)
                        subscribed.append(extra)
                        await manager.send(ws, {"type": "subscribed", "topic": extra})
                    else:
                        await manager.send(ws, {"type": "error", "message": "topic not permitted"})

            except asyncio.TimeoutError:
                # No message for 2 minutes — send keep-alive
                await manager.send(ws, {"type": "ping"})

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        log.warning("agent ws error session=%s: %s", session_id, exc)
        await manager.send(ws, {"type": "error", "message": str(exc)})
    finally:
        hb.cancel()
        for t in subscribed:
            manager.disconnect(ws, t)


# ── Job progress stream ───────────────────────────────────────────────────────

@router.websocket("/ws/job/{job_id}")
async def job_ws(ws: WebSocket, job_id: str):
    """
    Subscribe to background job progress.
    Server streams {"type": "progress", "pct": 0-100, "log": "..."} frames.
    Connection closes when job reaches a terminal state.
    """
    topic = f"job:{job_id}"
    await manager.connect(ws, topic)
    hb    = asyncio.create_task(_heartbeat(ws))

    try:
        # Send current snapshot
        from app.core.jobs import get_job_queue
        job = await get_job_queue().get(job_id)
        if not job:
            await manager.send(ws, {"type": "error", "message": f"Job {job_id!r} not found"})
            return

        await manager.send(ws, {
            "type"   : "snapshot",
            "job"    : job.to_dict(),
        })

        # If already terminal, close immediately
        if job.status.value in ("completed", "failed", "cancelled"):
            await manager.send(ws, {"type": "closed", "reason": f"job {job.status.value}"})
            return

        # Poll until terminal (replace with pub/sub subscription in prod)
        while True:
            await asyncio.sleep(0.5)
            job = await get_job_queue().get(job_id)
            if not job:
                break
            await manager.send(ws, {
                "type"    : "progress",
                "status"  : job.status.value,
                "progress": job.progress,
                "log"     : job.log_lines[-1] if job.log_lines else "",
            })
            if job.status.value in ("completed", "failed", "cancelled"):
                await manager.send(ws, {
                    "type"  : "closed",
                    "reason": job.status.value,
                    "result": job.result,
                    "error" : job.error,
                })
                break

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        log.warning("job ws error job_id=%s: %s", job_id, exc)
    finally:
        hb.cancel()
        manager.disconnect(ws, topic)


# ── System broadcast (authenticated) ────────────────────────────────────────

@router.websocket("/ws/system")
async def system_ws(ws: WebSocket):
    """System-wide broadcast channel — currently carries AgentOS agent
    liveness (see app/agents/liveness.py's "agent.started"/"agent.finished"
    bridge; frame shape {"agent": name, "status": "running"|"idle", ...}).
    Any authenticated user may connect: agent names/timings aren't
    per-tenant secret, but the channel still requires a valid session so
    it isn't wide open to anyone on the internet, matching every other
    WS endpoint here that carries live operational data."""
    token   = ws.query_params.get("token", "")
    user_id = _user_id_from_ws_token(token)
    if not user_id:
        await ws.close(code=4401, reason="unauthorized")
        return

    topic = "system"
    await manager.connect(ws, topic)
    hb    = asyncio.create_task(_heartbeat(ws))

    try:
        await manager.send(ws, {"type": "connected", "topic": "system"})
        while True:
            try:
                raw = await asyncio.wait_for(ws.receive_text(), timeout=300)
                msg = json.loads(raw)
                if msg.get("type") == "ping":
                    await manager.send(ws, {"type": "pong"})
            except asyncio.TimeoutError:
                await manager.send(ws, {"type": "ping"})
    except WebSocketDisconnect:
        pass
    finally:
        hb.cancel()
        manager.disconnect(ws, topic)


@router.websocket("/ws/system/{run_id}")
async def system_run_ws(ws: WebSocket, run_id: str):
    """Narrated step stream for one AgentOS run (see
    app/agents/liveness.py's publish_step). Deliberately a *separate*
    topic per run_id (`system:{run_id}`) rather than the shared "system"
    topic every connection on that endpoint receives — step payloads can
    carry the run's actual input, search queries, and URLs, so fan-out
    is scoped at the topic/subscription level, not by filtering messages
    client-side after they've already been sent to every connection.

    Authorization is two-layered, same principle as deliverable downloads
    (app/routers/agent_os_api.py): knowing an unguessable run_id is not
    on its own treated as proof you're allowed to watch it. AgentKernel.run()
    records the verified caller (if any) who started each run_id
    (app/agents/liveness.py's register_run_owner); this endpoint checks
    the connecting user against that record and rejects a mismatch. A
    run_id with no owner on record — not yet started, or started by an
    unauthenticated caller — falls back to any authenticated user, same
    as deliverables' "no owner recorded" case."""
    token   = ws.query_params.get("token", "")
    user_id = _user_id_from_ws_token(token)
    if not user_id:
        await ws.close(code=4401, reason="unauthorized")
        return

    from app.agents.liveness import get_run_owner
    owner = get_run_owner(run_id)
    if owner is not None and owner != user_id:
        await ws.close(code=4403, reason="not authorized for this run")
        return

    topic = f"system:{run_id}"
    await manager.connect(ws, topic)
    hb    = asyncio.create_task(_heartbeat(ws))

    try:
        await manager.send(ws, {"type": "connected", "topic": topic})
        while True:
            try:
                raw = await asyncio.wait_for(ws.receive_text(), timeout=300)
                msg = json.loads(raw)
                if msg.get("type") == "ping":
                    await manager.send(ws, {"type": "pong"})
            except asyncio.TimeoutError:
                await manager.send(ws, {"type": "ping"})
    except WebSocketDisconnect:
        pass
    finally:
        hb.cancel()
        manager.disconnect(ws, topic)


# ── Notification stream (per-user, authenticated) ─────────────────────────────

def _user_id_from_ws_token(token: str) -> str | None:
    """Browsers can't set an Authorization header on a WS handshake, so the
    access token travels as a query param instead. Same JWT the REST API
    already issues (app.core.jwt_utils) — its `sub` claim IS the user id,
    no extra DB round-trip needed."""
    if not token:
        return None
    try:
        from app.core.jwt_utils import decode_access_token
        return decode_access_token(token).get("sub")
    except Exception:
        return None


@router.websocket("/ws/notifications")
async def notifications_ws(ws: WebSocket):
    """Live stream of this user's own notifications. Emits
    {"type": "event", "topic": "notifications:{user_id}", "data": <notification>}
    frames as new notifications are created (see app/core/notifications/
    dispatcher.py). Clients should also poll GET /api/notifications on
    connect/reconnect to backfill anything missed while disconnected.

    Also doubles as the transport for presence heartbeats (see
    app/core/presence/service.py) — no separate socket. The client sends
    {"type": "ping"} every ~15s; each one (plus the initial connect) refreshes
    this user's online TTL. The same socket is subscribed to
    `presence:{user_id}`, so {"type": "event", "topic": "presence:{user_id}",
    "data": {"user_id": ..., "online": ...}} frames for this user's org-mates
    arrive here too, interleaved with notification events."""
    token   = ws.query_params.get("token", "")
    user_id = _user_id_from_ws_token(token)
    if not user_id:
        await ws.close(code=4401, reason="unauthorized")
        return

    from app.core.presence import get_presence_service
    presence = get_presence_service()

    topic          = f"notifications:{user_id}"
    presence_topic = f"presence:{user_id}"
    await manager.connect(ws, topic)
    await manager.connect(ws, presence_topic)
    await presence.touch(user_id)
    hb    = asyncio.create_task(_heartbeat(ws))

    try:
        await manager.send(ws, {"type": "connected", "topic": topic})
        while True:
            try:
                raw = await asyncio.wait_for(ws.receive_text(), timeout=300)
                msg = json.loads(raw)
                if msg.get("type") == "ping":
                    await presence.touch(user_id)
                    await manager.send(ws, {"type": "pong"})
            except asyncio.TimeoutError:
                await manager.send(ws, {"type": "ping"})
    except WebSocketDisconnect:
        pass
    finally:
        hb.cancel()
        manager.disconnect(ws, topic)
        manager.disconnect(ws, presence_topic)
        # Only the user's LAST open connection (they may have several tabs)
        # should flip them offline.
        if manager.subscriber_count(topic) == 0:
            await presence.mark_offline(user_id)


# ── Team chat stream ─────────────────────────────────────────────────────────

async def _resolve_chat_room(room_key: str) -> str | None:
    """room_key is `org:{org_id}` (the org-wide "General" room) or
    `team:{team_id}` (a specific team's room). Returns the organization_id
    the room belongs to, or None if room_key is malformed or the team
    doesn't exist — either way the caller closes the connection."""
    import uuid as uuid_mod

    if room_key.startswith("org:"):
        org_id = room_key[len("org:"):]
        try:
            uuid_mod.UUID(org_id)
        except ValueError:
            return None
        return org_id

    if room_key.startswith("team:"):
        team_id = room_key[len("team:"):]
        try:
            uuid_mod.UUID(team_id)
        except ValueError:
            return None
        from app.core.db import get_pool
        async with get_pool().acquire() as conn:
            org_id = await conn.fetchval(
                "SELECT organization_id FROM teams WHERE id=$1 AND deleted_at IS NULL",
                uuid_mod.UUID(team_id),
            )
        return str(org_id) if org_id else None

    return None


@router.websocket("/ws/chat/{room_key}")
async def chat_ws(ws: WebSocket, room_key: str):
    """Live delivery for Teams/Organizations chat (app/core/chat/). New
    messages arrive as {"type": "event", "topic": "chat:{room_key}",
    "data": <message>} — posting itself happens over REST
    (POST /api/orgs/{org_id}/chat/messages or .../teams/{team_id}/chat/
    messages), which broadcasts here after persisting. Clients should fetch
    the REST history endpoint on connect/reconnect to backfill."""
    token   = ws.query_params.get("token", "")
    user_id = _user_id_from_ws_token(token)
    if not user_id:
        await ws.close(code=4401, reason="unauthorized")
        return

    org_id = await _resolve_chat_room(room_key)
    if org_id is None:
        await ws.close(code=4404, reason="room not found")
        return

    from app.tenancy import get_tenancy_service
    role = await get_tenancy_service().get_member_role(org_id, user_id)
    if role is None:
        await ws.close(code=4403, reason="not a member of this organization")
        return

    topic = f"chat:{room_key}"
    await manager.connect(ws, topic)
    hb    = asyncio.create_task(_heartbeat(ws))

    try:
        await manager.send(ws, {"type": "connected", "topic": topic})
        while True:
            try:
                raw = await asyncio.wait_for(ws.receive_text(), timeout=300)
                msg = json.loads(raw)
                if msg.get("type") == "ping":
                    await manager.send(ws, {"type": "pong"})
            except asyncio.TimeoutError:
                await manager.send(ws, {"type": "ping"})
    except WebSocketDisconnect:
        pass
    finally:
        hb.cancel()
        manager.disconnect(ws, topic)
