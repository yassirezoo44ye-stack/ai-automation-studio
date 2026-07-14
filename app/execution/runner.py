"""
ExecutionEngine — detects project type and dispatches to the appropriate driver.

Phase 3: Merged run/build/package decision flow via driver chain.
Phase 4: Every run stream includes a 10-second SSE heartbeat.
Phase 2: Preflight gate blocks execution before any subprocess if tools missing.

Driver chain (checked in order, first match wins):
  static          HTML projects
  python_script   Python scripts (non-server)
  python_server   FastAPI / Flask / generic Python server
  node            Node.js / npm projects (when node/npm is available)
  fallback        Anything else — shows a helpful unsupported message

SSE event types:
  status        progress update
  log           one stdout/stderr line
  html          static HTML content (frontend renders blob URL)
  server_ready  server started, preview_url available
  unsupported   project type not runnable here
  done          script finished  {exit_code, duration, stdout, stderr}
  error         structured error {category, message, fix, severity, recoverable}
  heartbeat     keepalive every 10 s — frontend should ignore
"""
from __future__ import annotations

import asyncio
import json
import logging
import shlex
from pathlib import Path
from typing import AsyncIterator, AsyncGenerator, Optional

from app.execution import detector as det
from app.execution.drivers import fallback, node, python_script, python_server, static
from app.runtime.errors import sse_error
from app.runtime.preflight import run_preflight_for_strategy, preflight_error_events

log = logging.getLogger(__name__)

_SHELL_CHARS: frozenset[str] = frozenset(";& |><`$(){}\\")
_ALLOWED_EXECUTABLES: frozenset[str] = frozenset({"python", "python3", "node", "npm"})

# Drivers checked in order — first whose can_handle() returns True wins
_DRIVER_CHAIN = [static, python_script, python_server, node, fallback]

# Strategies that have no runtime requirement (always safe to run)
_NO_PREFLIGHT_STRATEGIES = frozenset({"static", "unsupported"})

_HEARTBEAT_INTERVAL = 10.0  # seconds


# ── Public API ────────────────────────────────────────────────────────────────

async def run_stream(
    project_id: str,
    ws: Path,
    command_override: Optional[str],
) -> AsyncIterator[str]:
    async for chunk in _with_heartbeat(_run(project_id, ws, command_override)):
        yield chunk


async def run_sync(
    project_id: str,
    ws: Path,
    command_override: Optional[str],
) -> dict:
    last: dict = {"type": "error", "category": "execution",
                  "message": "No response from execution engine",
                  "fix": ["Retry the operation"], "severity": "high", "recoverable": True}
    async for chunk in _run(project_id, ws, command_override):
        if chunk.startswith("data: "):
            try:
                ev = json.loads(chunk[6:])
                if ev.get("type") in ("done", "error", "html", "server_ready", "unsupported"):
                    last = ev
            except Exception:
                pass
    return last


# ── Core ──────────────────────────────────────────────────────────────────────

async def _run(project_id: str, ws: Path, command_override: Optional[str]):
    if not ws.exists():
        yield sse_error(
            category="config",
            message=f"Workspace not found for project '{project_id}'",
            fix=["Build the project first to create a workspace"],
            severity="high",
        )
        return

    if not any(ws.rglob("*")):
        yield sse_error(
            category="config",
            message="Workspace is empty — no files to run",
            fix=["Use the Build tab to generate project files first"],
            severity="high",
        )
        return

    info = det.detect(ws)
    log.info("run project=%s type=%s strategy=%s entry=%s",
             project_id, info.project_type, info.run_strategy, info.entry_point)

    yield _ev("status",
              message=f"🔍 Detected: {info.project_type} ({info.confidence} confidence)",
              project_type=info.project_type,
              entry_point=info.entry_point,
              run_strategy=info.run_strategy)

    # ── Phase 2: preflight gate ───────────────────────────────────────────────
    if info.run_strategy not in _NO_PREFLIGHT_STRATEGIES:
        pf = run_preflight_for_strategy(info.run_strategy)
        if not pf.ok:
            for ev in preflight_error_events(pf):
                yield ev
            return

    # ── Phase 3: driver dispatch ──────────────────────────────────────────────
    for driver in _DRIVER_CHAIN:
        if driver.can_handle(info):
            async for chunk in driver.stream(project_id, ws, info, command_override):
                yield chunk
            return

    yield sse_error(
        category="execution",
        message="No driver matched this project type",
        fix=["Add a main.py, index.html, or package.json to the project"],
        severity="medium",
    )


# ── Phase 4: heartbeat wrapper ────────────────────────────────────────────────

async def _with_heartbeat(
    gen: AsyncGenerator[str, None],
    interval: float = _HEARTBEAT_INTERVAL,
) -> AsyncGenerator[str, None]:
    """
    Wraps any async generator and injects a heartbeat SSE event every
    *interval* seconds if no chunk arrives in time.

    Uses asyncio.shield so the underlying generator is never cancelled
    by the timeout — only the wait itself times out.
    """
    _hb = f"data: {json.dumps({'type': 'heartbeat', 'message': 'still running'})}\n\n"

    async def _anext_safe(it):
        try:
            return await it.__anext__()
        except StopAsyncIteration:
            return None

    it = gen.__aiter__()
    pending: asyncio.Future = asyncio.ensure_future(_anext_safe(it))

    try:
        while True:
            try:
                result = await asyncio.wait_for(asyncio.shield(pending), timeout=interval)
                if result is None:
                    return          # generator exhausted
                yield result
                pending = asyncio.ensure_future(_anext_safe(it))
            except asyncio.TimeoutError:
                yield _hb           # emit heartbeat; pending task still running
    finally:
        pending.cancel()
        try:
            await pending
        except (asyncio.CancelledError, StopAsyncIteration):
            pass


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ev(type_: str, **kw) -> str:
    return f"data: {json.dumps({'type': type_, **kw})}\n\n"


def _validate_command(raw: str) -> Optional[list[str]]:
    """Validate a user-supplied command. Returns arg list or None if unsafe."""
    if any(c in raw for c in _SHELL_CHARS):
        return None
    try:
        args = shlex.split(raw)
    except ValueError:
        return None
    if not args or args[0] not in _ALLOWED_EXECUTABLES:
        return None
    for arg in args[1:]:
        if ".." in arg or arg.startswith("/") or (len(arg) > 1 and arg[1] == ":"):
            return None
    return args
