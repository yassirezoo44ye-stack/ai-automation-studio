"""
ExecutionEngine — coordinates detection, validation, and streaming execution.

Entry points:
  run_stream(project_id, ws, command_override)  → AsyncIterator[str] (SSE lines)
  run_sync(project_id, ws, command_override)    → dict

SSE event types emitted by run_stream:
  status        — progress message
  log           — one stdout/stderr line
  html          — static HTML content (frontend renders in iframe)
  server_ready  — server started, preview_url available
  unsupported   — project type not runnable in sandbox
  done          — script finished  {exit_code, duration, stdout, stderr}
  error         — fatal error  {error, details, ...}
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shlex
import time
from pathlib import Path
from typing import AsyncIterator, Optional

from app.execution import detector as det
from app.execution import process_mgr as pm

log = logging.getLogger(__name__)

# Only Python is available in the production Docker image
_ALLOWED_EXECUTABLES: frozenset[str] = frozenset({"python", "python3"})
_SHELL_CHARS: frozenset[str] = frozenset(";& |><`$(){}\\")


# ── Public API ────────────────────────────────────────────────────────────────

async def run_stream(
    project_id: str,
    ws: Path,
    command_override: Optional[str],
) -> AsyncIterator[str]:
    """Yield SSE-formatted strings for the project run."""
    async for chunk in _run(project_id, ws, command_override):
        yield chunk


async def run_sync(
    project_id: str,
    ws: Path,
    command_override: Optional[str],
) -> dict:
    """
    Collect all SSE events and return the final result dict.
    Used by the sync /run endpoint as a fallback.
    """
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


# ── Core stream ───────────────────────────────────────────────────────────────

async def _run(
    project_id: str,
    ws: Path,
    command_override: Optional[str],
) -> AsyncIterator[str]:

    # ── Workspace validation ───────────────────────────────────────────────
    if not ws.exists():
        yield _ev("error",
                  error="Workspace not found",
                  details=f"No workspace for project '{project_id}'. Build first.",
                  project_type="unknown", checked_files=[])
        return

    workspace_files = sorted(
        str(p.relative_to(ws)).replace("\\", "/")
        for p in ws.rglob("*") if p.is_file()
    )

    if not workspace_files:
        yield _ev("error",
                  error="Empty workspace",
                  details="No files found. Build the project first.",
                  project_type="unknown", checked_files=[])
        return

    # ── Detection ──────────────────────────────────────────────────────────
    info = det.detect(ws)
    yield _ev("status",
              message=f"🔍 {info.project_type} ({info.confidence} confidence)",
              project_type=info.project_type,
              entry_point=info.entry_point,
              run_strategy=info.run_strategy)

    # ── Unsupported ────────────────────────────────────────────────────────
    if info.run_strategy == "unsupported":
        yield _ev("unsupported",
                  project_type=info.project_type,
                  error=f"{info.project_type} — not available in sandbox",
                  details=info.unsupported_reason,
                  local_run_hint=info.local_run_hint,
                  checked_files=workspace_files)
        return

    # ── Static HTML ────────────────────────────────────────────────────────
    if info.run_strategy == "static":
        async for chunk in _serve_html(ws, info, workspace_files):
            yield chunk
        return

    # ── Validate command override ──────────────────────────────────────────
    user_args: Optional[list[str]] = None
    if command_override:
        user_args = _validate_command(command_override)
        if user_args is None:
            yield _ev("status",
                      message=f"⚠ Ignoring unsafe override '{command_override}', using auto-detect")

    # ── Build command ──────────────────────────────────────────────────────
    if info.run_strategy == "server":
        async for chunk in _run_server(project_id, ws, info, user_args, workspace_files):
            yield chunk
        return

    # ── Script ────────────────────────────────────────────────────────────
    async for chunk in _run_script(project_id, ws, info, user_args, workspace_files):
        yield chunk


# ── Static serving ────────────────────────────────────────────────────────────

async def _serve_html(ws: Path, info: det.ProjectInfo, workspace_files: list[str]):
    entry = info.entry_point
    if not entry:
        yield _ev("error",
                  error="No HTML entry point",
                  details="Project detected as HTML but no .html file found.",
                  project_type="html", checked_files=workspace_files)
        return
    try:
        content = (ws / entry).read_text(encoding="utf-8")
    except Exception as e:
        yield _ev("error",
                  error=f"Cannot read {entry}",
                  details=str(e),
                  project_type="html", checked_files=workspace_files)
        return
    yield _ev("html",
              html_content=content,
              entry_file=entry,
              project_type="html",
              message=f"Opening {entry} in preview…")


# ── Server execution ──────────────────────────────────────────────────────────

async def _run_server(  # noqa: E302  (async generator)
    project_id: str,
    ws: Path,
    info: det.ProjectInfo,
    user_args: Optional[list[str]],
    workspace_files: list[str],
):
    port = pm.allocate_port()
    if port is None:
        yield _ev("error",
                  error="No available ports",
                  details="All sandbox ports are in use. Stop other running projects.",
                  project_type=info.project_type)
        return

    args = user_args or _server_command(info, port)
    if not args:
        yield _ev("error",
                  error="Cannot resolve server command",
                  details=f"No command for {info.project_type}.",
                  project_type=info.project_type, checked_files=workspace_files)
        pm._used_ports.discard(port)
        return

    env = {**os.environ, "PORT": str(port)}

    yield _ev("status",
              message=f"▶ {' '.join(args)}  (port {port})",
              command=" ".join(args),
              port=port)

    start_time = time.time()
    try:
        rp = await pm.start_server(
            project_id=project_id,
            args=args,
            cwd=str(ws),
            env=env,
            port=port,
            project_type=info.project_type,
        )
    except FileNotFoundError:
        yield _ev("error",
                  error=f"Executable not found: {args[0]}",
                  details="Only Python/uvicorn are available in this sandbox.",
                  project_type=info.project_type)
        return
    except Exception as e:
        yield _ev("error",
                  error="Failed to start server",
                  details=str(e),
                  project_type=info.project_type)
        return

    # Stream early startup logs while waiting for readiness
    yield _ev("status", message=f"⏳ Waiting for server on :{port}…")

    ready = await _wait_ready_with_logs(rp, port, timeout=20.0)

    if not ready:
        # Collect error output
        stdout_b, stderr_b = b"", b""
        try:
            stdout_b, stderr_b = await asyncio.wait_for(rp.process.communicate(), timeout=2.0)
        except Exception:
            try: rp.process.kill()
            except Exception: pass
        pm._release(project_id)

        yield _ev("error",
                  error="Server failed to start",
                  details=(
                      f"Port {port} did not become available within 20 s. "
                      "Check that your app listens on the PORT environment variable "
                      f"(set to {port}) rather than a hard-coded port."
                  ),
                  stdout=stdout_b.decode("utf-8", errors="replace"),
                  stderr=stderr_b.decode("utf-8", errors="replace"),
                  exit_code=rp.process.returncode,
                  project_type=info.project_type,
                  hint=_server_local_hint(info.project_type))
        return

    elapsed = round(time.time() - start_time, 2)
    yield _ev("server_ready",
              preview_url=f"/api/projects/{project_id}/proxy/",
              port=port,
              project_type=info.project_type,
              message=f"✓ Server ready in {elapsed}s",
              command=" ".join(args))


async def _wait_ready_with_logs(rp: pm.RunningProcess, port: int, timeout: float) -> bool:
    """Wait for port readiness; also drain startup stdout/stderr lines."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pm._port_open(port):
            return True
        if not rp.alive:
            return False
        await asyncio.sleep(0.25)
    return False


