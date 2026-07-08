"""
Execution Platform — production-grade cloud-native execution subsystem.

Public surface:
    UnifiedExecutionEngine  — the core orchestrator
    ExecutionContext         — passed to all runtime adapters
    RuntimeRegistry         — plugin-based runtime selection
    BuildCache              — content-addressed caching
    ArtifactSystem          — versioned artifact storage
    ExecutionSandbox        — per-execution isolation
    ExecutionMetrics        — timing and resource tracking
    ExecutionReport         — canonical execution record
    TypedEvent + subclasses — structured SSE events
    PlatformError + subclasses — unified error hierarchy
"""
from app.execution.platform.engine      import UnifiedExecutionEngine
from app.execution.platform.sandbox     import ExecutionSandbox
from app.execution.platform.cache       import BuildCache, get_cache
from app.execution.platform.artifacts   import ArtifactSystem
from app.execution.platform.metrics     import ExecutionMetrics, PhaseMetrics
from app.execution.platform.report      import ExecutionReport
from app.execution.platform.events      import (
    TypedEvent, ExecutionStarted, ProbeCompleted, ValidationPassed,
    ValidationFailed, BuildPlanGenerated, InstallStarted, InstallProgress,
    InstallCompleted, InstallFailed, BuildStarted, BuildProgress,
    BuildCompleted, BuildFailed, ServerStarting, ServerReady,
    HealthCheckPassed, ArtifactCollected, ExecutionFailed, ExecutionFinished,
    CleanupStarted, CleanupFinished, Heartbeat, LogLine, StatusUpdate,
    HtmlOutput, UnsupportedRuntime, ExecutionReport as ExecutionReportEvent,
    EVENT_REGISTRY,
)
from app.execution.platform.errors      import (
    PlatformError, ErrorCategory,
    EnvironmentError, ValidationError, DependencyError, BuildError,
    LaunchError, RuntimeError_, SandboxError, ArtifactError,
    NetworkError, TimeoutError_, InternalError,
)
from app.execution.platform.runtimes    import (
    AbstractRuntime, ExecutionContext,
    RuntimeRegistry, get_registry,
    NodeRuntime, PythonRuntime, DockerRuntime, ElectronRuntime,
)

__all__ = [
    "UnifiedExecutionEngine",
    "ExecutionContext", "ExecutionSandbox",
    "BuildCache", "get_cache",
    "ArtifactSystem",
    "ExecutionMetrics", "PhaseMetrics",
    "ExecutionReport",
    "TypedEvent", "EVENT_REGISTRY",
    "PlatformError", "ErrorCategory",
    "RuntimeRegistry", "get_registry",
    "AbstractRuntime",
    "NodeRuntime", "PythonRuntime", "DockerRuntime", "ElectronRuntime",
]
