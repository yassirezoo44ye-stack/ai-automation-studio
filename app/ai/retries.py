"""
Retry and timeout helpers for AI provider calls.
Uses exponential backoff with jitter.
"""
from __future__ import annotations

import asyncio
import logging
import random
from typing import Callable, TypeVar, Awaitable

log = logging.getLogger(__name__)

T = TypeVar("T")

# Errors that are worth retrying (transient)
_RETRYABLE_CODES = {429, 500, 502, 503, 504}

# Errors that indicate a billing / auth problem — don't retry
_TERMINAL_MESSAGES = ("invalid api key", "insufficient_quota", "billing")


def _is_retryable(exc: Exception) -> bool:
    """Return True if the exception is likely transient."""
    msg = str(exc).lower()
    if any(t in msg for t in _TERMINAL_MESSAGES):
        return False
    # HTTP status code embedded in message
    for code in _RETRYABLE_CODES:
        if str(code) in msg:
            return True
    return True  # default: retry unknown errors


async def with_retry(
    fn: Callable[[], Awaitable[T]],
    *,
    max_retries: int = 2,
    base_delay:  float = 1.0,
    max_delay:   float = 30.0,
    timeout:     float = 60.0,
) -> T:
    """
    Call `fn` with exponential backoff retries and a per-attempt timeout.

    Raises the last exception if all attempts fail.
    """
    last_exc: Exception = RuntimeError("No attempts made")

    for attempt in range(max_retries + 1):
        try:
            return await asyncio.wait_for(fn(), timeout=timeout)
        except asyncio.TimeoutError as exc:
            last_exc = TimeoutError(f"AI request timed out after {timeout}s")
            log.warning("Attempt %d/%d timed out", attempt + 1, max_retries + 1)
        except Exception as exc:
            last_exc = exc
            if not _is_retryable(exc):
                log.warning("Non-retryable error: %s", exc)
                raise
            log.warning(
                "Attempt %d/%d failed: %s",
                attempt + 1, max_retries + 1, exc,
            )

        if attempt < max_retries:
            delay = min(base_delay * (2 ** attempt) + random.uniform(0, 0.5), max_delay)
            log.debug("Retrying in %.2fs", delay)
            await asyncio.sleep(delay)

    raise last_exc
