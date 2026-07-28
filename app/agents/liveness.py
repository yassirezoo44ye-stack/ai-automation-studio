"""
AgentOS agent liveness + live step narration — tracks each registered
agent's current execution state (idle/running) in-process and
broadcasts every transition, plus every AgentContext.step() call an
agent makes mid-execution, live over the existing WS
`_ConnectionManager` (app/routers/ws.py), onto the same "system" topic
`/ws/system` already serves ("System-wide broadcast channel. Receives
all agent + job events." — previously true only in the docstring; this
is what actually makes it true). No new WS endpoint needed.

The liveness signal itself already exists: AgentKernel.run() publishes
"agent.started"/"agent.finished" on the platform EventBus for every
invocation (app/agents/kernel.py's `_publish_agent_event`), each
carrying a `run_id` that correlates one specific invocation. This
module is a thin bridge from that event bus to the WS layer — the same
shape app/core/notifications/dispatcher.py already uses for a
different event set, and app/core/presence/service.py uses for user
presence. publish_step() is the second half: agents call
`await ctx.step(...)` from inside execute() to narrate what they're
doing as they do it (see app/agents/builtin/run_agent.py,
build_agent.py, deploy_agent.py) — this is the actual "live computer"
signal, distinct from the started/finished liveness dot.

Deliberately in-process, not Redis-backed like PresenceService: agent
execution is synchronous within a single backend process's HTTP
request (see AgentKernel.run()), so there's no cross-instance state to
reconcile the way user online/offline status needs — a process restart
clears it, which is correct, since every agent goes back to idle on
boot anyway.

Tracked per (agent_name, run_id), not just agent_name: two concurrent
runs of the same agent (two users both running "build" at once) must
not let the first to finish clear liveness for the one still running.
"""
from __future__ import annotations

import logging
import time
from typing import Any

log = logging.getLogger(__name__)

_running: dict[str, dict[str, float]] = {}  # agent_name -> {run_id: started_at}
_wired = False


def is_running(agent_name: str) -> bool:
    return bool(_running.get(agent_name))


def snapshot() -> dict[str, dict[str, Any]]:
    """Current status of every agent with at least one in-flight run in
    this process — merged into GET /api/agentos/agents so the UI is
    correct on first load, before any WS frame has arrived. When an
    agent has more than one concurrent run, reports the oldest one."""
    now = time.time()
    result: dict[str, dict[str, Any]] = {}
    for name, runs in _running.items():
        if not runs:
            continue
        oldest = min(runs.values())
        result[name] = {"status": "running", "running_since": oldest, "duration_s": round(now - oldest, 1)}
    return result


async def publish_step(run_id: str, agent_name: str, description: str, kind: str = "info", **data) -> None:
    """Broadcast one live narrated sub-step. Called from
    AgentContext.step() — never call this directly from an agent,
    call ctx.step() instead, which fills in run_id/agent_name."""
    if not run_id or not agent_name:
        return
    frame = {"run_id": run_id, "agent": agent_name, "step": description, "kind": kind, **data}
    try:
        from app.routers.ws import manager as ws_manager
        await ws_manager.broadcast("system", frame)
    except Exception:
        log.warning("agentos step broadcast failed for agent=%s run=%s", agent_name, run_id, exc_info=True)


async def _on_agent_event(event) -> None:
    agent_name = event.data.get("agent")
    run_id = event.data.get("run_id")
    if not agent_name or not run_id:
        return

    if event.type == "agent.started":
        _running.setdefault(agent_name, {})[run_id] = time.time()
        frame: dict[str, Any] = {"agent": agent_name, "status": "running", "run_id": run_id}
    elif event.type == "agent.finished":
        _running.get(agent_name, {}).pop(run_id, None)
        if agent_name in _running and not _running[agent_name]:
            del _running[agent_name]
        frame = {
            "agent": agent_name, "status": "idle" if not is_running(agent_name) else "running",
            "run_id": run_id,
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
