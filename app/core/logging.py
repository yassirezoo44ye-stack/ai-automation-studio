"""
Structured JSON logging for production observability.

Usage:
    from app.core.logging import get_logger, log_request
    logger = get_logger(__name__)
    logger.info("event", user="foo@bar.com", action="chat_run")
"""
import json
import logging
import sys
import time
import uuid
from contextvars import ContextVar
from typing import Any

# Per-request context so logs emitted deep in call stacks carry the request ID.
_request_id_var: ContextVar[str] = ContextVar("request_id", default="")


def get_request_id() -> str:
    return _request_id_var.get()


def set_request_id(rid: str) -> None:
    _request_id_var.set(rid)


class SensitiveDataFilter:
    """
    Scrubs known secret patterns and password/token/secret-like field names
    from log payloads before they're serialized. Reuses the same regex
    patterns already used to scan files for leaked secrets — not
    reimplemented — from app.marketplace.security and
    app.services.security_monitor. Imports are deferred to first use since
    this module (app.core.logging) is loaded very early in the app's
    import graph, before those modules exist.
    """
    _REDACTED = "***REDACTED***"
    _SENSITIVE_KEYS = frozenset({
        "password", "passwd", "api_key", "apikey", "token", "access_token",
        "refresh_token", "authorization", "secret", "client_secret",
        "session_cookie", "cookie", "private_key", "jwt",
    })

    def __init__(self) -> None:
        self._patterns = self._load_patterns()

    @staticmethod
    def _load_patterns() -> list:
        patterns = []
        try:
            from app.marketplace.security import _SECRET_PATTERNS as _mp_patterns
            patterns.extend(rx for _, rx in _mp_patterns)
        except Exception:
            pass
        try:
            from app.services.security_monitor import _SECRET_PATTERNS as _sm_patterns
            patterns.extend(_sm_patterns)
        except Exception:
            pass
        return patterns

    def scrub_text(self, text: str) -> str:
        if not isinstance(text, str) or not text:
            return text
        for rx in self._patterns:
            text = rx.sub(self._REDACTED, text)
        return text

    def scrub_value(self, key: str, value: Any) -> Any:
        if isinstance(value, str):
            if key.lower() in self._SENSITIVE_KEYS:
                return self._REDACTED
            return self.scrub_text(value)
        return value


_sensitive_filter: "SensitiveDataFilter | None" = None


def _get_sensitive_filter() -> SensitiveDataFilter:
    global _sensitive_filter
    if _sensitive_filter is None:
        _sensitive_filter = SensitiveDataFilter()
    return _sensitive_filter


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        sdf = _get_sensitive_filter()
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": sdf.scrub_text(record.getMessage()),
        }
        rid = get_request_id()
        if rid:
            payload["request_id"] = rid
        # Extra fields attached via logger.info("msg", extra={...})
        for key, val in record.__dict__.items():
            if key not in (
                "name", "msg", "args", "created", "filename", "funcName",
                "levelname", "levelno", "lineno", "module", "msecs",
                "pathname", "process", "processName", "relativeCreated",
                "thread", "threadName", "stack_info", "exc_info", "exc_text",
                "message",
            ):
                payload[key] = sdf.scrub_value(key, val)
        if record.exc_info:
            payload["exc"] = sdf.scrub_text(self.formatException(record.exc_info))
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    """Call once at startup to switch all handlers to JSON output."""
    root = logging.getLogger()
    root.setLevel(level)
    for h in root.handlers[:]:
        root.removeHandler(h)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter())
    root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
