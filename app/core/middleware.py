"""
Production middleware stack:
  - RequestIdMiddleware  — stamps every request/response with X-Request-Id
  - AccessLogMiddleware  — structured JSON access log (method, path, status, ms)
"""
import random
import time
import uuid

from opentelemetry import trace as otel_trace
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.core.logging import get_logger, set_request_id

_log = get_logger("axon.access")


def _active_trace_id() -> str:
    """The current OTel span's trace_id, W3C 32-hex — the same format
    app/core/observability/tracer.py already produces. Used so a request's
    request_id, its access-log line, and its /api/diagnostics/traces entry
    all share one canonical ID instead of independently-generated ones.
    Returns "" when tracing is disabled or no span is active, so callers
    fall back to a fresh uuid4 exactly as before."""
    ctx = otel_trace.get_current_span().get_span_context()
    return format(ctx.trace_id, "032x") if ctx.is_valid else ""


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("X-Request-Id") or _active_trace_id() or str(uuid.uuid4())
        set_request_id(rid)
        response = await call_next(request)
        response.headers["X-Request-Id"] = rid
        return response


class AccessLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.monotonic()
        response = await call_next(request)
        duration_ms = round((time.monotonic() - start) * 1000, 1)

        # Optional sampling (OBS_SAMPLING_RATE, default 1.0 = log every
        # request — never drop data unless explicitly configured to).
        # Errors are always logged regardless of sampling: dropping error
        # visibility to save log volume would defeat the point of sampling.
        from app.core.observability.config import get_observability_config
        rate = get_observability_config().sampling_rate
        if response.status_code >= 500 or rate >= 1.0 or random.random() < rate:
            _log.info(
                "request",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "ms": duration_ms,
                },
            )
        return response
