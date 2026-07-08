"""
Typed event system — Phase 6 of the Execution Platform.

Every state change the engine produces is a TypedEvent dataclass.
The UI consumes these events instead of parsing free-text log lines.

Event hierarchy:
    TypedEvent (base)
    ├── ExecutionStarted
    ├── ProbeCompleted
    ├── ValidationPassed
    ├── ValidationFailed
    ├── BuildPlanGenerated
    ├── InstallStarted
    ├── InstallProgress
    ├── InstallCompleted
    ├── InstallFailed
    ├── BuildStarted
    ├── BuildProgress
    ├── BuildCompleted
    ├── BuildFailed
    ├── ServerStarting
    ├── ServerReady
    ├── HealthCheckPassed
    ├── ArtifactCollected
    ├── ExecutionFailed
    ├── ExecutionFinished
    ├── CleanupStarted
    ├── CleanupFinished
    └── Heartbeat

Every event can be serialised to a SSE dict for streaming to the frontend.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, ClassVar, Optional


# ── Base ─────────────────────────────────────────────────────────────────────

@dataclass
class TypedEvent:
    """Base class for all platform events."""
    execution_id: str
    timestamp: float = field(default_factory=time.time)
    event_type: ClassVar[str] = "event"

    def to_sse_dict(self) -> dict:
        """Produce the JSON payload that flows in an SSE 'data:' line."""
        d = {
            "type"        : self.event_type,
            "execution_id": self.execution_id,
            "ts"          : round(self.timestamp, 3),
        }
        d.update(self._extra())
        return d

    def _extra(self) -> dict:
        return {}


# ── Execution lifecycle ────────────────────────────────────────────────────────

@dataclass
class ExecutionStarted(TypedEvent):
    event_type: ClassVar[str] = "execution_started"
    project_id: str = ""
    runtime: str = ""
    workspace: str = ""

    def _extra(self) -> dict:
        return {
            "project_id": self.project_id,
            "runtime"   : self.runtime,
            "workspace" : self.workspace,
        }


@dataclass
class ProbeCompleted(TypedEvent):
    event_type: ClassVar[str] = "probe_completed"
    os_name: str = ""
    architecture: str = ""
    node_version: Optional[str] = None
    python_version: str = ""
    available_runtimes: list[str] = field(default_factory=list)
    disk_free_mb: int = 0
    memory_free_mb: Optional[int] = None
    warnings: list[str] = field(default_factory=list)

    def _extra(self) -> dict:
        return {
            "os"                : self.os_name,
            "architecture"      : self.architecture,
            "node"              : self.node_version,
            "python"            : self.python_version,
            "available_runtimes": self.available_runtimes,
            "disk_free_mb"      : self.disk_free_mb,
            "memory_free_mb"    : self.memory_free_mb,
            "warnings"          : self.warnings,
        }


@dataclass
class ValidationPassed(TypedEvent):
    event_type: ClassVar[str] = "validation_passed"
    checks: list[str] = field(default_factory=list)

    def _extra(self) -> dict:
        return {"checks": self.checks}


@dataclass
class ValidationFailed(TypedEvent):
    event_type: ClassVar[str] = "validation_failed"
    error_code: str = ""
    message: str = ""
    fix: list[str] = field(default_factory=list)

    def _extra(self) -> dict:
        return {"error_code": self.error_code, "message": self.message, "fix": self.fix}


@dataclass
class BuildPlanGenerated(TypedEvent):
    event_type: ClassVar[str] = "build_plan_generated"
    plan: dict = field(default_factory=dict)   # BuildPlan.to_dict()

    def _extra(self) -> dict:
        return {"plan": self.plan}


@dataclass
class InstallStarted(TypedEvent):
    event_type: ClassVar[str] = "install_started"
    pm: str = ""
    command: str = ""
    cache_hit: bool = False

    def _extra(self) -> dict:
        return {"pm": self.pm, "command": self.command, "cache_hit": self.cache_hit}


@dataclass
class InstallProgress(TypedEvent):
    event_type: ClassVar[str] = "install_progress"
    stream: str = "stdout"   # "stdout" | "stderr"
    line: str = ""

    def _extra(self) -> dict:
        return {"stream": self.stream, "line": self.line}


@dataclass
class InstallCompleted(TypedEvent):
    event_type: ClassVar[str] = "install_completed"
    duration_s: float = 0.0
    skipped: bool = False
    skip_reason: str = ""

    def _extra(self) -> dict:
        return {
            "duration_s" : self.duration_s,
            "skipped"    : self.skipped,
            "skip_reason": self.skip_reason,
        }


@dataclass
class InstallFailed(TypedEvent):
    event_type: ClassVar[str] = "install_failed"
    error_code: str = ""
    message: str = ""
    exit_code: int = 1
    fix: list[str] = field(default_factory=list)

    def _extra(self) -> dict:
        return {
            "error_code": self.error_code,
            "message"   : self.message,
            "exit_code" : self.exit_code,
            "fix"       : self.fix,
        }


@dataclass
class BuildStarted(TypedEvent):
    event_type: ClassVar[str] = "build_started"
    command: str = ""
    script: str = ""

    def _extra(self) -> dict:
        return {"command": self.command, "script": self.script}


@dataclass
class BuildProgress(TypedEvent):
    event_type: ClassVar[str] = "build_progress"
    stream: str = "stdout"
    line: str = ""

    def _extra(self) -> dict:
        return {"stream": self.stream, "line": self.line}


@dataclass
class BuildCompleted(TypedEvent):
    event_type: ClassVar[str] = "build_completed"
    duration_s: float = 0.0
    output_dir: str = ""

    def _extra(self) -> dict:
        return {"duration_s": self.duration_s, "output_dir": self.output_dir}


@dataclass
class BuildFailed(TypedEvent):
    event_type: ClassVar[str] = "build_failed"
    error_code: str = ""
    message: str = ""
    exit_code: int = 1
    stderr_tail: list[str] = field(default_factory=list)

    def _extra(self) -> dict:
        return {
            "error_code": self.error_code,
            "message"   : self.message,
            "exit_code" : self.exit_code,
            "stderr_tail": self.stderr_tail,
        }


@dataclass
class ServerStarting(TypedEvent):
    event_type: ClassVar[str] = "server_starting"
    command: str = ""
    port: int = 0
    pid: Optional[int] = None

    def _extra(self) -> dict:
        return {"command": self.command, "port": self.port, "pid": self.pid}


@dataclass
class ServerReady(TypedEvent):
    event_type: ClassVar[str] = "server_ready"
    preview_url: str = ""
    port: int = 0
    startup_duration_s: float = 0.0
    command: str = ""
    project_type: str = ""
    message: str = ""

    def _extra(self) -> dict:
        return {
            "preview_url"        : self.preview_url,
            "port"               : self.port,
            "startup_duration_s" : self.startup_duration_s,
            "command"            : self.command,
            "project_type"       : self.project_type,
            "message"            : self.message,
        }


@dataclass
class HealthCheckPassed(TypedEvent):
    event_type: ClassVar[str] = "health_check_passed"
    url: str = ""
    status_code: int = 200
    latency_ms: float = 0.0

    def _extra(self) -> dict:
        return {"url": self.url, "status_code": self.status_code, "latency_ms": self.latency_ms}


@dataclass
class ArtifactCollected(TypedEvent):
    event_type: ClassVar[str] = "artifact_collected"
    name: str = ""
    path: str = ""
    size_bytes: int = 0
    kind: str = ""   # "log" | "dist" | "report" | "screenshot"

    def _extra(self) -> dict:
        return {
            "name"      : self.name,
            "path"      : self.path,
            "size_bytes": self.size_bytes,
            "kind"      : self.kind,
        }


@dataclass
class ExecutionFailed(TypedEvent):
    event_type: ClassVar[str] = "execution_failed"
    error_code: str = ""
    category: str = ""
    message: str = ""
    technical_cause: str = ""
    fix: list[str] = field(default_factory=list)
    recoverable: bool = False
    doc_link: str = ""

    def _extra(self) -> dict:
        return {
            "error_code"     : self.error_code,
            "category"       : self.category,
            "message"        : self.message,
            "technical_cause": self.technical_cause,
            "fix"            : self.fix,
            "recoverable"    : self.recoverable,
            "doc_link"       : self.doc_link,
        }


@dataclass
class ExecutionFinished(TypedEvent):
    event_type: ClassVar[str] = "execution_finished"
    success: bool = True
    duration_s: float = 0.0
    exit_code: int = 0
    artifact_count: int = 0

    def _extra(self) -> dict:
        return {
            "success"       : self.success,
            "duration_s"    : self.duration_s,
            "exit_code"     : self.exit_code,
            "artifact_count": self.artifact_count,
        }


@dataclass
class CleanupStarted(TypedEvent):
    event_type: ClassVar[str] = "cleanup_started"

    def _extra(self) -> dict:
        return {}


@dataclass
class CleanupFinished(TypedEvent):
    event_type: ClassVar[str] = "cleanup_finished"
    freed_bytes: int = 0

    def _extra(self) -> dict:
        return {"freed_bytes": self.freed_bytes}


@dataclass
class Heartbeat(TypedEvent):
    event_type: ClassVar[str] = "heartbeat"
    message: str = "still running"

    def _extra(self) -> dict:
        return {"message": self.message}


# ── Log line (replaces raw "log" events) ─────────────────────────────────────

@dataclass
class LogLine(TypedEvent):
    """Replaces the old {"type": "log", "line": "..."} pattern."""
    event_type: ClassVar[str] = "log"
    stream: str = "stdout"
    line: str = ""
    phase: str = ""   # "probe" | "install" | "build" | "launch"

    def _extra(self) -> dict:
        return {"stream": self.stream, "line": self.line, "phase": self.phase}


# ── Status update ─────────────────────────────────────────────────────────────

@dataclass
class StatusUpdate(TypedEvent):
    """Lightweight progress message — replaces {"type": "status", "message": "..."}."""
    event_type: ClassVar[str] = "status"
    message: str = ""
    phase: str = ""

    def _extra(self) -> dict:
        return {"message": self.message, "phase": self.phase}


# ── HTML output (for build projects) ─────────────────────────────────────────

@dataclass
class HtmlOutput(TypedEvent):
    """Build project rendered output — replaces {"type": "html", ...}."""
    event_type: ClassVar[str] = "html"
    html_content: str = ""
    entry_file: str = ""
    project_type: str = ""
    message: str = ""

    def _extra(self) -> dict:
        return {
            "html_content": self.html_content,
            "entry_file"  : self.entry_file,
            "project_type": self.project_type,
            "message"     : self.message,
        }


# ── Unsupported ───────────────────────────────────────────────────────────────

@dataclass
class UnsupportedRuntime(TypedEvent):
    """Emitted when a project type cannot run in this sandbox."""
    event_type: ClassVar[str] = "unsupported"
    project_type: str = ""
    reason: str = ""
    local_run_hint: str = ""
    fix: list[str] = field(default_factory=list)

    def _extra(self) -> dict:
        return {
            "project_type"  : self.project_type,
            "reason"        : self.reason,
            "local_run_hint": self.local_run_hint,
            "fix"           : self.fix,
        }


# ── Report event (terminal event) ─────────────────────────────────────────────

@dataclass
class ExecutionReport(TypedEvent):
    """Final report — always the last event in a successful or failed execution."""
    event_type: ClassVar[str] = "report"
    report: dict = field(default_factory=dict)

    def _extra(self) -> dict:
        return {"report": self.report}


# ── Registry of all event types (for deserialization) ─────────────────────────

EVENT_REGISTRY: dict[str, type[TypedEvent]] = {
    cls.event_type: cls                          # type: ignore[attr-defined]
    for cls in [
        ExecutionStarted, ProbeCompleted,
        ValidationPassed, ValidationFailed,
        BuildPlanGenerated,
        InstallStarted, InstallProgress, InstallCompleted, InstallFailed,
        BuildStarted, BuildProgress, BuildCompleted, BuildFailed,
        ServerStarting, ServerReady, HealthCheckPassed,
        ArtifactCollected,
        ExecutionFailed, ExecutionFinished,
        CleanupStarted, CleanupFinished,
        Heartbeat, LogLine, StatusUpdate, HtmlOutput,
        UnsupportedRuntime, ExecutionReport,
    ]
}
