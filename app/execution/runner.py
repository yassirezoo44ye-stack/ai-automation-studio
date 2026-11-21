"""
ExecutionEngine — App Builder entry points backed exclusively by isolated microVMs.

Host drivers are retained for legacy internal callers, never dispatched here.

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
import secrets
import shlex
from pathlib import Path
from collections.abc import AsyncIterator, AsyncGenerator

import contextlib

log = logging.getLogger(__name__)

_SHELL_CHARS: frozenset[str] = frozenset(";& |><`$(){}\\")
_ALLOWED_EXECUTABLES: frozenset[str] = frozenset({"python", "python3", "node", "npm"})

_HEARTBEAT_INTERVAL = 10.0  # seconds


# ── Public API ────────────────────────────────────────────────────────────────

async def run_stream(
    project_id: str,
    ws: Path,
    command_override: str | None,
    request_id: str | None = None,
) -> AsyncIterator[str]:
    rid = request_id or secrets.token_hex(8)
    async for chunk in _with_heartbeat(_run(project_id, ws, command_override, rid)):
        yield chunk


async def run_sync(
    project_id: str,
    ws: Path,
    command_override: str | None,
    request_id: str | None = None,
) -> dict:
    rid = request_id or secrets.token_hex(8)
    last: dict = {"type": "error", "category": "execution",
                  "message": "No response from execution engine",
                  "fix": ["Retry the operation"], "severity": "high", "recoverable": True}
    async for chunk in _run(project_id, ws, command_override, rid):
        if chunk.startswith("data: "):
            try:
                ev = json.loads(chunk[6:])
                if ev.get("type") in ("done", "error", "html", "server_ready", "unsupported"):
                    last = ev
            except Exception:
                pass
    return last


# ── Core ──────────────────────────────────────────────────────────────────────

async def _run(project_id: str, ws: Path, command_override: str | None, request_id: str = ""):
    # Generated projects must never enter the legacy host driver chain.
    from app.execution.isolated import stream
    async with contextlib.aclosing(stream(project_id, ws, command_override)) as events:
        async for event in events:
            yield event


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
        with contextlib.suppress(asyncio.CancelledError, StopAsyncIteration):
            await pending
        await it.aclose()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ev(type_: str, **kw) -> str:
    return f"data: {json.dumps({'type': type_, **kw})}\n\n"


def _validate_command(raw: str) -> list[str] | None:
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
