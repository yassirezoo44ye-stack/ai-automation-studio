"""
Structured RuntimeReport — the single object produced by every execution.

Every field is populated regardless of success or failure.
Callers render this object; they never parse free-text strings.

Structure:
    RuntimeReport
    ├── EnvironmentReport   (Phase A — environment validation)
    ├── BuildPlanReport     (Phase Plan — resolved commands)
    ├── DependencyReport    (Phase B — dependency installation)
    └── LaunchReport        (Phase C — application launch)

Each phase report carries:
    - passed: bool
    - error_code: RuntimeErrorCode | None
    - message: str
    - technical_details: dict  (machine-readable, never truncated)
    - suggested_fix: list[str]
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from .error_codes import RuntimeErrorCode, fixes_for, js_code_for, message_for


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

    # OS info (Phase 1 — system probe)
    os_name: str = ""
    architecture: str = ""
    current_user: str = ""
    tmpdir: str = ""
    python_version: str = ""
    disk_free_mb: int = -1
    memory_free_mb: Optional[int] = None
    available_pms: dict = field(default_factory=dict)   # pm_name → version

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


# ── BuildPlan phase report ────────────────────────────────────────────────────

@dataclass
class BuildPlanReport:
    """Records the build plan that was validated before Phase B."""
    passed: bool

    runtime: str = ""
    node_version: str = ""
    pm_name: str = ""
    pm_version: str = ""
    pm_method: str = ""
    pm_evidence: str = ""
    install_cmd: str = ""   # stringified for reporting
    run_cmd: str = ""
    build_cmd: str = ""
    output_dir: str = ""
    port: int = 0
    project_type: str = ""
    is_server: bool = True
    script_name: str = ""
    warnings: list[str] = field(default_factory=list)

    # Failure
    error_code: Optional[RuntimeErrorCode] = None
    message: str = ""
    technical_details: dict = field(default_factory=dict)
    suggested_fix: list[str] = field(default_factory=list)

    @classmethod
    def from_plan(cls, plan) -> "BuildPlanReport":
        """Construct from a BuildPlan instance."""
        return cls(
            passed=True,
            runtime=plan.runtime,
            node_version=plan.node_version,
            pm_name=plan.pm_name,
            pm_version=plan.pm_version,
            pm_method=plan.pm_method,
            pm_evidence=plan.pm_evidence,
            install_cmd=plan.install_cmd_str,
            run_cmd=plan.run_cmd_str,
            build_cmd=plan.build_cmd_str,
            output_dir=plan.output_dir,
            port=plan.port,
            project_type=plan.project_type,
            is_server=plan.is_server,
            script_name=plan.script_name,
            warnings=plan.warnings,
        )

    @classmethod
    def failure(
        cls,
        code: RuntimeErrorCode,
        *,
        technical_details: dict | None = None,
        **kwargs,
    ) -> "BuildPlanReport":
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
    lockfile: str = ""              # which lockfile was found
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
    build_plan: Optional[BuildPlanReport] = None
    dependencies: Optional[DependencyReport] = None
    launch: Optional[LaunchReport] = None

    # Timing
    started_at: float = field(default_factory=time.time)
    warnings: list[str] = field(default_factory=list)

    @property
    def duration_s(self) -> float:
        return round(time.time() - self.started_at, 2)

    @property
    def passed(self) -> bool:
        return (
            self.environment is not None and self.environment.passed
            and self.dependencies is not None and self.dependencies.passed
            and self.launch is not None and self.launch.passed
        )

    @property
    def failure_reason(self) -> Optional[RuntimeErrorCode]:
        for phase in (self.environment, self.build_plan, self.dependencies, self.launch):
            if phase and not phase.passed and phase.error_code:
                return phase.error_code
        return None

    @property
    def suggested_fix(self) -> list[str]:
        for phase in (self.environment, self.build_plan, self.dependencies, self.launch):
            if phase and not phase.passed:
                return phase.suggested_fix
        return []

    def to_sse_dict(self) -> dict:
        """Serialisable dict for the final SSE 'report' event."""
        def _phase(p) -> dict | None:
            if p is None:
                return None
            d: dict = {
                "passed": p.passed,
                "error_code": p.error_code.value if p.error_code else None,
                "js_code": js_code_for(p.error_code) if p.error_code else None,
                "message": p.message,
                "suggested_fix": p.suggested_fix,
            }
            if hasattr(p, "technical_details"):
                d["technical_details"] = p.technical_details
            return d

        # Execution report summary (Phase 8)
        failure_code = self.failure_reason
        return {
            "project_id": self.project_id,
            "workspace": self.workspace,
            "passed": self.passed,
            "result": "success" if self.passed else "failure",
            "failure_reason": failure_code.value if failure_code else None,
            "failure_js_code": js_code_for(failure_code) if failure_code else None,
            "suggested_fix": self.suggested_fix,
            "duration_s": self.duration_s,
            "warnings": self.warnings,
            # Phase reports
            "environment": _phase(self.environment),
            "build_plan": _build_plan_dict(self.build_plan),
            "dependencies": _phase(self.dependencies),
            "launch": _phase(self.launch),
        }


def _build_plan_dict(bp: Optional[BuildPlanReport]) -> dict | None:
    if bp is None:
        return None
    return {
        "passed": bp.passed,
        "runtime": bp.runtime,
        "node_version": bp.node_version,
        "pm_name": bp.pm_name,
        "pm_version": bp.pm_version,
        "pm_method": bp.pm_method,
        "install_cmd": bp.install_cmd,
        "run_cmd": bp.run_cmd,
        "build_cmd": bp.build_cmd,
        "port": bp.port,
        "project_type": bp.project_type,
        "script_name": bp.script_name,
        "warnings": bp.warnings,
        "error_code": bp.error_code.value if bp.error_code else None,
        "message": bp.message,
        "suggested_fix": bp.suggested_fix,
    }
