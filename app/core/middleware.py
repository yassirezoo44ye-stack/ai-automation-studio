"""
Production middleware stack:
  - RequestIdMiddleware         — stamps every request/response with X-Request-Id
  - AccessLogMiddleware         — structured JSON access log (method, path, status, ms)
  - UploadBodySizeLimitMiddleware — enforces 200 MB cap on POST .../upload at the
                                    ASGI receive level (before the endpoint reads data)
"""
import re
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


_UPLOAD_PATH_RE = re.compile(r"^/api/projects/[^/]+/upload$")
_UPLOAD_BODY_LIMIT = 200 * 1024 * 1024  # 200 MB — must match build.py constant


class UploadBodySizeLimitMiddleware:
    """
    Pure-ASGI middleware that enforces a hard 200 MB cap on upload requests
    before the endpoint reads any data into memory.

    Two enforcement layers:
      1. Content-Length header present → 413 before reading a single byte.
      2. Chunked / no Content-Length → wrap the ASGI receive() so cumulative
         bytes are counted; sends 413 and returns a disconnect to the app the
         moment the running total exceeds the limit.

    Only active on POST /api/projects/{id}/upload.  All other paths, methods,
    and WebSocket scopes are passed through untouched.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") != "POST":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        study_upload = path == "/api/study-library/lessons"
        if not _UPLOAD_PATH_RE.match(path) and not study_upload:
            await self.app(scope, receive, send)
            return
        body_limit = 11 * 1024 * 1024 if study_upload else _UPLOAD_BODY_LIMIT

        # --- Fast path: Content-Length declared ---
        raw_headers = dict(scope.get("headers", []))
        cl_bytes = raw_headers.get(b"content-length", b"")
        if cl_bytes:
            try:
                if int(cl_bytes) > body_limit:
                    await _send_413(send, study_upload)
                    return
            except ValueError:
                pass  # malformed Content-Length — let the endpoint handle it

        # --- Slow path: count bytes as they stream in ---
        state = {"seen": 0, "rejected": False}

        async def limited_receive():
            if state["rejected"]:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                state["seen"] += len(message.get("body", b""))
                if state["seen"] > body_limit:
                    state["rejected"] = True
                    await _send_413(send, study_upload)  # before app touches send
                    return {"type": "http.disconnect"}
            return message

        async def guarded_send(message):
            # Silently drop the app's response if we already sent 413.
            if state["rejected"]:
                return
            await send(message)

        try:
            await self.app(scope, limited_receive, guarded_send)
        except Exception as exc:
            if not state["rejected"]:
                raise
            # We sent 413 and returned http.disconnect; the app raises
            # ClientDisconnect when it tries to read more body.  Swallow
            # that expected disconnect.  Any other exception is unexpected
            # (e.g. a DB error after partial body read); log it but don't
            # re-raise — we already committed a 413 response to the client.
            from starlette.requests import ClientDisconnect  # local import avoids circular
            if not isinstance(exc, ClientDisconnect):
                _log.warning(
                    "upload_limit: unexpected exception after 413 rejection",
                    extra={"exc_type": type(exc).__name__, "exc": str(exc)},
                )


async def _send_413(send, study_upload=False):
    body = (b'{"detail":"Study upload request body exceeds the 11 MiB limit"}' if study_upload
            else b'{"detail":"Upload request body exceeds the 200 MB limit"}')
    await send({
        "type": "http.response.start",
        "status": 413,
        "headers": [
            [b"content-type", b"application/json"],
            [b"content-length", str(len(body)).encode()],
        ],
    })
    await send({"type": "http.response.body", "body": body})


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
