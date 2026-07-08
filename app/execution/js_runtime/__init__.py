"""
js_runtime — Production-grade, self-diagnosing JavaScript execution layer.

Public surface:

    from app.execution.js_runtime import PhaseRunner, BuildPlan
    from app.execution.js_runtime import RuntimeReport, RuntimeErrorCode

    # Phased execution (preferred — used by node.py driver):
    runner = PhaseRunner(project_id, ws, info)
    async for event_type, payload in runner.run():
        yield f"data: {json.dumps({'type': event_type, **payload})}\n\n"

    # Build plan inspection:
    plan = BuildPlan(project_id="x", workspace="/tmp/ws")
    errors = plan.validate()   # [] = safe, non-empty = abort

    # Direct manager access (for install/script utilities):
    manager = runtime_manager
    async for stream, line, sentinel in manager.install(ws): ...
    argv = manager.server_argv(ws, port=8100)

Error codes (all in RuntimeErrorCode enum):
    Phase A (environment):
      ENV_NODE_MISSING  ENV_PM_MISSING  ENV_PM_BROKEN
      ENV_TMP_NOT_WRITABLE  ENV_INVALID_WORKSPACE

    Phase B (dependencies):
      DEP_PKG_JSON_MISSING  DEP_PKG_JSON_INVALID  DEP_LOCKFILE_MISSING
      DEP_INSTALL_FAILED  DEP_INSTALL_EACCES  DEP_INSTALL_ERESOLVE
      DEP_INSTALL_ENOTFOUND  DEP_INSTALL_ETARGET  DEP_INSTALL_ENGINE
      DEP_INSTALL_TIMEOUT  DEP_EXTERNAL_SERVICE

    Phase C (execution):
      EXEC_SCRIPT_MISSING  EXEC_SERVER_TIMEOUT  EXEC_SERVER_CRASH
      EXEC_PORT_UNAVAILABLE  EXEC_BUILD_FAILED

JS-prefixed aliases (JS001–JS010) map to the above via js_code_for().
"""
from .build_plan import BuildPlan
from .error_codes import (
    RuntimeErrorCode,
    classify_install_error,
    fixes_for,
    from_js_code,
    js_code_for,
    message_for,
)
from .errors import (
    ExecutionFailed,
    ExecutionTimeout,
    JsRuntimeError,
    LockfileConflict,
    NodeModulesMissing,
    PackageJsonMissing,
    PackageManagerBroken,
    PackageManagerNotFound,
    RuntimeUnavailable,
    ScriptNotFound,
)
from .manager import InstallResult, RuntimeManager, runtime_manager
from .detector import DetectionResult, PackageManagerDetector
from .phases import PhaseRunner
from .probe import EnvironmentProbe, ProbeResult, SystemProbe, SystemProbeResult
from .report import (
    BuildPlanReport,
    DependencyReport,
    EnvironmentReport,
    LaunchReport,
    RuntimeReport,
)
from .resolver import ScriptResolver
from .validator import ValidationReport, WorkspaceValidator

__all__ = [
    # Core execution
    "PhaseRunner",
    "BuildPlan",
    # Reports
    "RuntimeReport",
    "BuildPlanReport",
    "EnvironmentReport",
    "DependencyReport",
    "LaunchReport",
    # Error codes + utilities
    "RuntimeErrorCode",
    "classify_install_error",
    "fixes_for",
    "message_for",
    "js_code_for",
    "from_js_code",
    # Manager singleton
    "runtime_manager",
    "RuntimeManager",
    "InstallResult",
    # Detection
    "PackageManagerDetector",
    "DetectionResult",
    # Probes
    "SystemProbe",
    "SystemProbeResult",
    "EnvironmentProbe",
    "ProbeResult",
    # Other utilities
    "ScriptResolver",
    "WorkspaceValidator",
    "ValidationReport",
    # Legacy error classes
    "JsRuntimeError",
    "PackageManagerNotFound",
    "PackageManagerBroken",
    "ScriptNotFound",
    "PackageJsonMissing",
    "NodeModulesMissing",
    "RuntimeUnavailable",
    "ExecutionTimeout",
    "ExecutionFailed",
    "LockfileConflict",
]
