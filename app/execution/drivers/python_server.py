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

from app.execution import process_mgr
from app.runtime import registry
from app.runtime import process as rt_process
from app.runtime.errors import sse_error

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
        yield sse_error(
            category="execution",
            message="No available ports — all slots are in use",
            fix=["Stop other running projects to free a port"],
            severity="medium",
            recoverable=True,
            project_type=info.project_type,
        )
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
        yield sse_error(
            category="config",
            message=f"Cannot determine run command for {info.project_type}",
            fix=["Add a main.py or app.py with a recognisable entry point"],
            severity="high",
            recoverable=False,
            project_type=info.project_type,
        )
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
        yield sse_error(
            category="missing_runtime",
            message=f"Executable not found: {args[0]}",
            fix=[f"Install {args[0]} and ensure it is on PATH",
                 "Restart the server after installation"],
            severity="high",
            recoverable=False,
            project_type=info.project_type,
        )
        return
    except Exception as e:
        process_mgr._used_ports.discard(port)
        yield sse_error(
            category="execution",
            message="Unexpected error starting server process",
            fix=["Check the project entry file for syntax errors",
                 "Verify all dependencies are installed"],
            severity="high",
            recoverable=True,
            project_type=info.project_type,
        )
        return

    yield _ev("status", message=f"⏳ Waiting for server on :{port}…")
    ready = await _wait_ready(rp, port, timeout=30.0)

    if not ready:
        stderr_text = ""
        try:
            _, err_bytes = await asyncio.wait_for(rp.process.communicate(), timeout=2.0)
            stderr_text = (err_bytes or b"").decode("utf-8", errors="replace")
        except Exception:
            try:
                rp.process.kill()
            except Exception:
                pass
        process_mgr._release(project_id)
        yield sse_error(
            category="execution",
            message=f"Server failed to start — port {port} did not respond within 30 s",
            fix=[
                "Ensure the app listens on the PORT environment variable",
                _hint(info.project_type),
            ],
            severity="high",
            recoverable=True,
            project_type=info.project_type,
            stderr=stderr_text[:500] if stderr_text else None,
        )
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
    rc, _, _ = await rt_process.run_process(
        [python, "-m", "pip", "install", "-r", "requirements.txt", "--quiet"],
        cwd=ws,
        timeout=120.0,
    )
    return rc == 0


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


