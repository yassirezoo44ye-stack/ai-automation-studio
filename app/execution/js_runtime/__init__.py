"""
js_runtime — Universal JavaScript Runtime Execution Layer.

Public surface (everything else is an implementation detail):

    from app.execution.js_runtime import runtime_manager

    # Detection:
    result = runtime_manager.detect(ws)      # DetectionResult
    print(result.adapter.name)               # "npm" | "pnpm" | "yarn" | "bun" | "npm-cli"
    print(result.method)                     # "lockfile" | "probe" | "fallback" | ...
    print(result.evidence)                   # human-readable reason

    # Validation:
    report = runtime_manager.validate(ws, script="dev")
    if not report.ok:
        for issue in report.issues:
            print(issue)

    # Installation:
    ok, lines = await runtime_manager.install(ws)

    # Script execution:
    rc, stdout, stderr = await runtime_manager.run_script(ws, "build")

    # Server argv (for process_mgr):
    argv = runtime_manager.server_argv(ws, port=8100)

Errors (all subclass JsRuntimeError):
    PackageManagerNotFound  PackageManagerBroken  ScriptNotFound
    PackageJsonMissing      NodeModulesMissing    RuntimeUnavailable
    ExecutionTimeout        ExecutionFailed       LockfileConflict
"""
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
from .probe import EnvironmentProbe, ProbeResult
from .resolver import ScriptResolver
from .validator import ValidationReport, WorkspaceValidator

__all__ = [
    # Singleton (main entry point)
    "runtime_manager",
    # Classes
    "RuntimeManager",
    "InstallResult",
    "PackageManagerDetector",
    "ScriptResolver",
    "WorkspaceValidator",
    "EnvironmentProbe",
    "DetectionResult",
    "ValidationReport",
    "ProbeResult",
    # Errors
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
