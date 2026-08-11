"""Structured logging setup.

Hard rule: never log passwords, access tokens, refresh tokens, or CSRF tokens.
`redact` is applied to any field name that looks sensitive before it reaches a log
sink, as a last line of defense on top of "just don't pass them in".
"""
from __future__ import annotations

import logging
import sys

import structlog

_SENSITIVE_KEYS = {
    "password",
    "access_token",
    "refresh_token",
    "token",
    "authorization",
    "csrf_token",
    "token_hash",
    "secret",
}


def _redact_sensitive(_logger: object, _method_name: str, event_dict: dict) -> dict:
    for key in list(event_dict.keys()):
        if key.lower() in _SENSITIVE_KEYS:
            event_dict[key] = "***REDACTED***"
    return event_dict


def configure_logging(*, json_logs: bool = True, level: str = "INFO") -> None:
    logging.basicConfig(stream=sys.stdout, level=level, format="%(message)s")

    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        _redact_sensitive,
    ]

    structlog.configure(
        processors=shared_processors
        + [
            structlog.processors.JSONRenderer()
            if json_logs
            else structlog.dev.ConsoleRenderer()
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level)),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
