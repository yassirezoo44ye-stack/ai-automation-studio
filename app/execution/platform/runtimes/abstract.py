"""
AbstractRuntime — Phase 2 of the Execution Platform.

All runtime adapters (Node, Python, Docker, Electron) implement this
protocol.  The UnifiedExecutionEngine talks only to this interface.

Protocol methods:

    detect(ws)      → bool   — can this runtime handle the given workspace?
    probe(ctx)      → None   — gather env facts (node version, pm, …)
    install(ctx)    → None   — install dependencies
    build(ctx)      → None   — compile / bundle (build projects only)
    launch(ctx)     → None   — start server / serve static HTML
    cleanup(ctx)    → None   — teardown (kill process, remove sandbox)

Each method emits TypedEvents into ctx.emit().
Each method raises PlatformError on non-recoverable failure.

ExecutionContext carries everything a runtime needs across all phases:
  - The resolved workspace path
  - The ArtifactSystem for this execution
  - The ExecutionMetrics recorder
  - The ExecutionReport (mutated in-place)
  - The emit() coroutine for SSE events
  - The ExecutionSandbox (created by the engine before calling the runtime)
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from app.execution.platform.artifacts import ArtifactSystem
    from app.execution.platform.events import TypedEvent
    from app.execution.platform.metrics import ExecutionMetrics
    from app.execution.platform.report import ExecutionReport
    from app.execution.platform.sandbox import ExecutionSandbox


class ExecutionContext:
    """
    Shared execution context passed to every runtime method.

    The engine creates one context per execution and passes it to all
    runtime phase calls.  Runtimes read from it and write to report.
    """

    def __init__(
        self,
        *,
        execution_id: str,
        project_id: str,
        workspace: Path,
        sandbox: "ExecutionSandbox",
        metrics: "ExecutionMetrics",
        report: "ExecutionReport",
        artifacts: "ArtifactSystem",
        emit: Callable[["TypedEvent"], None],
        options: dict | None = None,
    ) -> None:
        self.execution_id = execution_id
        self.project_id   = project_id
        self.workspace    = workspace
        self.sandbox      = sandbox
        self.metrics      = metrics
        self.report       = report
        self.artifacts    = artifacts
        self.emit         = emit          # emit(event) → queues event for SSE stream
        self.options      = options or {}

        # Mutable state set by runtime phases
        self.node_version: str | None = None
        self.python_version: str = ""
        self.pm_name: str = ""
        self.pm_version: str = ""
        self.port: int = 0
        self.pid: int | None = None
        self.preview_url: str = ""


class AbstractRuntime(ABC):
    """
    Protocol all runtime adapters must implement.

    A runtime adapter is selected by the RuntimeRegistry based on
    what it returns from detect().  The engine then calls probe →
    install → build → launch in sequence.
    """

    #: Human-readable name — shown in logs and events ("node", "python", …)
    name: str = "abstract"

    #: Priority — lower wins when multiple runtimes match a workspace
    priority: int = 100

    @abstractmethod
    def detect(self, workspace: Path) -> bool:
        """
        Return True if this runtime can handle the given workspace.
        Must be fast and side-effect free — it's called for every
        registered runtime during project detection.
        """

    @abstractmethod
    async def probe(self, ctx: ExecutionContext) -> None:
        """
        Gather environmental facts: runtime version, available tools, …
        Emit ProbeCompleted.  Raise EnvironmentError on hard failure.
        """

    @abstractmethod
    async def install(self, ctx: ExecutionContext) -> None:
        """
        Install project dependencies.
        Emit InstallStarted → InstallProgress* → InstallCompleted | InstallFailed.
        Raise DependencyError on failure.
        """

    @abstractmethod
    async def build(self, ctx: ExecutionContext) -> None:
        """
        Build / bundle the project (optional phase — skip if not applicable).
        Emit BuildStarted → BuildProgress* → BuildCompleted | BuildFailed.
        Raise BuildError on failure.
        """

    @abstractmethod
    async def launch(self, ctx: ExecutionContext) -> None:
        """
        Start the server or render static output.
        Emit ServerStarting → ServerReady | ExecutionFailed.
        Raise LaunchError or RuntimeError_ on failure.
        """

    @abstractmethod
    async def cleanup(self, ctx: ExecutionContext) -> None:
        """
        Kill processes and clean up any runtime-owned resources.
        Always called — even after a failure.  Must not raise.
        """

    def supports_build(self) -> bool:
        """Return True if this runtime uses the build() phase."""
        return False

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} priority={self.priority}>"
