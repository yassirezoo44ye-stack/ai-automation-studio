"""
DockerRuntime — Docker-based execution.

This runtime handles projects that ship a Dockerfile.  The image is
built per-execution (`docker build -t studio-exec-<id> .`), run as a
detached container with the allocated host port mapped in, and the
container + image are removed on cleanup.

Detection:
  - Dockerfile or docker-compose.yml present in workspace root

When launched, emits UnsupportedRuntime unless DOCKER_ENABLED=true
in the environment (opt-in gate for when the host has Docker).
Compose-only projects (no Dockerfile) are not orchestrated yet and
also emit UnsupportedRuntime.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import socket
import subprocess
import time
from pathlib import Path

from app.execution.platform.errors import install_failed, port_exhausted, unsupported_runtime
from app.execution.platform.events import (
    ExecutionFailed,
    InstallCompleted,
    InstallFailed,
    InstallProgress,
    InstallStarted,
    LogLine,
    ServerReady,
    ServerStarting,
    StatusUpdate,
    UnsupportedRuntime,
)
from app.execution.platform.runtimes.abstract import AbstractRuntime, ExecutionContext

log = logging.getLogger(__name__)

_DOCKER_ENABLED = os.getenv("DOCKER_ENABLED", "false").lower() == "true"

_BUILD_TIMEOUT  = 600
_RUN_TIMEOUT    = 60
_LAUNCH_TIMEOUT = 30

_UNSAFE_ID_RE = re.compile(r"[^a-z0-9_.-]+")
_EXPOSE_RE    = re.compile(r"^\s*EXPOSE\s+(\d+)", re.IGNORECASE | re.MULTILINE)


class DockerRuntime(AbstractRuntime):
    name     = "docker"
    priority = 30

    def detect(self, workspace: Path) -> bool:
        return (
            (workspace / "Dockerfile").exists()
            or (workspace / "docker-compose.yml").exists()
            or (workspace / "docker-compose.yaml").exists()
        )

    async def probe(self, ctx: ExecutionContext) -> None:
        if not _DOCKER_ENABLED:
            ctx.emit(UnsupportedRuntime(
                execution_id   = ctx.execution_id,
                project_type   = "docker",
                reason         = "Docker execution is disabled on this host",
                local_run_hint = "docker compose up",
                fix            = ["Download the ZIP and run: docker compose up"],
            ))
            raise unsupported_runtime("docker", "DOCKER_ENABLED is not set")

        docker_bin = shutil.which("docker")
        if not docker_bin:
            ctx.emit(UnsupportedRuntime(
                execution_id   = ctx.execution_id,
                project_type   = "docker",
                reason         = "docker binary not found on PATH",
                local_run_hint = "docker compose up",
            ))
            raise unsupported_runtime("docker", "docker binary not found")

        if not (_workspace(ctx) / "Dockerfile").exists():
            ctx.emit(UnsupportedRuntime(
                execution_id   = ctx.execution_id,
                project_type   = "docker",
                reason         = "compose-only projects are not supported yet — a Dockerfile is required",
                local_run_hint = "docker compose up",
                fix            = ["Download the ZIP and run: docker compose up"],
            ))
            raise unsupported_runtime("docker", "no Dockerfile (compose-only project)")

        ctx.emit(StatusUpdate(
            execution_id = ctx.execution_id,
            message      = "Docker runtime detected",
            phase        = "probe",
        ))

    async def install(self, ctx: ExecutionContext) -> None:
        ws    = _workspace(ctx)
        image = _image_tag(ctx.execution_id)
        cmd   = ["docker", "build", "-t", image, "."]

        ctx.emit(InstallStarted(
            execution_id = ctx.execution_id,
            pm           = "docker",
            command      = " ".join(cmd),
        ))

        started = time.time()
        rc, stdout, stderr = await _run_docker(cmd, ws, _BUILD_TIMEOUT)

        for line in stdout:
            ctx.emit(InstallProgress(execution_id=ctx.execution_id, stream="stdout", line=line))
        for line in stderr:
            ctx.emit(InstallProgress(execution_id=ctx.execution_id, stream="stderr", line=line))

        if rc != 0:
            ctx.emit(InstallFailed(
                execution_id = ctx.execution_id,
                error_code   = "DEP_INSTALL_FAILED",
                message      = f"docker build exited with code {rc}",
                exit_code    = rc,
            ))
            raise install_failed(rc, "docker build", stderr)

        ctx.emit(InstallCompleted(
            execution_id = ctx.execution_id,
            duration_s   = round(time.time() - started, 3),
        ))

    async def build(self, ctx: ExecutionContext) -> None:
        pass  # build is part of docker build

    async def launch(self, ctx: ExecutionContext) -> None:
        from app.execution.process_mgr import allocate_port

        ws        = _workspace(ctx)
        image     = _image_tag(ctx.execution_id)
        container = _container_name(ctx.execution_id)

        port = allocate_port()
        if not port:
            raise port_exhausted()
        ctx.port = port

        container_port = _exposed_port(ws) or port
        cmd = [
            "docker", "run", "-d",
            "--name", container,
            "-p", f"{port}:{container_port}",
            "-e", f"PORT={container_port}",
            image,
        ]

        ctx.emit(ServerStarting(
            execution_id = ctx.execution_id,
            command      = " ".join(cmd),
            port         = port,
        ))

        rc, _stdout, stderr = await _run_docker(cmd, ws, _RUN_TIMEOUT)
        if rc != 0:
            for line in stderr:
                ctx.emit(LogLine(execution_id=ctx.execution_id, stream="stderr", line=line, phase="launch"))
            ctx.emit(ExecutionFailed(
                execution_id = ctx.execution_id,
                error_code   = "LAUNCH_CRASH",
                message      = f"docker run exited with code {rc}",
            ))
            return

        deadline = time.time() + _LAUNCH_TIMEOUT
        while time.time() < deadline:
            if not await _container_running(container, ws):
                for line in await _container_logs(container, ws):
                    ctx.emit(LogLine(execution_id=ctx.execution_id, line=line, phase="launch"))
                ctx.emit(ExecutionFailed(
                    execution_id = ctx.execution_id,
                    error_code   = "LAUNCH_CRASH",
                    message      = "Container exited before binding its port",
                ))
                return
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                    break
            except OSError:
                await asyncio.sleep(0.5)
        else:
            await _run_docker(["docker", "rm", "-f", container], ws, _RUN_TIMEOUT)
            ctx.emit(ExecutionFailed(
                execution_id = ctx.execution_id,
                error_code   = "LAUNCH_TIMEOUT",
                message      = f"Container did not bind port {port} within {_LAUNCH_TIMEOUT}s",
            ))
            return

        preview_url = f"http://localhost:{port}"
        ctx.preview_url        = preview_url
        ctx.report.port        = port
        ctx.report.preview_url = preview_url

        ctx.emit(ServerReady(
            execution_id = ctx.execution_id,
            preview_url  = preview_url,
            port         = port,
            command      = " ".join(cmd),
            project_type = "docker",
        ))

    async def cleanup(self, ctx: ExecutionContext) -> None:
        if not _DOCKER_ENABLED or not shutil.which("docker"):
            return
        container = _container_name(ctx.execution_id)
        image     = _image_tag(ctx.execution_id)
        for cmd in (["docker", "rm", "-f", container], ["docker", "rmi", "-f", image]):
            try:
                await _run_docker(cmd, ctx.workspace, _RUN_TIMEOUT)
            except Exception:
                log.warning("docker cleanup command failed: %s", " ".join(cmd), exc_info=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _workspace(ctx: ExecutionContext) -> Path:
    return ctx.sandbox.paths.workspace if ctx.sandbox.paths else ctx.workspace


def _slug(execution_id: str) -> str:
    return _UNSAFE_ID_RE.sub("-", execution_id.lower()).strip("-.") or "exec"


def _image_tag(execution_id: str) -> str:
    return f"studio-exec-{_slug(execution_id)}"


def _container_name(execution_id: str) -> str:
    return f"studio-exec-{_slug(execution_id)}"


def _exposed_port(ws: Path) -> int | None:
    try:
        m = _EXPOSE_RE.search((ws / "Dockerfile").read_text(encoding="utf-8"))
        return int(m.group(1)) if m else None
    except Exception:
        return None


async def _run_docker(cmd: list[str], cwd: Path, timeout: int) -> tuple[int, list[str], list[str]]:
    """Run a docker CLI command off the event loop; never raises."""
    loop = asyncio.get_event_loop()

    def _run():
        try:
            proc = subprocess.Popen(
                cmd, cwd=str(cwd),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True,
            )
            try:
                out, err = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                return -1, [], [f"{' '.join(cmd[:2])} timed out after {timeout}s"]
            return proc.returncode, out.splitlines(), err.splitlines()
        except Exception as exc:
            return -1, [], [str(exc)]

    return await loop.run_in_executor(None, _run)


async def _container_running(container: str, cwd: Path) -> bool:
    rc, stdout, _ = await _run_docker(
        ["docker", "inspect", "-f", "{{.State.Running}}", container], cwd, _RUN_TIMEOUT,
    )
    return rc == 0 and bool(stdout) and stdout[0].strip() == "true"


async def _container_logs(container: str, cwd: Path, tail: int = 20) -> list[str]:
    _, stdout, stderr = await _run_docker(
        ["docker", "logs", "--tail", str(tail), container], cwd, _RUN_TIMEOUT,
    )
    return stdout + stderr
