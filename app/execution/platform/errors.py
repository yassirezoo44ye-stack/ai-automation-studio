"""
Unified error hierarchy — Phase 8 of the Execution Platform.

11 error categories, each with typed codes, descriptions, causes,
fixes, and recoverability flags.  No raw exceptions ever surface
to callers — every failure is an instance of PlatformError.

Error categories:
    ENVIRONMENT   — missing/broken runtime tools
    VALIDATION    — workspace or config is invalid
    DEPENDENCY    — package installation failures
    BUILD         — build step failed
    LAUNCH        — server failed to start or bind
    RUNTIME       — server crashed during execution
    SANDBOX       — isolation or resource limit violation
    ARTIFACT      — artifact collection or storage failure
    NETWORK       — registry or connectivity issue
    TIMEOUT       — phase or total execution timeout
    INTERNAL      — unexpected platform bug

Each error carries:
    code            — unique string identifier (e.g. "ENV_NODE_MISSING")
    category        — one of the 11 categories
    message         — user-friendly description
    technical_cause — machine-readable detail for devs / logs
    fix             — list of actionable suggestions
    recoverable     — bool — can the user retry without changing anything?
    doc_link        — URL to documentation (empty if not yet written)
"""
from __future__ import annotations

from enum import Enum


class ErrorCategory(str, Enum):
    ENVIRONMENT = "ENVIRONMENT"
    VALIDATION  = "VALIDATION"
    DEPENDENCY  = "DEPENDENCY"
    BUILD       = "BUILD"
    LAUNCH      = "LAUNCH"
    RUNTIME     = "RUNTIME"
    SANDBOX     = "SANDBOX"
    ARTIFACT    = "ARTIFACT"
    NETWORK     = "NETWORK"
    TIMEOUT     = "TIMEOUT"
    INTERNAL    = "INTERNAL"


class PlatformError(Exception):
    """
    Base class for all platform errors.

    Every failure that crosses the platform boundary must be an
    instance of this class or a subclass.  Never raise raw
    OSError, ValueError, etc. to callers.
    """

    def __init__(
        self,
        code: str,
        category: ErrorCategory,
        message: str,
        *,
        technical_cause: str = "",
        fix: list[str] | None = None,
        recoverable: bool = False,
        doc_link: str = "",
    ) -> None:
        super().__init__(message)
        self.code            = code
        self.category        = category
        self.message         = message
        self.technical_cause = technical_cause
        self.fix             = fix or []
        self.recoverable     = recoverable
        self.doc_link        = doc_link

    def to_dict(self) -> dict:
        return {
            "code"           : self.code,
            "category"       : self.category.value,
            "message"        : self.message,
            "technical_cause": self.technical_cause,
            "fix"            : self.fix,
            "recoverable"    : self.recoverable,
            "doc_link"       : self.doc_link,
        }


# ── Category subclasses ───────────────────────────────────────────────────────

class EnvironmentError(PlatformError):
    def __init__(self, code: str, message: str, **kw):
        super().__init__(code, ErrorCategory.ENVIRONMENT, message, **kw)


class ValidationError(PlatformError):
    def __init__(self, code: str, message: str, **kw):
        super().__init__(code, ErrorCategory.VALIDATION, message, **kw)


class DependencyError(PlatformError):
    def __init__(self, code: str, message: str, **kw):
        super().__init__(code, ErrorCategory.DEPENDENCY, message, **kw)


class BuildError(PlatformError):
    def __init__(self, code: str, message: str, **kw):
        super().__init__(code, ErrorCategory.BUILD, message, **kw)


class LaunchError(PlatformError):
    def __init__(self, code: str, message: str, **kw):
        super().__init__(code, ErrorCategory.LAUNCH, message, **kw)


class RuntimeError_(PlatformError):
    def __init__(self, code: str, message: str, **kw):
        super().__init__(code, ErrorCategory.RUNTIME, message, **kw)


class SandboxError(PlatformError):
    def __init__(self, code: str, message: str, **kw):
        super().__init__(code, ErrorCategory.SANDBOX, message, **kw)


class ArtifactError(PlatformError):
    def __init__(self, code: str, message: str, **kw):
        super().__init__(code, ErrorCategory.ARTIFACT, message, **kw)


class NetworkError(PlatformError):
    def __init__(self, code: str, message: str, **kw):
        super().__init__(code, ErrorCategory.NETWORK, message, **kw)


class TimeoutError_(PlatformError):
    def __init__(self, code: str, message: str, **kw):
        super().__init__(code, ErrorCategory.TIMEOUT, message, **kw)


class InternalError(PlatformError):
    def __init__(self, code: str, message: str, **kw):
        super().__init__(code, ErrorCategory.INTERNAL, message,
                         recoverable=False, **kw)


# ── Canonical error factories ─────────────────────────────────────────────────
# One function per well-known failure mode.  Callers never build PlatformError
# by hand — they call one of these factories.

def node_missing() -> EnvironmentError:
    return EnvironmentError(
        "ENV_NODE_MISSING",
        "Node.js runtime not found on this host",
        technical_cause="node --version returned non-zero or FileNotFoundError",
        fix=["Install Node.js 18+: https://nodejs.org"],
        recoverable=False,
    )


