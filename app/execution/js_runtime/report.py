"""
Structured RuntimeReport — the single object produced by every execution.

Every field is populated regardless of success or failure.
Callers render this object; they never parse free-text strings.

Structure:
    RuntimeReport
    ├── EnvironmentReport   (Phase A)
    ├── DependencyReport    (Phase B)
    └── LaunchReport        (Phase C)

Each phase report carries:
    - passed: bool
    - error_code: RuntimeErrorCode | None
    - message: str
    - technical_details: dict  (machine-readable, never truncated)
    - suggested_fix: list[str]
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional

from .error_codes import RuntimeErrorCode, fixes_for, message_for


# ── Phase A ───────────────────────────────────────────────────────────────────

@dataclass
class EnvironmentReport:
    passed: bool

    # Host info
    home: str = ""
    path: str = ""
    node_version: str = ""
    tmp_writable: bool = False
    home_writable: bool = False

    # Package manager
    pm_name: str = ""
    pm_version: str = ""
    pm_method: str = ""     # lockfile | packageManager_field | probe | fallback
    pm_evidence: str = ""
    pm_cmd: list[str] = field(default_factory=list)

    # Filesystem
    workspace_exists: bool = False
    workspace_path: str = ""
    workspace_readable: bool = False

    # Failure
    error_code: Optional[RuntimeErrorCode] = None
    message: str = ""
    technical_details: dict = field(default_factory=dict)
    suggested_fix: list[str] = field(default_factory=list)

    @classmethod
    def failure(
        cls,
        code: RuntimeErrorCode,
        *,
        technical_details: dict | None = None,
        **kwargs,
    ) -> "EnvironmentReport":
        return cls(
            passed=False,
            error_code=code,
            message=message_for(code),
            technical_details=technical_details or {},
            suggested_fix=fixes_for(code),
            **kwargs,
        )


# ── Phase B ───────────────────────────────────────────────────────────────────

@dataclass
class DependencyReport:
    passed: bool

    # Workspace state
    pkg_json_path: str = ""
    lockfile: str = ""          # which lockfile was found
    node_modules_existed: bool = False   # was it present BEFORE this run?
    install_ran: bool = False
    install_skipped_reason: str = ""    # why install was skipped

    # Install outcome (populated only if install_ran)
    install_exit_code: int = 0
    install_stdout: list[str] = field(default_factory=list)
    install_stderr: list[str] = field(default_factory=list)
    install_duration_s: float = 0.0

    # Failure
    error_code: Optional[RuntimeErrorCode] = None
    message: str = ""
    technical_details: dict = field(default_factory=dict)
    suggested_fix: list[str] = field(default_factory=list)

    @property
    def all_install_output(self) -> list[str]:
        return self.install_stdout + self.install_stderr

    @classmethod
    def skipped(cls, reason: str) -> "DependencyReport":
        return cls(passed=True, node_modules_existed=True,
                   install_skipped_reason=reason)

    @classmethod
    def failure(
        cls,
        code: RuntimeErrorCode,
        *,
        technical_details: dict | None = None,
        **kwargs,
    ) -> "DependencyReport":
        return cls(
            passed=False,
            error_code=code,
            message=message_for(code),
            technical_details=technical_details or {},
            suggested_fix=fixes_for(code),
            **kwargs,
        )


# ── Phase C ───────────────────────────────────────────────────────────────────

@dataclass
class LaunchReport:
    passed: bool

    script: str = ""
    argv: list[str] = field(default_factory=list)
    port: int = 0
    startup_duration_s: float = 0.0

    # Failure
    error_code: Optional[RuntimeErrorCode] = None
    message: str = ""
    technical_details: dict = field(default_factory=dict)
    suggested_fix: list[str] = field(default_factory=list)

    # Crash output (populated on EXEC_SERVER_CRASH / EXEC_SERVER_TIMEOUT)
    crash_stdout: list[str] = field(default_factory=list)
    crash_stderr: list[str] = field(default_factory=list)

    @classmethod
    def failure(
        cls,
        code: RuntimeErrorCode,
        *,
        technical_details: dict | None = None,
        **kwargs,
    ) -> "LaunchReport":
        return cls(
            passed=False,
            error_code=code,
            message=message_for(code),
            technical_details=technical_details or {},
            suggested_fix=fixes_for(code),
            **kwargs,
        )


# ── Top-level RuntimeReport ───────────────────────────────────────────────────

@dataclass
class RuntimeReport:
    """
    Complete record of one execution attempt.

    Produced by PhaseRunner.run().  The driver streams events while
    this is built; the final report is emitted as the last SSE event.
    """
    project_id: str
    workspace: str

    environment: Optional[EnvironmentReport] = None
    dependencies: Optional[DependencyReport] = None
    launch: Optional[LaunchReport] = None

    @property
    def passed(self) -> bool:
        return (
            self.environment is not None and self.environment.passed
            and self.dependencies is not None and self.dependencies.passed
            and self.launch is not None and self.launch.passed
        )

    @property
    def failure_reason(self) -> Optional[RuntimeErrorCode]:
        for phase in (self.environment, self.dependencies, self.launch):
            if phase and not phase.passed and phase.error_code:
                return phase.error_code
        return None

    @property
    def suggested_fix(self) -> list[str]:
        for phase in (self.environment, self.dependencies, self.launch):
            if phase and not phase.passed:
                return phase.suggested_fix
        return []

    def to_sse_dict(self) -> dict:
        """Serialisable dict suitable for inclusion in an SSE 'report' event."""
        def _phase(p) -> dict | None:
            if p is None:
                return None
            d = {
                "passed": p.passed,
                "error_code": p.error_code.value if p.error_code else None,
                "message": p.message,
                "suggested_fix": p.suggested_fix,
            }
            if hasattr(p, "technical_details"):
                d["technical_details"] = p.technical_details
            return d

        return {
            "project_id": self.project_id,
            "workspace": self.workspace,
            "passed": self.passed,
            "failure_reason": self.failure_reason.value if self.failure_reason else None,
            "suggested_fix": self.suggested_fix,
            "environment": _phase(self.environment),
            "dependencies": _phase(self.dependencies),
            "launch": _phase(self.launch),
        }
