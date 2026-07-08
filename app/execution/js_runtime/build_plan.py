"""
BuildPlan — fully-resolved execution plan for one project run.

Created during the planning phase, after environment validation and before
any subprocess is spawned.  Every command field is non-empty or validation
raises a typed error — "$ undefined" is structurally impossible.

Contract:
  - validate() returns an empty list iff the plan is safe to execute.
  - PhaseRunner.run() calls validate() before Phase B.
  - If validate() returns errors the run aborts immediately.
  - No command may be passed to subprocess without a prior valid BuildPlan.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class BuildPlan:
    """
    Fully-resolved execution plan.

    Every field that feeds into a subprocess call is typed list[str].
    An empty list means "not applicable", not "unknown".
    validate() distinguishes these cases and rejects the plan if a
    required command is missing.
    """
    project_id: str
    workspace: str

    # ── Runtime ───────────────────────────────────────────────────────────────
    runtime: str = "node"
    node_version: str = ""
    python_version: str = ""

    # ── Package manager ───────────────────────────────────────────────────────
    pm_name: str = ""
    pm_version: str = ""
    pm_cmd: list[str] = field(default_factory=list)
    pm_method: str = ""         # lockfile | packageManager_field | probe | fallback
    pm_evidence: str = ""

    # ── Commands ──────────────────────────────────────────────────────────────
    # validate() ensures these are populated before Phase B begins.
    install_cmd: list[str] = field(default_factory=list)
    run_cmd: list[str] = field(default_factory=list)    # server projects
    build_cmd: list[str] = field(default_factory=list)  # SPA/SSG projects

    # ── Output ────────────────────────────────────────────────────────────────
    output_dir: str = ""    # "dist" | "build" | "out" for build projects
    port: int = 0           # allocated port for server projects

    # ── Environment ───────────────────────────────────────────────────────────
    env_vars: dict[str, str] = field(default_factory=dict)

    # ── Metadata ──────────────────────────────────────────────────────────────
    project_type: str = ""
    is_server: bool = True      # False → build project (SPA/SSG)
    script_name: str = ""       # "dev" | "start" | "build" etc.
    warnings: list[str] = field(default_factory=list)

    # ── Convenience properties ────────────────────────────────────────────────

    @property
    def run_cmd_str(self) -> str:
        """Human-readable run command — guaranteed non-empty after validate()."""
        return " ".join(self.run_cmd)

    @property
    def install_cmd_str(self) -> str:
        return " ".join(self.install_cmd)

    @property
    def build_cmd_str(self) -> str:
        return " ".join(self.build_cmd)

    # ── Validation ────────────────────────────────────────────────────────────

    def validate(self) -> list[str]:
        """
        Return a list of error strings.  Empty list = plan is safe to execute.

        Every error includes the JS-code prefix so callers can switch on code.
        Callers MUST call this before spawning any subprocess.  If errors are
        returned the run must abort immediately — no silent fallbacks.
        """
        errors: list[str] = []

        if not self.pm_name:
            errors.append("JS001: package manager not resolved")
        if not self.pm_cmd:
            errors.append("JS001: package manager command is undefined")
        if not self.install_cmd:
            errors.append(
                "JS001: install command is undefined — "
                "cannot install dependencies"
            )

        if self.is_server:
            if not self.run_cmd:
                errors.append(
                    "JS004: run command is undefined — "
                    "no 'start', 'dev', 'serve', or 'preview' script "
                    "found in package.json"
                )
            if self.port <= 0:
                errors.append(
                    "JS006: port not allocated — cannot start server"
                )
        else:
            if not self.build_cmd:
                errors.append(
                    "JS004: build command is undefined — "
                    "no 'build', 'compile', or 'bundle' script "
                    "found in package.json"
                )

        return errors

    # ── Serialisation ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """JSON-serialisable snapshot.  No field is ever 'undefined'."""
        return {
            "runtime": self.runtime,
            "node_version": self.node_version,
            "pm_name": self.pm_name,
            "pm_version": self.pm_version,
            "pm_method": self.pm_method,
            "pm_evidence": self.pm_evidence,
            "install_cmd": self.install_cmd_str,
            "run_cmd": self.run_cmd_str,
            "build_cmd": self.build_cmd_str,
            "output_dir": self.output_dir,
            "port": self.port,
            "project_type": self.project_type,
            "is_server": self.is_server,
            "script_name": self.script_name,
            "warnings": self.warnings,
        }

    def as_log_lines(self) -> list[str]:
        """Human-readable plan for streaming to the client."""
        lines = [
            "── Build Plan ────────────────────────────────────────────────",
            f"  Runtime         : {self.runtime} {self.node_version}",
            f"  Package Manager : {self.pm_name} {self.pm_version}",
            f"  PM Detection    : {self.pm_method} ({self.pm_evidence})",
            f"  Install Cmd     : {self.install_cmd_str or '(none)'}",
        ]
        if self.is_server:
            lines += [
                f"  Run Cmd         : {self.run_cmd_str or '(undefined — INVALID)'}",
                f"  Port            : {self.port or '(not allocated)'}",
            ]
        else:
            lines += [
                f"  Build Cmd       : {self.build_cmd_str or '(undefined — INVALID)'}",
                f"  Output Dir      : {self.output_dir or '(unknown)'}",
            ]
        lines.append(f"  Project Type    : {self.project_type}")
        for w in self.warnings:
            lines.append(f"  ⚠ WARNING       : {w}")
        lines.append("──────────────────────────────────────────────────────────────")
        return lines
