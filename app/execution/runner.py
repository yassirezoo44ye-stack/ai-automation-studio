"""
ExecutionEngine — detects project type and dispatches to the appropriate driver.

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
  error         fatal error
  heartbeat     keepalive (frontend should ignore)
"""
from __future__ import annotations

import json
import logging
import shlex
from pathlib import Path
from typing import AsyncIterator, Optional

from app.execution import detector as det
from app.execution.drivers import fallback, node, python_script, python_server, static

log = logging.getLogger(__name__)

_SHELL_CHARS: frozenset[str] = frozenset(";& |><`$(){}\\")
_ALLOWED_EXECUTABLES: frozenset[str] = frozenset({"python", "python3", "node", "npm"})

# Drivers checked in order — first whose can_handle() returns True wins
_DRIVER_CHAIN = [static, python_script, python_server, node, fallback]


# ── Public API ────────────────────────────────────────────────────────────────

async def run_stream(
    project_id: str,
    ws: Path,
    command_override: Optional[str],
) -> AsyncIterator[str]:
    async for chunk in _run(project_id, ws, command_override):
        yield chunk


async def run_sync(
    project_id: str,
    ws: Path,
    command_override: Optional[str],
) -> dict:
    last: dict = {"type": "error", "error": "No response from execution engine"}
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
        yield _ev("error",
                  error="Workspace not found",
                  details=f"No workspace for project '{project_id}'. Build the project first.")
        return

    if not any(ws.rglob("*")):
        yield _ev("error", error="Empty workspace",
                  details="No files found. Build the project first.")
        return

    info = det.detect(ws)
    log.info("run project=%s type=%s strategy=%s entry=%s",
             project_id, info.project_type, info.run_strategy, info.entry_point)

    yield _ev("status",
              message=f"🔍 Detected: {info.project_type} ({info.confidence} confidence)",
              project_type=info.project_type,
              entry_point=info.entry_point,
              run_strategy=info.run_strategy)

    for driver in _DRIVER_CHAIN:
        if driver.can_handle(info):
            async for chunk in driver.stream(project_id, ws, info, command_override):
                yield chunk
            return

    yield _ev("error", error="Internal: no driver matched this project type.")


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
