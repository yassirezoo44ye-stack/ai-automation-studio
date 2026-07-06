"""
js_runtime — Universal JavaScript Runtime Execution Layer.

Public surface:

    from app.execution.js_runtime import runtime_manager, PhaseRunner
    from app.execution.js_runtime import RuntimeReport, RuntimeErrorCode

    # Phased execution (preferred — used by node.py driver):
    runner = PhaseRunner(project_id, ws, info)
    async for event_type, payload in runner.run():
        yield _ev(event_type, **payload)

    # Direct manager access (for install/script utilities):
    manager = runtime_manager
    async for stream, line, sentinel in manager.install(ws): ...
    argv = manager.server_argv(ws, port=8100)

Error codes (all in RuntimeErrorCode enum):
    ENV_NODE_MISSING  ENV_PM_MISSING  ENV_PM_BROKEN  ENV_TMP_NOT_WRITABLE
    DEP_PKG_JSON_MISSING  DEP_INSTALL_EACCES  DEP_INSTALL_ERESOLVE  ...
    EXEC_SCRIPT_MISSING  EXEC_SERVER_TIMEOUT  EXEC_SERVER_CRASH  ...
"""
from .error_codes import RuntimeErrorCode, classify_install_error, fixes_for, message_for
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
from .probe import EnvironmentProbe, ProbeResult
from .report import DependencyReport, EnvironmentReport, LaunchReport, RuntimeReport
from .resolver import ScriptResolver
from .validator import ValidationReport, WorkspaceValidator

__all__ = [
    # Phased execution
    "PhaseRunner",
    # Reports
    "RuntimeReport",
    "EnvironmentReport",
    "DependencyReport",
    "LaunchReport",
    # Error codes
    "RuntimeErrorCode",
    "classify_install_error",
    "fixes_for",
    "message_for",
    # Manager singleton
    "runtime_manager",
    "RuntimeManager",
    "InstallResult",
    # Detection
    "PackageManagerDetector",
    "DetectionResult",
    # Other utilities
    "ScriptResolver",
    "WorkspaceValidator",
    "ValidationReport",
    "EnvironmentProbe",
    "ProbeResult",
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
