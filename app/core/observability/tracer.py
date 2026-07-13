"""
Distributed Tracer — real OpenTelemetry SDK underneath, wrapped in the
exact same Tracer/Span API this module always exposed:

    tracer = get_tracer()
    with tracer.start_span("agent.run", service="agentos") as span:
        span.set_tag("agent", "build")
        result = await agent.run(ctx)

/api/diagnostics/traces* (app/routers/diagnostics_api.py) and every call
site keep working unchanged — a custom SpanProcessor feeds finished OTel
spans into the same in-memory ring buffer (last 2 000 spans) this module
always exposed. trace_id/span_id are OTel's own 32-hex/16-hex W3C-format
IDs, the same format this module produced before adopting OTel, so no
downstream consumer sees a format change.

An OTLP exporter is additionally wired when OTEL_EXPORTER_OTLP_ENDPOINT is
set (see _maybe_otlp_processor below) — batched, so it never blocks a
request on network I/O; the in-memory ring buffer works identically with
or without an external collector configured.
"""
from __future__ import annotations

import logging
import os
import threading
from collections import deque
from typing import Optional

from opentelemetry import trace as otel_trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider, ReadableSpan, SpanProcessor
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import SpanContext, TraceFlags, NonRecordingSpan, Status, StatusCode

log = logging.getLogger(__name__)

_MAX_SPANS = 2_000


def _fmt_trace_id(tid: int) -> str:
    return format(tid, "032x")


def _fmt_span_id(sid: int) -> str:
    return format(sid, "016x")


class SpanHandle:
    """Wraps a real OTel Span with the set_tag/add_event/finish interface
    this module's API has always exposed — callers don't need to know the
    underlying implementation is now the real OTel SDK."""

    def __init__(self, otel_span) -> None:
        self._span = otel_span

    @property
    def trace_id(self) -> str:
        return _fmt_trace_id(self._span.get_span_context().trace_id)

    @property
    def span_id(self) -> str:
        return _fmt_span_id(self._span.get_span_context().span_id)

    def set_tag(self, key: str, value) -> "SpanHandle":
        self._span.set_attribute(key, str(value))
        return self

    def add_event(self, name: str, **attrs) -> "SpanHandle":
        self._span.add_event(name, attributes={k: str(v) for k, v in attrs.items()})
        return self

    def finish(self, error: Optional[str] = None) -> None:
        if error:
            self._span.set_status(Status(StatusCode.ERROR, error))
        self._span.end()

    def __enter__(self) -> "SpanHandle":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.finish(error=str(exc_val) if exc_val else None)


class _RingBufferProcessor(SpanProcessor):
    """Tracks in-flight spans (on_start) and feeds every finished span into
    an in-memory ring buffer (on_end), in the exact dict shape
    /api/diagnostics/traces* has always returned — this is what makes
    adopting the real SDK backward-compatible at the API level instead of
    a breaking rewrite. Unlike an Exporter, a SpanProcessor sees on_start
    too, so active() can reflect genuinely in-flight spans rather than
    faking a registry the SDK doesn't otherwise expose."""

    def __init__(self, max_spans: int = _MAX_SPANS) -> None:
        self._lock   = threading.Lock()
        self._spans  : deque[dict] = deque(maxlen=max_spans)
        self._active : dict[str, ReadableSpan] = {}   # span_id (hex) -> span

    def on_start(self, span, parent_context=None) -> None:
        sid = _fmt_span_id(span.get_span_context().span_id)
        with self._lock:
            self._active[sid] = span

    def on_end(self, span: ReadableSpan) -> None:
        sid = _fmt_span_id(span.get_span_context().span_id)
        with self._lock:
            self._active.pop(sid, None)
            self._spans.append(self._to_dict(span))

    def shutdown(self) -> None:
        pass

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True

    def active_dicts(self) -> list[dict]:
        with self._lock:
            spans = list(self._active.values())
        return [self._to_dict(s) for s in spans]

    @staticmethod
    def _to_dict(s: ReadableSpan) -> dict:
        ctx = s.get_span_context()
        duration_ms = 0.0
        if s.end_time and s.start_time:
            duration_ms = (s.end_time - s.start_time) / 1_000_000
        error = None
        if s.status and s.status.status_code == StatusCode.ERROR:
            error = s.status.description
        attrs = s.attributes or {}
        # start_span() stores the caller's `service=` kwarg as a span
        # attribute (not on the process-wide Resource, which is fixed to
        # "axon") — read it from there. Falls back to the Resource's own
        # service.name for auto-instrumented spans (e.g. FastAPIInstrumentor's
        # HTTP spans) that don't set this attribute themselves.
        service = (
            attrs.get("service.name")
            or (s.resource.attributes.get("service.name") if s.resource else None)
            or "agentos"
        )
        return {
            "trace_id"   : _fmt_trace_id(ctx.trace_id),
            "span_id"    : _fmt_span_id(ctx.span_id),
            "parent_id"  : _fmt_span_id(s.parent.span_id) if s.parent else None,
            "name"       : s.name,
            "service"    : service,
            "duration_ms": round(duration_ms, 2),
            "tags"       : {k: str(v) for k, v in attrs.items() if k != "service.name"},
            "events"     : [
                {"name": e.name, "ts": e.timestamp / 1_000_000_000, **{k: str(v) for k, v in (e.attributes or {}).items()}}
                for e in (s.events or [])
            ],
            "error"      : error,
        }


