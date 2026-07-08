"""
UnifiedExecutionEngine — Phase 1 of the Execution Platform.

Single orchestrator replacing the ad-hoc driver chain in runner.py.

Lifecycle:
  1. Validate workspace
  2. Select runtime (via RuntimeRegistry)
  3. Create ExecutionSandbox
  4. Create ExecutionContext + ExecutionMetrics + ExecutionReport + ArtifactSystem
  5. Runtime.probe()
  6. Runtime.install()
  7. Runtime.build()  (if supported)
  8. Runtime.launch()
  9. Runtime.cleanup()
  10. Collect artifacts
  11. Emit ExecutionReport

The engine emits TypedEvent objects.  Callers receive them by passing
an emit() callback or by iterating the async generator returned by
engine.run().

Thread safety: each call to run() is independent — the engine creates
fresh objects per execution.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import AsyncIterator, Callable, Optional
from uuid import uuid4

from app.execution.platform.artifacts import ArtifactSystem
from app.execution.platform.errors import PlatformError, internal, unsupported_runtime, workspace_missing
from app.execution.platform.events import (
    CleanupFinished,
    CleanupStarted,
    ExecutionFailed,
    ExecutionFinished,
    ExecutionReport as ExecutionReportEvent,
    ExecutionStarted,
    Heartbeat,
    TypedEvent,
)
from app.execution.platform.metrics import ExecutionMetrics
from app.execution.platform.report import ExecutionReport
from app.execution.platform.runtimes.abstract import ExecutionContext
from app.execution.platform.runtimes.registry import RuntimeRegistry, get_registry
from app.execution.platform.sandbox import ExecutionSandbox

log = logging.getLogger(__name__)

_HEARTBEAT_INTERVAL = 10.0  # seconds


class UnifiedExecutionEngine:
    """
    Orchestrates a full project execution lifecycle.

    Usage (async generator):

        engine = UnifiedExecutionEngine()
        async for event in engine.run(workspace, project_id=project_id):
            sse_dict = event.to_sse_dict()
            yield f"data: {json.dumps(sse_dict)}\n\n"

    Usage (callback):

        def on_event(event: TypedEvent) -> None:
            ...
        await engine.run_with_callback(workspace, on_event)
    """

    def __init__(self, registry: Optional[RuntimeRegistry] = None) -> None:
        self._registry = registry or get_registry()

    async def run(
        self,
        workspace: Path,
        project_id: str = "",
        execution_id: Optional[str] = None,
        options: dict | None = None,
    ) -> AsyncIterator[TypedEvent]:
        """
        Async generator: yields TypedEvent objects for the entire lifecycle.
        Heartbeats are injected every 10 seconds to keep SSE connections alive.
        """
        execution_id = execution_id or str(uuid4())[:16]
        queue: asyncio.Queue[TypedEvent] = asyncio.Queue()
        done  = asyncio.Event()

        def emit(event: TypedEvent) -> None:
            queue.put_nowait(event)

        async def _worker():
            try:
                await self._execute(workspace, project_id, execution_id, emit, options)
            finally:
                done.set()

        task = asyncio.ensure_future(_worker())

        heartbeat_ts = time.time()

        while not done.is_set() or not queue.empty():
            try:
                event = queue.get_nowait()
                yield event
                heartbeat_ts = time.time()
            except asyncio.QueueEmpty:
                if time.time() - heartbeat_ts >= _HEARTBEAT_INTERVAL:
                    yield Heartbeat(execution_id=execution_id)
                    heartbeat_ts = time.time()
                await asyncio.sleep(0.05)

        # Drain any remaining events
        while not queue.empty():
            yield queue.get_nowait()

        if task.exception():
            log.error("engine worker raised: %s", task.exception())

    async def _execute(
        self,
        workspace: Path,
        project_id: str,
        execution_id: str,
        emit: Callable[[TypedEvent], None],
        options: dict | None,
    ) -> None:
        """Internal: run the full lifecycle, always calling cleanup."""
        started_at = time.time()
        report     = ExecutionReport(execution_id=execution_id, project_id=project_id)
        metrics    = ExecutionMetrics(execution_id=execution_id, project_id=project_id)
        artifacts  = ArtifactSystem(execution_id)
        sandbox    = ExecutionSandbox(workspace, execution_id)
        runtime    = None

        # ── Workspace validation ──────────────────────────────────────────────
        if not workspace.exists():
            err = workspace_missing(str(workspace))
            emit(ExecutionFailed(
                execution_id   = execution_id,
                error_code     = err.code,
                category       = err.category.value,
                message        = err.message,
                fix            = err.fix,
            ))
            report.finish(success=False, error_code=err.code, error_message=err.message)
            emit(ExecutionReportEvent(execution_id=execution_id, report=report.to_dict()))
            return

        # ── Runtime selection ─────────────────────────────────────────────────
        runtime = self._registry.select(workspace)
        if not runtime:
            err = unsupported_runtime("unknown", "no runtime matched the workspace")
            emit(ExecutionFailed(
                execution_id = execution_id,
                error_code   = err.code,
                category     = err.category.value,
                message      = err.message,
                fix          = err.fix,
            ))
            report.finish(success=False, error_code=err.code, error_message=err.message)
            emit(ExecutionReportEvent(execution_id=execution_id, report=report.to_dict()))
            return

        report.runtime = runtime.name
        metrics.runtime = runtime.name
        artifacts.init()

        emit(ExecutionStarted(
            execution_id = execution_id,
            project_id   = project_id,
            runtime      = runtime.name,
            workspace    = str(workspace),
        ))

        # ── Sandbox creation ──────────────────────────────────────────────────
        try:
            sandbox.create()
        except Exception as exc:
            err = internal(str(exc))
            emit(ExecutionFailed(
                execution_id = execution_id,
                error_code   = err.code,
                message      = err.message,
            ))
            report.finish(success=False, error_code=err.code, error_message=err.message)
            emit(ExecutionReportEvent(execution_id=execution_id, report=report.to_dict()))
            return

        # ── Build ExecutionContext ────────────────────────────────────────────
        ctx = ExecutionContext(
            execution_id = execution_id,
            project_id   = project_id,
            workspace    = workspace,
            sandbox      = sandbox,
            metrics      = metrics,
            report       = report,
            artifacts    = artifacts,
            emit         = emit,
            options      = options,
        )

        # ── Run lifecycle phases ─────────────────────────────────────────────
        phase_error: Optional[PlatformError] = None
        try:
            pm = metrics.start_phase("probe")
            await runtime.probe(ctx)
            metrics.end_phase(pm, success=True)

            pm = metrics.start_phase("install")
            await runtime.install(ctx)
            metrics.end_phase(pm, success=True)

            if runtime.supports_build():
                pm = metrics.start_phase("build")
                await runtime.build(ctx)
                metrics.end_phase(pm, success=True)

            pm = metrics.start_phase("launch")
            await runtime.launch(ctx)
            metrics.end_phase(pm, success=True)

        except PlatformError as exc:
            phase_error = exc
            metrics.end_phase(pm, success=False, error_code=exc.code)
            emit(ExecutionFailed(
                execution_id   = execution_id,
                error_code     = exc.code,
                category       = exc.category.value,
                message        = exc.message,
                technical_cause= exc.technical_cause,
                fix            = exc.fix,
                recoverable    = exc.recoverable,
            ))
        except Exception as exc:
            err = internal(str(exc))
            phase_error = err
            emit(ExecutionFailed(
                execution_id = execution_id,
                error_code   = err.code,
                message      = err.message,
                technical_cause = str(exc),
            ))

        # ── Cleanup (always) ─────────────────────────────────────────────────
        emit(CleanupStarted(execution_id=execution_id))
        try:
            await runtime.cleanup(ctx)
        except Exception:
            pass
        freed = sandbox.cleanup()
        emit(CleanupFinished(execution_id=execution_id, freed_bytes=freed))

        # ── Finish metrics + report ───────────────────────────────────────────
        success = phase_error is None
        metrics.finish(success=success, error_code=phase_error.code if phase_error else None)

        report.phases       = [p.to_dict() for p in metrics.phases]
        report.artifact_count = artifacts.count()
        report.artifacts    = [a.to_dict() for a in artifacts.all()]

        if phase_error:
            report.finish(
                success        = False,
                error_code     = phase_error.code,
                error_category = phase_error.category.value,
                error_message  = phase_error.message,
                error_fix      = phase_error.fix,
            )
        else:
            report.finish(success=True)

        # Write report artifact
        try:
            artifacts.add_bytes("report", "report.json",
                                json.dumps(report.to_dict(), indent=2).encode())
        except Exception:
            pass
        artifacts.save_index()

        total = round(time.time() - started_at, 2)
        emit(ExecutionFinished(
            execution_id  = execution_id,
            success       = success,
            duration_s    = total,
            exit_code     = report.exit_code,
            artifact_count= artifacts.count(),
        ))
        emit(ExecutionReportEvent(execution_id=execution_id, report=report.to_dict()))
