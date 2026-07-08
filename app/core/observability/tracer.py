"""
Distributed Tracer — lightweight in-process span-based tracing.

Produces W3C-compatible trace-id / span-id pairs.
Traces are stored in a rolling in-memory ring buffer (last 2 000 spans)
and exposed via /api/diagnostics/traces.

For production, replace the in-memory store with an OTLP/Jaeger exporter
by subclassing SpanExporter and setting Tracer._exporter.
"""
from __future__ import annotations

import time
import uuid
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Optional


def _new_id(n: int = 16) -> str:
    return uuid.uuid4().hex[:n]


@dataclass
class Span:
    trace_id  : str
    span_id   : str
    parent_id : Optional[str]
    name      : str
    service   : str
    started_at: float = field(default_factory=time.monotonic)
    ended_at  : Optional[float] = None
    tags      : dict[str, str]  = field(default_factory=dict)
    events    : list[dict]      = field(default_factory=list)
    error     : Optional[str]   = None
    _tracer   : Optional["Tracer"] = field(default=None, repr=False)

    @property
    def duration_ms(self) -> float:
        if self.ended_at is None:
            return (time.monotonic() - self.started_at) * 1000
        return (self.ended_at - self.started_at) * 1000

    def set_tag(self, key: str, value: str) -> "Span":
        self.tags[key] = value
        return self

    def add_event(self, name: str, **attrs: str) -> "Span":
        self.events.append({"name": name, "ts": time.monotonic(), **attrs})
        return self

    def finish(self, error: Optional[str] = None) -> None:
        self.ended_at = time.monotonic()
        if error:
            self.error = error
        if self._tracer:
            self._tracer._finish(self)

    def __enter__(self) -> "Span":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.finish(error=str(exc_val) if exc_val else None)

    def to_dict(self) -> dict:
        return {
            "trace_id"   : self.trace_id,
            "span_id"    : self.span_id,
            "parent_id"  : self.parent_id,
            "name"       : self.name,
            "service"    : self.service,
            "duration_ms": round(self.duration_ms, 2),
            "tags"       : self.tags,
            "events"     : self.events,
            "error"      : self.error,
        }


class Tracer:
    """
    Lightweight in-process tracer.

    Usage:
        tracer = get_tracer()
        with tracer.start_span("agent.run", service="agentos") as span:
            span.set_tag("agent", "build")
            result = await agent.run(ctx)
    """

    def __init__(self, max_spans: int = 2_000) -> None:
        self._lock   = threading.Lock()
        self._spans  : deque[Span] = deque(maxlen=max_spans)
        self._active : dict[str, Span] = {}   # span_id → Span

    def start_span(
        self,
        name     : str,
        *,
        service  : str = "agentos",
        trace_id : Optional[str] = None,
        parent_id: Optional[str] = None,
    ) -> Span:
        tid = trace_id or _new_id(32)
        sid = _new_id(16)
        span = Span(
            trace_id=tid, span_id=sid, parent_id=parent_id,
            name=name, service=service, _tracer=self,
        )
        with self._lock:
            self._active[sid] = span
        return span

    def _finish(self, span: Span) -> None:
        with self._lock:
            self._active.pop(span.span_id, None)
            self._spans.append(span)

    def recent(self, n: int = 100) -> list[dict]:
        with self._lock:
            spans = list(self._spans)[-n:]
        return [s.to_dict() for s in reversed(spans)]

    def active(self) -> list[dict]:
        with self._lock:
            return [s.to_dict() for s in self._active.values()]

    def trace(self, trace_id: str) -> list[dict]:
        with self._lock:
            return [s.to_dict() for s in self._spans if s.trace_id == trace_id]


# ── Singleton ─────────────────────────────────────────────────────────────────

_tracer: Tracer | None = None


def get_tracer() -> Tracer:
    global _tracer
    if _tracer is None:
        _tracer = Tracer()
    return _tracer
