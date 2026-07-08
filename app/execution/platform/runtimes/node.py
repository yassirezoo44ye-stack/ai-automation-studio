"""
NodeRuntime — wraps the existing js_runtime PhaseRunner.

Adapts the PhaseRunner's generator-based SSE output into the
ExecutionContext emit() interface used by UnifiedExecutionEngine.

Detection criteria (in order):
  1. package.json exists in workspace root
  2. *.js / *.ts / *.jsx / *.tsx files present
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from app.execution.platform.errors import (
    DependencyError as DepErr,
    LaunchError,
    internal,
    pm_missing,
    pkg_json_missing,
)
from app.execution.platform.events import (
    ExecutionFailed,
    InstallCompleted,
    InstallFailed,
    InstallStarted,
    LogLine,
    ProbeCompleted,
    ServerReady,
    ServerStarting,
    StatusUpdate,
)
from app.execution.platform.runtimes.abstract import AbstractRuntime, ExecutionContext

if TYPE_CHECKING:
    pass

log = logging.getLogger(__name__)


class NodeRuntime(AbstractRuntime):
    name     = "node"
    priority = 10

    # ── Detection ────────────────────────────────────────────────────────────

    def detect(self, workspace: Path) -> bool:
        if (workspace / "package.json").exists():
            return True
        js_files = (
            list(workspace.glob("*.js"))
            + list(workspace.glob("*.ts"))
            + list(workspace.glob("*.jsx"))
            + list(workspace.glob("*.tsx"))
        )
        return len(js_files) > 0

    # ── Probe ────────────────────────────────────────────────────────────────

    async def probe(self, ctx: ExecutionContext) -> None:
        from app.execution.js_runtime.probe import SystemProbe
        probe = SystemProbe()
        result = probe.run(ctx.workspace)

        ctx.node_version   = result.node_version
        ctx.python_version = result.python_version

        ctx.report.node_version   = result.node_version
        ctx.report.python_version = result.python_version
        ctx.report.os_name        = result.os_name
        ctx.report.architecture   = result.architecture
        ctx.report.disk_free_mb   = result.disk_free_mb
        ctx.report.memory_free_mb = result.memory_free_mb

        ctx.emit(ProbeCompleted(
            execution_id      = ctx.execution_id,
            os_name           = result.os_name,
            architecture      = result.architecture,
            node_version      = result.node_version,
            python_version    = result.python_version,
            available_runtimes= list(result.available_pms.keys()),
            disk_free_mb      = result.disk_free_mb,
            memory_free_mb    = result.memory_free_mb,
            warnings          = result.warnings,
        ))

    # ── Install ──────────────────────────────────────────────────────────────

    async def install(self, ctx: ExecutionContext) -> None:
        from app.execution.js_runtime.phases import PhaseRunner

        ws = ctx.sandbox.paths.workspace if ctx.sandbox.paths else ctx.workspace

        runner = PhaseRunner(str(ws), ctx.execution_id)

        # Collect install events from the existing PhaseRunner
        # PhaseRunner.run() is a sync generator that yields dicts.
        # We run it in a thread to avoid blocking the event loop.
        loop = asyncio.get_event_loop()

        def _stream_install():
            events = []
            try:
                for ev_dict in runner._phase_b_iter():
                    events.append(ev_dict)
            except Exception as exc:
                events.append({"type": "error", "text": str(exc)})
            return events

        try:
            ev_list = await loop.run_in_executor(None, _stream_install)
        except Exception as exc:
            raise internal(str(exc)) from exc

        error_seen = False
        for ev in ev_list:
            t = ev.get("type", "")
            if t in ("log", "stdout", "stderr"):
                ctx.emit(LogLine(
                    execution_id = ctx.execution_id,
                    stream       = ev.get("stream", "stdout"),
                    line         = ev.get("text", ev.get("line", "")),
                    phase        = "install",
                ))
            elif t == "error":
                error_seen = True
                ctx.emit(InstallFailed(
                    execution_id = ctx.execution_id,
                    error_code   = ev.get("code", "DEP_INSTALL_FAILED"),
                    message      = ev.get("text", "install failed"),
                    exit_code    = ev.get("exit_code", 1),
                ))

        if not error_seen:
            ctx.emit(InstallCompleted(
                execution_id = ctx.execution_id,
                duration_s   = 0.0,
            ))

    # ── Build ────────────────────────────────────────────────────────────────

    async def build(self, ctx: ExecutionContext) -> None:
        # Build is handled inside the existing PhaseRunner.launch()
        # when project type is a build project.  We delegate to launch().
        pass

    def supports_build(self) -> bool:
        return True

    # ── Launch ───────────────────────────────────────────────────────────────

    async def launch(self, ctx: ExecutionContext) -> None:
        from app.execution.js_runtime.phases import PhaseRunner

        ws = ctx.sandbox.paths.workspace if ctx.sandbox.paths else ctx.workspace
        runner = PhaseRunner(str(ws), ctx.execution_id)

        loop = asyncio.get_event_loop()

        server_ready_info: dict = {}

        def _stream_launch():
            events = []
            try:
                for ev_dict in runner._phase_c_iter():
                    events.append(ev_dict)
            except Exception as exc:
                events.append({"type": "error", "text": str(exc)})
            return events

        try:
            ev_list = await loop.run_in_executor(None, _stream_launch)
        except Exception as exc:
            raise internal(str(exc)) from exc

        for ev in ev_list:
            t = ev.get("type", "")
            if t == "server_ready":
                ctx.port        = ev.get("port", 0)
                ctx.preview_url = ev.get("preview_url", "")
                ctx.pid         = ev.get("pid")
                ctx.report.port        = ctx.port
                ctx.report.preview_url = ctx.preview_url
                ctx.report.pid         = ctx.pid
                ctx.emit(ServerReady(
                    execution_id        = ctx.execution_id,
                    preview_url         = ctx.preview_url,
                    port                = ctx.port,
                    command             = ev.get("command", ""),
                    project_type        = ev.get("project_type", ""),
                    message             = ev.get("message", "Server is running"),
                ))
            elif t in ("log", "stdout", "stderr"):
                ctx.emit(LogLine(
                    execution_id = ctx.execution_id,
                    stream       = ev.get("stream", "stdout"),
                    line         = ev.get("text", ev.get("line", "")),
                    phase        = "launch",
                ))
            elif t == "error":
                ctx.emit(ExecutionFailed(
                    execution_id   = ctx.execution_id,
                    error_code     = ev.get("code", "LAUNCH_CRASH"),
                    message        = ev.get("text", "Launch failed"),
                ))
            elif t in ("html", "build_complete"):
                # Re-emit verbatim for build projects
                ctx.emit(StatusUpdate(
                    execution_id = ctx.execution_id,
                    message      = ev.get("text", "Build complete"),
                    phase        = "build",
                ))

    # ── Cleanup ──────────────────────────────────────────────────────────────

    async def cleanup(self, ctx: ExecutionContext) -> None:
        try:
            from app.execution import process_mgr
            await process_mgr.kill(ctx.project_id)
        except Exception:
            pass
