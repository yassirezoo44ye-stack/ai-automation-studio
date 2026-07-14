"""
ExecutionReport — Phase 9 of the Execution Platform.

The complete, canonical record of one execution.  This is the last
object produced by the UnifiedExecutionEngine and is:
  - embedded in the final SSE "report" event
  - written as a JSON artifact
  - returned by GET /api/runtime/{execution_id}/report

Fields are deliberately flat (not nested) for easy frontend consumption.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ExecutionReport:
    """
    Canonical record of one execution.

    Produced by UnifiedExecutionEngine.finish() and exported as:
      - JSON artifact ("report.json")
      - SSE ExecutionReport event
      - GET /api/runtime/{execution_id}/report response body
    """
    # ── Identity ─────────────────────────────────────────────────────────────
    execution_id: str
    project_id: str = ""
    runtime: str = ""           # "node" | "python" | "docker" | "electron"

    # ── Timing ───────────────────────────────────────────────────────────────
    started_at: float = field(default_factory=time.time)
    ended_at: Optional[float] = None

    # ── Outcome ──────────────────────────────────────────────────────────────
    success: bool = False
    exit_code: int = 0
    error_code: str = ""
    error_category: str = ""
    error_message: str = ""
    error_fix: list[str] = field(default_factory=list)

    # ── Phase timing (seconds) ────────────────────────────────────────────────
    probe_duration_s: Optional[float] = None
    install_duration_s: Optional[float] = None
    build_duration_s: Optional[float] = None
    launch_duration_s: Optional[float] = None

    # ── Cache ─────────────────────────────────────────────────────────────────
    cache_hit: bool = False
    cache_key: str = ""

    # ── Environment snapshot ─────────────────────────────────────────────────
    os_name: str = ""
    architecture: str = ""
    node_version: Optional[str] = None
    python_version: str = ""
    pm_name: str = ""
    pm_version: str = ""
    disk_free_mb: int = 0
    memory_free_mb: Optional[int] = None

    # ── Build plan ───────────────────────────────────────────────────────────
    install_cmd: str = ""
    run_cmd: str = ""
    port: int = 0
    project_type: str = ""      # "react-app" | "express" | "static" | …
    is_server: bool = False

    # ── Runtime ──────────────────────────────────────────────────────────────
    preview_url: str = ""
    pid: Optional[int] = None

    # ── Artifacts ────────────────────────────────────────────────────────────
    artifacts: list[dict] = field(default_factory=list)   # Artifact.to_dict() records
    artifact_count: int = 0

    # ── Warnings ─────────────────────────────────────────────────────────────
    warnings: list[str] = field(default_factory=list)

    # ── Raw phase breakdown (for devs) ───────────────────────────────────────
    phases: list[dict] = field(default_factory=list)   # PhaseMetrics.to_dict()

    # ── Helpers ──────────────────────────────────────────────────────────────

    @property
    def total_duration_s(self) -> Optional[float]:
        if self.ended_at is None:
            return None
        return round(self.ended_at - self.started_at, 3)

    def finish(
        self,
        *,
        success: bool,
        exit_code: int = 0,
        error_code: str = "",
        error_category: str = "",
        error_message: str = "",
        error_fix: list[str] | None = None,
    ) -> None:
        self.ended_at      = time.time()
        self.success       = success
        self.exit_code     = exit_code
        self.error_code    = error_code
        self.error_category= error_category
        self.error_message = error_message
        self.error_fix     = error_fix or []

    def to_dict(self) -> dict:
        return {
            # Identity
            "execution_id"     : self.execution_id,
            "project_id"       : self.project_id,
            "runtime"          : self.runtime,
            # Timing
            "started_at"       : round(self.started_at, 3),
            "ended_at"         : round(self.ended_at, 3) if self.ended_at else None,
            "total_duration_s" : self.total_duration_s,
            # Outcome
            "success"          : self.success,
            "exit_code"        : self.exit_code,
            "error_code"       : self.error_code,
            "error_category"   : self.error_category,
            "error_message"    : self.error_message,
            "error_fix"        : self.error_fix,
            # Phase timing
            "probe_duration_s"  : self.probe_duration_s,
            "install_duration_s": self.install_duration_s,
            "build_duration_s"  : self.build_duration_s,
            "launch_duration_s" : self.launch_duration_s,
            # Cache
            "cache_hit"        : self.cache_hit,
            "cache_key"        : self.cache_key,
            # Environment
            "os_name"          : self.os_name,
            "architecture"     : self.architecture,
            "node_version"     : self.node_version,
            "python_version"   : self.python_version,
            "pm_name"          : self.pm_name,
            "pm_version"       : self.pm_version,
            "disk_free_mb"     : self.disk_free_mb,
            "memory_free_mb"   : self.memory_free_mb,
            # Build plan
            "install_cmd"      : self.install_cmd,
            "run_cmd"          : self.run_cmd,
            "port"             : self.port,
            "project_type"     : self.project_type,
            "is_server"        : self.is_server,
            # Runtime
            "preview_url"      : self.preview_url,
            "pid"              : self.pid,
            # Artifacts
            "artifacts"        : self.artifacts,
            "artifact_count"   : self.artifact_count,
            # Meta
            "warnings"         : self.warnings,
            "phases"           : self.phases,
        }

    def to_sse_dict(self) -> dict:
        """Produce the SSE payload for the final 'report' event."""
        return {
            "type"        : "report",
            "execution_id": self.execution_id,
            "report"      : self.to_dict(),
        }
