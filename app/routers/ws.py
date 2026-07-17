"""
WebSocket real-time channel — Layer 16 surface.

Endpoints:
  WS /ws/agent/{session_id}       live agent output stream
  WS /ws/job/{job_id}             background job progress stream
  WS /ws/system                   system-wide broadcast (admin)

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

log = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])

# ── Connection manager ────────────────────────────────────────────────────────

class _ConnectionManager:
    def __init__(self) -> None:
        # topic → list of active websockets
        self._subs: dict[str, list[WebSocket]] = {}

    async def connect(self, ws: WebSocket, topic: str) -> None:
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
    """
    topic = f"agent:{session_id}"
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
                    if extra:
                        await manager.connect(ws, extra)
                        await manager.send(ws, {"type": "subscribed", "topic": extra})

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
        manager.disconnect(ws, topic)


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


# ── System broadcast (admin) ──────────────────────────────────────────────────

@router.websocket("/ws/system")
async def system_ws(ws: WebSocket):
    """System-wide broadcast channel. Receives all agent + job events."""
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