def pm_missing(tried: list[str]) -> EnvironmentError:
    return EnvironmentError(
        "ENV_PM_MISSING",
        f"No package manager found (tried: {', '.join(tried)})",
        technical_cause="All PM binaries missing or broken",
        fix=["Install Node.js (includes npm): https://nodejs.org",
             "Or: npm install -g pnpm"],
        recoverable=False,
    )


def python_missing() -> EnvironmentError:
    return EnvironmentError(
        "ENV_PYTHON_MISSING",
        "Python runtime not found on this host",
        technical_cause="python3 --version returned non-zero or FileNotFoundError",
        fix=["Install Python 3.10+: https://python.org"],
        recoverable=False,
    )


def tmp_not_writable(tmpdir: str) -> EnvironmentError:
    return EnvironmentError(
        "ENV_TMP_NOT_WRITABLE",
        f"Temp directory not writable: {tmpdir}",
        technical_cause="os.access(tmpdir, os.W_OK) returned False",
        fix=["Contact the hosting provider — temp storage must be writable"],
        recoverable=False,
    )


def workspace_missing(ws: str) -> ValidationError:
    return ValidationError(
        "VAL_WORKSPACE_MISSING",
        f"Workspace directory does not exist: {ws}",
        technical_cause="Path.exists() returned False",
        fix=["Build the project first to populate the workspace"],
        recoverable=False,
    )


def pkg_json_missing() -> ValidationError:
    return ValidationError(
        "VAL_PKG_JSON_MISSING",
        "package.json not found in project root",
        fix=["Run: npm init -y", "Or upload a package.json file"],
        recoverable=False,
    )


def pkg_json_invalid(detail: str) -> ValidationError:
    return ValidationError(
        "VAL_PKG_JSON_INVALID",
        "package.json contains invalid JSON",
        technical_cause=detail,
        fix=["Fix the JSON syntax error in package.json"],
        recoverable=False,
    )


def script_missing(script: str, available: list[str]) -> ValidationError:
    return ValidationError(
        "VAL_SCRIPT_MISSING",
        f"Script '{script}' not defined in package.json",
        technical_cause=f"Available scripts: {available}",
        fix=[f"Add a '{script}' script to package.json", "Check the available scripts: npm run"],
        recoverable=False,
    )


def install_failed(exit_code: int, pm: str, stderr_tail: list[str]) -> DependencyError:
    return DependencyError(
        "DEP_INSTALL_FAILED",
        f"{pm} install exited with code {exit_code}",
        technical_cause="\n".join(stderr_tail[-10:]),
        fix=["Download the ZIP and run locally: npm install && npm run dev"],
        recoverable=False,
    )


def install_permission_denied(path: str) -> DependencyError:
    return DependencyError(
        "DEP_INSTALL_EACCES",
        "Permission denied during package installation",
        technical_cause=f"EACCES at {path}",
        fix=["Download the ZIP and run locally", "Use Docker: docker compose up"],
        recoverable=False,
    )


def build_failed(exit_code: int, stderr_tail: list[str]) -> BuildError:
    return BuildError(
        "BUILD_FAILED",
        f"Build script exited with code {exit_code}",
        technical_cause="\n".join(stderr_tail[-10:]),
        fix=["Download the ZIP and run locally: npm run build"],
        recoverable=False,
    )


def server_timeout(port: int, timeout_s: float) -> LaunchError:
    return LaunchError(
        "LAUNCH_TIMEOUT",
        f"Server did not bind port {port} within {timeout_s:.0f}s",
        technical_cause=f"socket.create_connection('127.0.0.1:{port}') kept failing",
        fix=["Ensure the server listens on the PORT environment variable",
             "Download the ZIP and run locally to debug"],
        recoverable=True,
    )


def server_crash(argv: list[str], stderr_tail: list[str]) -> LaunchError:
    return LaunchError(
        "LAUNCH_CRASH",
        "Server process exited before binding its port",
        technical_cause=f"argv={argv}\n" + "\n".join(stderr_tail[-10:]),
        fix=["Check the entry file for syntax errors",
             "Download the ZIP and run locally: npm run dev"],
        recoverable=True,
    )


def port_exhausted() -> LaunchError:
    return LaunchError(
        "LAUNCH_PORT_EXHAUSTED",
        "No free port available in the pool",
        fix=["Stop other running projects to free a port"],
        recoverable=True,
    )


def execution_timeout(phase: str, timeout_s: float) -> TimeoutError_:
    return TimeoutError_(
        "EXEC_TIMEOUT",
        f"Execution timed out in phase '{phase}' after {timeout_s:.0f}s",
        fix=["Download the ZIP and run locally",
             "The project may require external services not in this sandbox"],
        recoverable=False,
    )


def unsupported_runtime(runtime: str, reason: str) -> ValidationError:
    return ValidationError(
        "VAL_UNSUPPORTED_RUNTIME",
        f"Runtime '{runtime}' is not supported in this sandbox",
        technical_cause=reason,
        fix=["Download the ZIP and run with docker compose up"],
        recoverable=False,
    )


def internal(detail: str) -> InternalError:
    return InternalError(
        "INTERNAL_ERROR",
        "An unexpected platform error occurred",
        technical_cause=detail,
        fix=["Retry the operation", "Report this issue if it persists"],
    )
