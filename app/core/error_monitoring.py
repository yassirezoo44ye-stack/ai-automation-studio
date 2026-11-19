"""Optional error monitoring (Sentry).

Disabled unless ``SENTRY_DSN`` is set, so local dev, tests and deployments
without an account behave exactly as before. ``sentry-sdk`` is imported
lazily: a missing package logs a warning instead of breaking startup.

Privacy: ``send_default_pii`` is off and request bodies are never attached,
so prompts, passwords and tokens are not sent to Sentry.
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)

_enabled = False


def _float_env(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError:
        return default
    return min(max(value, 0.0), 1.0)


def init_error_monitoring() -> bool:
    """Initialise Sentry when ``SENTRY_DSN`` is configured. Returns True if enabled."""
    global _enabled
    dsn = os.getenv("SENTRY_DSN", "").strip()
    if not dsn:
        _enabled = False
        return False
    try:
        import sentry_sdk
    except ImportError:
        log.warning("SENTRY_DSN is set but sentry-sdk is not installed — error monitoring disabled")
        _enabled = False
        return False

    sentry_sdk.init(
        dsn=dsn,
        environment=os.getenv("ENVIRONMENT", "production").strip().lower(),
        release=os.getenv("RENDER_GIT_COMMIT") or None,
        send_default_pii=False,
        max_request_body_size="never",
        traces_sample_rate=_float_env("SENTRY_TRACES_SAMPLE_RATE", 0.0),
    )
    _enabled = True
    log.info("error monitoring enabled (Sentry)")
    return True


def is_enabled() -> bool:
    return _enabled


def capture_exception(exc: BaseException) -> None:
    """Report an exception if monitoring is enabled. Never raises."""
    if not _enabled:
        return
    try:
        import sentry_sdk

        sentry_sdk.capture_exception(exc)
    except Exception:  # monitoring must never break request handling
        log.debug("failed to report exception to Sentry", exc_info=True)
