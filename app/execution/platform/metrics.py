"""
ExecutionMetrics — Phase 7 of the Execution Platform.

Records timing and resource usage for every execution phase.
Metrics are attached to the final ExecutionReport and stored for analytics.

All durations are in seconds (float).  Memory/CPU values are best-effort
and may be None on platforms that don't expose them.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional
from uuid import uuid4


@dataclass
class PhaseMetrics:
    """Timing for one lifecycle phase."""
    phase: str
    started_at: float = field(default_factory=time.time)
    ended_at: Optional[float] = None
    success: bool = False
    error_code: Optional[str] = None

    @property
    def duration_s(self) -> Optional[float]:
        if self.ended_at is None:
            return None
        return round(self.ended_at - self.started_at, 3)

    def complete(self, *, success: bool, error_code: Optional[str] = None) -> None:
        self.ended_at   = time.time()
        self.success    = success
        self.error_code = error_code

    def to_dict(self) -> dict:
        return {
            "phase"     : self.phase,
            "duration_s": self.duration_s,
            "success"   : self.success,
            "error_code": self.error_code,
        }


@dataclass
class ExecutionMetrics:
    """
    Complete timing and resource record for one execution.

    Created at the start of every execution.  Phases register themselves
    by calling start_phase() / end_phase().  The final report embeds
    metrics.to_dict().
    """
    execution_id: str = field(default_factory=lambda: str(uuid4()))
    project_id: str = ""
    runtime: str = ""
    started_at: float = field(default_factory=time.time)
    ended_at: Optional[float] = None

    # Phase breakdown
    phases: list[PhaseMetrics] = field(default_factory=list)

    # Resource usage (best-effort)
    peak_memory_mb: Optional[float] = None
    avg_cpu_pct: Optional[float] = None
    disk_used_mb: Optional[float] = None

    # Derived times (filled in by specific phases)
    probe_duration_s: Optional[float] = None
    install_duration_s: Optional[float] = None
    build_duration_s: Optional[float] = None
    launch_duration_s: Optional[float] = None

    # Cache behaviour
    cache_hit: bool = False
    cache_key: str = ""

    # Final outcome
    success: bool = False
    exit_code: int = 0
    error_code: Optional[str] = None
    artifact_count: int = 0

    @property
    def total_duration_s(self) -> Optional[float]:
        if self.ended_at is None:
            return None
        return round(self.ended_at - self.started_at, 3)

    def start_phase(self, phase: str) -> PhaseMetrics:
        pm = PhaseMetrics(phase=phase)
        self.phases.append(pm)
        return pm

    def end_phase(
        self,
        pm: PhaseMetrics,
        *,
        success: bool,
        error_code: Optional[str] = None,
    ) -> None:
        pm.complete(success=success, error_code=error_code)
        # Update derived timing
        if pm.duration_s is not None:
            if pm.phase == "probe":
                self.probe_duration_s = pm.duration_s
            elif pm.phase in ("install", "dependency"):
                self.install_duration_s = pm.duration_s
            elif pm.phase == "build":
                self.build_duration_s = pm.duration_s
            elif pm.phase in ("launch", "server"):
                self.launch_duration_s = pm.duration_s

    def finish(self, *, success: bool, exit_code: int = 0, error_code: Optional[str] = None) -> None:
        self.ended_at   = time.time()
        self.success    = success
        self.exit_code  = exit_code
        self.error_code = error_code

    def to_dict(self) -> dict:
        return {
            "execution_id"    : self.execution_id,
            "project_id"      : self.project_id,
            "runtime"         : self.runtime,
            "started_at"      : round(self.started_at, 3),
            "total_duration_s": self.total_duration_s,
            "cache_hit"       : self.cache_hit,
            "cache_key"       : self.cache_key,
            "probe_duration_s"  : self.probe_duration_s,
            "install_duration_s": self.install_duration_s,
            "build_duration_s"  : self.build_duration_s,
            "launch_duration_s" : self.launch_duration_s,
            "peak_memory_mb"  : self.peak_memory_mb,
            "disk_used_mb"    : self.disk_used_mb,
            "success"         : self.success,
            "exit_code"       : self.exit_code,
            "error_code"      : self.error_code,
            "artifact_count"  : self.artifact_count,
            "phases"          : [p.to_dict() for p in self.phases],
        }
