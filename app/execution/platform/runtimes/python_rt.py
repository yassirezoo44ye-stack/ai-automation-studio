"""
PythonRuntime — replaces python_server.py / python_script.py drivers.

Detection criteria (in order):
  1. requirements.txt or pyproject.toml in workspace root
  2. *.py files in workspace root
  3. main.py / app.py / server.py present

Project types:
  - Flask / FastAPI / Django server  → detect via import sniff → launch with uvicorn/python
  - Plain script                     → run with python <entry>
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from app.execution.platform.errors import (
    EnvironmentError as EnvErr,
    LaunchError,
    build_failed,
    execution_timeout,
    install_failed,
    internal,
    python_missing,
)
from app.execution.platform.events import (
    ExecutionFailed,
    InstallCompleted,
    InstallFailed,
    InstallProgress,
    InstallStarted,
    LogLine,
    ProbeCompleted,
    ServerReady,
    ServerStarting,
    StatusUpdate,
)
from app.execution.platform.runtimes.abstract import AbstractRuntime, ExecutionContext

log = logging.getLogger(__name__)

_SERVER_FRAMEWORKS = ("flask", "fastapi", "django", "starlette", "tornado", "aiohttp", "bottle")
_ENTRY_CANDIDATES  = ("main.py", "app.py", "server.py", "run.py", "wsgi.py", "asgi.py")
_INSTALL_TIMEOUT   = 120
_LAUNCH_TIMEOUT    = 30


class PythonRuntime(AbstractRuntime):
    name     = "python"
    priority = 20

    # ── Detection ────────────────────────────────────────────────────────────

    def detect(self, workspace: Path) -> bool:
        if (workspace / "requirements.txt").exists():
            return True
        if (workspace / "pyproject.toml").exists():
            return True
        py_files = list(workspace.glob("*.py"))
        return len(py_files) > 0

    # ── Probe ────────────────────────────────────────────────────────────────

    async def probe(self, ctx: ExecutionContext) -> None:
        py = shutil.which("python3") or shutil.which("python")
        if not py:
            raise python_missing()

        version = _run_version(py)
        ctx.python_version = version
        ctx.report.python_version = version
        ctx.report.os_name = sys.platform

        ctx.emit(ProbeCompleted(
            execution_id      = ctx.execution_id,
            python_version    = version,
            available_runtimes= ["python"],
        ))

    # ── Install ──────────────────────────────────────────────────────────────

    async def install(self, ctx: ExecutionContext) -> None:
        ws = ctx.sandbox.paths.workspace if ctx.sandbox.paths else ctx.workspace
        req = ws / "requirements.txt"

        if not req.exists():
            ctx.emit(InstallCompleted(
                execution_id = ctx.execution_id,
                skipped      = True,
                skip_reason  = "no requirements.txt",
            ))
            return

        py = shutil.which("python3") or shutil.which("python")
        if not py:
            raise python_missing()

        venv_dir = ws / ".venv"
        pip_cmd  = [py, "-m", "pip", "install", "-r", str(req), "--quiet"]
        env      = {**os.environ, "PIP_NO_COLOR": "1"}

        ctx.emit(InstallStarted(
            execution_id = ctx.execution_id,
            pm           = "pip",
            command      = " ".join(pip_cmd),
        ))

        loop = asyncio.get_event_loop()

        def _run():
            lines_out: list[str] = []
            lines_err: list[str] = []
            try:
                proc = subprocess.Popen(
                    pip_cmd, cwd=str(ws), env=env,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True,
                )
                out, err = proc.communicate(timeout=_INSTALL_TIMEOUT)
                for l in out.splitlines():
                    lines_out.append(l)
                for l in err.splitlines():
                    lines_err.append(l)
                return proc.returncode, lines_out, lines_err
            except subprocess.TimeoutExpired:
                return -1, lines_out, ["pip install timed out"]
            except Exception as exc:
                return -1, [], [str(exc)]

        rc, stdout, stderr = await loop.run_in_executor(None, _run)

        for line in stdout:
            ctx.emit(InstallProgress(execution_id=ctx.execution_id, stream="stdout", line=line))
        for line in stderr:
            ctx.emit(InstallProgress(execution_id=ctx.execution_id, stream="stderr", line=line))

        if rc != 0:
            ctx.emit(InstallFailed(
                execution_id = ctx.execution_id,
                error_code   = "DEP_INSTALL_FAILED",
                message      = f"pip install exited with code {rc}",
                exit_code    = rc,
            ))
            raise install_failed(rc, "pip", stderr)

        ctx.emit(InstallCompleted(execution_id=ctx.execution_id, duration_s=0.0))

    # ── Build ────────────────────────────────────────────────────────────────

    async def build(self, ctx: ExecutionContext) -> None:
        pass  # Python projects don't have a build step

    # ── Launch ───────────────────────────────────────────────────────────────

    async def launch(self, ctx: ExecutionContext) -> None:
        ws    = ctx.sandbox.paths.workspace if ctx.sandbox.paths else ctx.workspace
        entry = _find_entry(ws)
        if not entry:
            raise internal("No Python entry file found (main.py, app.py, …)")

        py    = shutil.which("python3") or shutil.which("python")
        if not py:
            raise python_missing()

        is_server = _is_server_project(ws)

        if is_server:
            await self._launch_server(ctx, py, ws, entry)
        else:
            await self._run_script(ctx, py, ws, entry)

    async def _run_script(
        self, ctx: ExecutionContext, py: str, ws: Path, entry: str,
    ) -> None:
        cmd = [py, entry]
        ctx.emit(StatusUpdate(
            execution_id = ctx.execution_id,
            message      = f"$ {' '.join(cmd)}",
            phase        = "launch",
        ))

        loop = asyncio.get_event_loop()

        def _run():
            try:
                proc = subprocess.Popen(
                    cmd, cwd=str(ws),
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True,
                )
                output, _ = proc.communicate(timeout=60)
                return proc.returncode, output.splitlines()
            except subprocess.TimeoutExpired:
                return -1, ["Script timed out after 60s"]
            except Exception as exc:
                return -1, [str(exc)]

        rc, lines = await loop.run_in_executor(None, _run)
        for line in lines:
            ctx.emit(LogLine(execution_id=ctx.execution_id, line=line, phase="launch"))

        ctx.report.success  = rc == 0
        ctx.report.exit_code= rc

    async def _launch_server(
        self, ctx: ExecutionContext, py: str, ws: Path, entry: str,
    ) -> None:
        from app.execution.process_mgr import allocate_port
        import socket
        import time as _time

        port = allocate_port()
        if not port:
            from app.execution.platform.errors import port_exhausted
            raise port_exhausted()

        ctx.port = port
        env = {**os.environ, "PORT": str(port)}

        cmd = [py, entry]

        ctx.emit(ServerStarting(
            execution_id = ctx.execution_id,
            command      = " ".join(cmd),
            port         = port,
        ))

        proc = subprocess.Popen(
            cmd, cwd=str(ws), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True,
        )
        ctx.pid = proc.pid

        deadline = _time.time() + _LAUNCH_TIMEOUT
        while _time.time() < deadline:
            if proc.poll() is not None:
                out, _ = proc.communicate()
                ctx.emit(ExecutionFailed(
                    execution_id = ctx.execution_id,
                    error_code   = "LAUNCH_CRASH",
                    message      = f"Python server exited (code {proc.returncode})",
                ))
                return
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                    break
            except OSError:
                await asyncio.sleep(0.5)
        else:
            proc.kill()
            ctx.emit(ExecutionFailed(
                execution_id = ctx.execution_id,
                error_code   = "LAUNCH_TIMEOUT",
                message      = f"Python server did not bind port {port} within {_LAUNCH_TIMEOUT}s",
            ))
            return

        preview_url = f"http://localhost:{port}"
        ctx.preview_url = preview_url
        ctx.report.port        = port
        ctx.report.preview_url = preview_url
        ctx.report.pid         = ctx.pid

        ctx.emit(ServerReady(
            execution_id = ctx.execution_id,
            preview_url  = preview_url,
            port         = port,
            command      = " ".join(cmd),
            project_type = "python-server",
        ))

    # ── Cleanup ──────────────────────────────────────────────────────────────

    async def cleanup(self, ctx: ExecutionContext) -> None:
        try:
            from app.execution import process_mgr
            await process_mgr.kill(ctx.project_id)
        except Exception:
            pass


# ── Helpers ───────────────────────────────────────────────────────────────────

def _find_entry(ws: Path) -> str | None:
    for name in _ENTRY_CANDIDATES:
        if (ws / name).exists():
            return name
    py_files = list(ws.glob("*.py"))
    if py_files:
        return py_files[0].name
    return None


def _is_server_project(ws: Path) -> bool:
    req = ws / "requirements.txt"
    if req.exists():
        try:
            content = req.read_text().lower()
            for fw in _SERVER_FRAMEWORKS:
                if fw in content:
                    return True
        except Exception:
            pass
    return False


def _run_version(py: str) -> str:
    try:
        r = subprocess.run([py, "--version"], capture_output=True, text=True, timeout=5)
        return (r.stdout or r.stderr).strip()
    except Exception:
        return "unknown"
