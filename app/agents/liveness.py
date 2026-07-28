"""
AgentOS agent liveness — tracks each registered agent's current
execution state (idle/running) in-process and broadcasts every
transition live over the existing WS `_ConnectionManager`
(app/routers/ws.py), onto the same "system" topic `/ws/system` already
serves ("System-wide broadcast channel. Receives all agent + job
events." — previously true only in the docstring; this is what
actually makes it true). No new WS endpoint needed.

The signal itself already exists: AgentKernel.run() publishes
"agent.started"/"agent.finished" on the platform EventBus for every
invocation (app/agents/kernel.py's `_publish_agent_event`). This module
is a thin bridge from that event bus to the WS layer — the same shape
app/core/notifications/dispatcher.py already uses for a different
event set, and app/core/presence/service.py uses for user presence.

Deliberately in-process, not Redis-backed like PresenceService: agent
execution is synchronous within a single backend process's HTTP
request (see AgentKernel.run()), so there's no cross-instance state to
reconcile the way user online/offline status needs — a process restart
clears it, which is correct, since every agent goes back to idle on
boot anyway.
"""
from __future__ import annotations

import logging
import time
from typing import Any

log = logging.getLogger(__name__)

_running: dict[str, float] = {}  # agent_name -> started_at (epoch seconds)
_wired = False


def is_running(agent_name: str) -> bool:
    return agent_name in _running


def snapshot() -> dict[str, dict[str, Any]]:
    """Current status of every agent this process has an in-flight
    agent.started for — merged into GET /api/agentos/agents so the UI
    is correct on first load, before any WS frame has arrived."""
    now = time.time()
    return {
        name: {"status": "running", "running_since": started_at, "duration_s": round(now - started_at, 1)}
        for name, started_at in _running.items()
    }


async def _on_agent_event(event) -> None:
    agent_name = event.data.get("agent")
    if not agent_name:
        return

    if event.type == "agent.started":
        _running[agent_name] = time.time()
        frame: dict[str, Any] = {"agent": agent_name, "status": "running"}
    elif event.type == "agent.finished":
        _running.pop(agent_name, None)
        frame = {
            "agent": agent_name, "status": "idle",
            "success": event.data.get("success"), "duration_ms": event.data.get("duration_ms"),
        }
    else:
        return

    try:
        from app.routers.ws import manager as ws_manager
        await ws_manager.broadcast("system", frame)
    except Exception:
        log.warning("agentos liveness broadcast failed for agent=%s", agent_name, exc_info=True)


def wire_agent_liveness() -> None:
    """Idempotent — safe to call from factory setup on every worker."""
    global _wired
    if _wired:
        return
    _wired = True

    from app.core.events import get_event_bus
    bus = get_event_bus()
    bus.subscribe("agent.started", _on_agent_event)
    bus.subscribe("agent.finished", _on_agent_event)
    log.info("AgentOS liveness bridge wired")
