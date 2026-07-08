"""
DockerRuntime — scaffold for Docker-based execution.

This runtime handles projects that ship a Dockerfile.  It is a
scaffold: detection and validation are implemented; actual container
orchestration is stubbed with extension points marked TODO.

Detection:
  - Dockerfile or docker-compose.yml present in workspace root

When launched, emits UnsupportedRuntime unless DOCKER_ENABLED=true
in the environment (opt-in gate for when the host has Docker).
"""
from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

from app.execution.platform.errors import unsupported_runtime
from app.execution.platform.events import LogLine, StatusUpdate, UnsupportedRuntime
from app.execution.platform.runtimes.abstract import AbstractRuntime, ExecutionContext

log = logging.getLogger(__name__)

_DOCKER_ENABLED = os.getenv("DOCKER_ENABLED", "false").lower() == "true"


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

        ctx.emit(StatusUpdate(
            execution_id = ctx.execution_id,
            message      = "Docker runtime detected — container build not yet implemented",
            phase        = "probe",
        ))

    async def install(self, ctx: ExecutionContext) -> None:
        # TODO: docker build -t <image> .
        ctx.emit(LogLine(
            execution_id = ctx.execution_id,
            line         = "docker build — not yet implemented",
            phase        = "install",
        ))

    async def build(self, ctx: ExecutionContext) -> None:
        pass  # build is part of docker build

    async def launch(self, ctx: ExecutionContext) -> None:
        # TODO: docker run -p <port>:<port> <image>
        ctx.emit(LogLine(
            execution_id = ctx.execution_id,
            line         = "docker run — not yet implemented",
            phase        = "launch",
        ))

    async def cleanup(self, ctx: ExecutionContext) -> None:
        # TODO: docker rm -f <container_id>
        pass