def _maybe_otlp_processor():
    """Additionally export to a real OTLP collector when configured — the
    in-memory ring buffer above works identically with or without this."""
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        return None
    try:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        return BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint))
    except Exception as exc:
        log.warning("OTLP exporter configured (%s) but unavailable: %s", endpoint, exc)
        return None


class Tracer:
    """
    Thin facade over the real OpenTelemetry SDK, preserving this module's
    original API.

    Usage:
        tracer = get_tracer()
        with tracer.start_span("agent.run", service="agentos") as span:
            span.set_tag("agent", "build")
            result = await agent.run(ctx)
    """

    def __init__(self) -> None:
        self._processor = _RingBufferProcessor()
        resource = Resource.create({"service.name": "axon"})
        self._provider = TracerProvider(resource=resource)
        self._provider.add_span_processor(self._processor)
        otlp = _maybe_otlp_processor()
        if otlp:
            self._provider.add_span_processor(otlp)
        # Register as the global provider so FastAPIInstrumentor's
        # auto-created HTTP spans (app.factory's instrument_app call) land
        # in the same ring buffer as every manually-created span here —
        # one tracer, not two disconnected ones.
        try:
            otel_trace.set_tracer_provider(self._provider)
        except Exception:
            pass  # already set (e.g. re-instantiated in a test) — non-fatal
        self._otel_tracer = self._provider.get_tracer("axon.observability")

    def start_span(
        self,
        name     : str,
        *,
        service  : str = "agentos",
        trace_id : Optional[str] = None,
        parent_id: Optional[str] = None,
    ) -> SpanHandle:
        parent_ctx = None
        if trace_id:
            # Explicit trace linkage (e.g. an id carried across a durable
            # event-bus message, or grouping multiple root spans under one
            # trace) — reconstruct a SpanContext to use as the parent
            # instead of relying on ambient context. parent_id defaults to
            # a zero span_id (a valid "trace root" reference) when only
            # trace_id is given.
            try:
                tid_int = int(trace_id, 16)
                sid_int = int(parent_id, 16) if parent_id else 0
                sc = SpanContext(
                    trace_id=tid_int,
                    span_id=sid_int,
                    is_remote=True,
                    trace_flags=TraceFlags(TraceFlags.SAMPLED),
                )
                parent_ctx = otel_trace.set_span_in_context(NonRecordingSpan(sc))
            except ValueError:
                log.debug("start_span: trace_id %r is not valid W3C hex — ignoring, using ambient context", trace_id)
        span = self._otel_tracer.start_span(
            name, context=parent_ctx, attributes={"service.name": service},
        )
        return SpanHandle(span)

    def recent(self, n: int = 100) -> list[dict]:
        with self._processor._lock:
            spans = list(self._processor._spans)[-n:]
        return list(reversed(spans))

    def active(self) -> list[dict]:
        return self._processor.active_dicts()

    def trace(self, trace_id: str) -> list[dict]:
        with self._processor._lock:
            return [s for s in self._processor._spans if s["trace_id"] == trace_id]


# ── Singleton ─────────────────────────────────────────────────────────────────

_tracer: Tracer | None = None


def get_tracer() -> Tracer:
    global _tracer
    if _tracer is None:
        _tracer = Tracer()
    return _tracer
