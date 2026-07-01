"""
Driver: Python server projects — FastAPI (uvicorn), Flask (auto pip-install), generic WSGI/ASGI.
Installs requirements.txt if present, then starts the server and proxies via process_mgr.
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import time
from pathlib import Path
from typing import Optional

from app.execution import process_mgr, registry

_HANDLED_TYPES = {"fastapi", "flask", "aiohttp", "tornado"}
_HANDLED_STRATEGIES = {"server", "flask"}


def can_handle(info) -> bool:
    return info.project_type in _HANDLED_TYPES or info.run_strategy in _HANDLED_STRATEGIES


async def stream(project_id: str, ws: Path, info, command_override: Optional[str] = None):
    python = registry.best_python()

    # Auto-install requirements if they exist
    reqs = ws / "requirements.txt"
    if reqs.exists():
        yield _ev("status", message="📦 Installing Python dependencies…")
        ok = await _pip_install(ws, python)
        if not ok:
            yield _ev("status", message="⚠ pip install failed — continuing with available packages…")

    port = process_mgr.allocate_port()
    if port is None:
        yield _ev("error", error="No available ports. Stop other running projects first.",
                  project_type=info.project_type)
        return

    # Build the command
    if command_override:
        from app.execution.runner import _validate_command
        args = _validate_command(command_override)
        if not args:
            yield _ev("status", message=f"⚠ Unsafe override ignored, using auto-detect.")
            args = _default_args(info, python, port)
    else:
        args = _default_args(info, python, port)

    if not args:
        process_mgr._used_ports.discard(port)
        yield _ev("error",
                  error=f"Cannot determine run command for {info.project_type}.",
                  details="Add a main.py or app.py with a recognisable entry point.",
                  project_type=info.project_type)
        return

    env = {**os.environ, "PORT": str(port), "FLASK_RUN_PORT": str(port),
           "FLASK_ENV": "development"}
    yield _ev("status", message=f"▶ {' '.join(args)}  (port {port})",
              command=" ".join(args), port=port)

    start = time.time()
    try:
        rp = await process_mgr.start_server(
            project_id=project_id, args=args, cwd=str(ws),
            env=env, port=port, project_type=info.project_type,
        )
    except FileNotFoundError:
        process_mgr._used_ports.discard(port)
        yield _ev("error", error=f"Executable not found: {args[0]}",
                  project_type=info.project_type)
        return
    except Exception as e:
        process_mgr._used_ports.discard(port)
        yield _ev("error", error=str(e), project_type=info.project_type)
        return

    yield _ev("status", message=f"⏳ Waiting for server on :{port}…")
    ready = await _wait_ready(rp, port, timeout=30.0)

    if not ready:
        stderr_text = ""
        try:
            out, err = await asyncio.wait_for(rp.process.communicate(), timeout=2.0)
            stderr_text = (err or b"").decode("utf-8", errors="replace")
        except Exception:
            try:
                rp.process.kill()
            except Exception:
                pass
        process_mgr._release(project_id)
        yield _ev("error",
                  error="Server failed to start",
                  details=(
                      f"Port {port} did not respond within 30 s. "
                      "Ensure the app listens on the PORT environment variable."
                  ),
                  stderr=stderr_text,
                  project_type=info.project_type,
                  hint=_hint(info.project_type))
        return

    yield _ev("server_ready",
              preview_url=f"/api/projects/{project_id}/proxy/",
              port=port,
              project_type=info.project_type,
              message=f"✓ Server ready in {round(time.time() - start, 2)}s",
              command=" ".join(args))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _default_args(info, python: str, port: int) -> Optional[list]:
    entry = info.entry_point or "main.py"
    pt = info.project_type
    if pt == "fastapi":
        module = entry.replace(".py", "").replace("/", ".").replace("\\", ".")
        return [python, "-m", "uvicorn", f"{module}:app",
                "--host", "0.0.0.0", "--port", str(port), "--reload"]
    if pt == "flask":
        app_module = entry.replace(".py", "").replace("/", ".").replace("\\", ".")
        return [python, "-m", "flask", "--app", app_module,
                "run", "--host", "0.0.0.0", "--port", str(port)]
    # Generic server — run directly and hope it reads PORT env var
    return [python, "-u", entry]


async def _pip_install(ws: Path, python: str) -> bool:
    try:
        proc = await asyncio.create_subprocess_exec(
            python, "-m", "pip", "install", "-r", "requirements.txt", "--quiet",
            cwd=str(ws),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(proc.communicate(), timeout=120.0)
        return proc.returncode == 0
    except Exception:
        return False


async def _wait_ready(rp, port: int, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                return True
        except OSError:
            pass
        if not rp.alive:
            return False
        await asyncio.sleep(0.25)
    return False


def _hint(project_type: str) -> str:
    hints = {
        "fastapi": (
            "Expose 'app = FastAPI()' at module level. "
            "Do not call uvicorn.run() inside if __name__ == '__main__'."
        ),
        "flask": (
            "Expose 'app = Flask(__name__)' at module level. "
            "Do not call app.run() inside if __name__ == '__main__'."
        ),
    }
    return hints.get(project_type, "Check the entry file for import errors.")


def _ev(type_: str, **kw) -> str:
    return f"data: {json.dumps({'type': type_, **kw})}\n\n"