def _server_command(info: det.ProjectInfo, port: int) -> list[str]:
    entry = info.entry_point or "main.py"
    if info.project_type == "fastapi":
        module = entry.replace(".py", "").replace("/", ".").replace("\\", ".")
        return ["python", "-m", "uvicorn", f"{module}:app",
                "--host", "127.0.0.1", "--port", str(port)]
    return []


def _server_local_hint(project_type: str) -> str:
    hints = {
        "fastapi": (
            "Make sure your app exposes 'app = FastAPI()' at module level, "
            "and does NOT call uvicorn.run() inside an if __name__ == '__main__' block "
            "that prevents module import."
        ),
    }
    return hints.get(project_type, "Check the entry file for import errors.")


# ── Script execution ──────────────────────────────────────────────────────────

async def _run_script(
    project_id: str,
    ws: Path,
    info: det.ProjectInfo,
    user_args: Optional[list[str]],
    workspace_files: list[str],
) -> AsyncIterator[str]:

    args = user_args or ["python", "-u", info.entry_point or "main.py"]
    yield _ev("status", message=f"▶ {' '.join(args)}", command=" ".join(args))

    env = {**os.environ}
    start_time = time.time()

    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(ws),
            env=env,
        )
    except FileNotFoundError:
        yield _ev("error",
                  error=f"Executable not found: {args[0]}",
                  details="Only Python is available in this sandbox.",
                  project_type=info.project_type)
        return
    except Exception as e:
        yield _ev("error",
                  error="Failed to start process",
                  details=str(e),
                  project_type=info.project_type)
        return

    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    log_q: asyncio.Queue = asyncio.Queue()

    async def pump(stream: asyncio.StreamReader, name: str) -> None:
        async for raw in stream:
            await log_q.put((name, raw.decode("utf-8", errors="replace").rstrip()))
        await log_q.put((name, None))  # sentinel

    t_out = asyncio.create_task(pump(proc.stdout, "stdout"))
    t_err = asyncio.create_task(pump(proc.stderr, "stderr"))

    timeout = 30
    deadline = time.time() + timeout
    done_streams = 0

    while done_streams < 2:
        remaining = deadline - time.time()
        if remaining <= 0:
            proc.terminate()
            yield _ev("warning",
                      message=f"Script timed out after {timeout}s — terminated.",
                      project_type=info.project_type)
            break
        try:
            name, line = await asyncio.wait_for(log_q.get(), timeout=min(0.5, remaining))
        except asyncio.TimeoutError:
            if proc.returncode is not None:
                break
            continue
        if line is None:
            done_streams += 1
        else:
            (stdout_lines if name == "stdout" else stderr_lines).append(line)
            yield _ev("log", stream=name, line=line, ts=round(time.time(), 3))

    # Wait for process to exit
    try:
        await asyncio.wait_for(proc.wait(), timeout=2.0)
    except asyncio.TimeoutError:
        proc.kill()

    t_out.cancel()
    t_err.cancel()

    rc = proc.returncode if proc.returncode is not None else -1
    elapsed = round(time.time() - start_time, 2)

    result: dict = {
        "exit_code": rc,
        "duration": elapsed,
        "stdout": "\n".join(stdout_lines),
        "stderr": "\n".join(stderr_lines),
        "project_type": info.project_type,
        "command": " ".join(args),
        "success": rc == 0,
    }

    if not stdout_lines and not stderr_lines and rc == 0:
        result["warning"] = (
            "Script exited successfully with no output. "
            "Add print() calls to see results."
        )

    yield _ev("done", **result)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ev(type_: str, **kwargs) -> str:
    return f"data: {json.dumps({'type': type_, **kwargs})}\n\n"


def _validate_command(raw: str) -> Optional[list[str]]:
    """
    Validate a user-supplied command string.
    Returns parsed args list, or None if the command is unsafe/unsupported.
    """
    if any(c in raw for c in _SHELL_CHARS):
        return None
    try:
        args = shlex.split(raw)
    except ValueError:
        return None
    if not args or args[0] not in _ALLOWED_EXECUTABLES:
        return None
    # Prevent path traversal in arguments
    for arg in args[1:]:
        if ".." in arg or arg.startswith("/") or (len(arg) > 1 and arg[1] == ":"):
            return None
    return args
