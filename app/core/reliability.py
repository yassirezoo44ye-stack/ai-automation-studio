"""
Generic reliability primitives — circuit breaker + bulkhead.

CircuitBreaker began life in app/ai/circuit_breaker.py guarding AI
providers. Its state machine is domain-agnostic (string-keyed targets), so
it lives here now and the AI module re-exports it — same class, same
module-level singleton over there, zero call-site changes.

Bulkhead bounds in-flight concurrency on hot request paths (chat/inference,
build, workflow runs). Saturation sheds load immediately (BulkheadFull →
HTTP 503 + Retry-After via the factory's exception handler) instead of
queueing unbounded work behind a stalled dependency. Limits are env-tunable:
BULKHEAD_<NAME>_LIMIT.
"""
from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import Enum

log = logging.getLogger(__name__)

_FAILURE_THRESHOLD = 3       # consecutive failures before opening
_COOLDOWN_S        = 30.0    # time before a half-open trial is allowed


class CircuitState(str, Enum):
    CLOSED    = "closed"
    OPEN      = "open"
    HALF_OPEN = "half_open"


@dataclass
class _Circuit:
    state:             CircuitState = CircuitState.CLOSED
    consecutive_fails: int          = 0
    opened_at:         float        = 0.0


class CircuitBreaker:
    """One breaker instance guards many targets, keyed by a string id."""

    def __init__(self, failure_threshold: int = _FAILURE_THRESHOLD,
                 cooldown_s: float = _COOLDOWN_S) -> None:
        self._threshold = failure_threshold
        self._cooldown  = cooldown_s
        self._circuits: dict[str, _Circuit] = {}

    def _get(self, target_id: str) -> _Circuit:
        return self._circuits.setdefault(target_id, _Circuit())

    def allow(self, target_id: str) -> bool:
        """True if a call to this target should be attempted right now."""
        c = self._get(target_id)
        if c.state == CircuitState.CLOSED:
            return True
        if c.state == CircuitState.OPEN:
            if time.time() - c.opened_at >= self._cooldown:
                c.state = CircuitState.HALF_OPEN
                log.info("circuit %s: open -> half_open (cooldown elapsed)", target_id)
                return True
            return False
        return True  # HALF_OPEN: let the probing call through

    def record_success(self, target_id: str) -> None:
        c = self._get(target_id)
        if c.state != CircuitState.CLOSED:
            log.info("circuit %s: %s -> closed (recovered)", target_id, c.state.value)
        c.state = CircuitState.CLOSED
        c.consecutive_fails = 0

    def record_failure(self, target_id: str) -> None:
        c = self._get(target_id)
        c.consecutive_fails += 1
        if c.state == CircuitState.HALF_OPEN:
            c.state = CircuitState.OPEN
            c.opened_at = time.time()
            log.warning("circuit %s: half_open -> open (probe failed)", target_id)
        elif c.state == CircuitState.CLOSED and c.consecutive_fails >= self._threshold:
            c.state = CircuitState.OPEN
            c.opened_at = time.time()
            log.warning("circuit %s: closed -> open (%d consecutive failures)",
                        target_id, c.consecutive_fails)

    def state(self, target_id: str) -> CircuitState:
        return self._get(target_id).state

    def snapshot(self) -> dict[str, dict]:
        """All known circuits — feeds the provider-health API/frontend."""
        return {
            tid: {"state": c.state.value, "consecutive_fails": c.consecutive_fails}
            for tid, c in self._circuits.items()
        }


# ── Bulkhead ──────────────────────────────────────────────────────────────────

class BulkheadFull(Exception):
    """Raised when a bulkhead is saturated — mapped to 503 + Retry-After."""

    def __init__(self, name: str, limit: int, retry_after_s: int = 5) -> None:
        self.name          = name
        self.limit         = limit
        self.retry_after_s = retry_after_s
        super().__init__(f"bulkhead {name!r} saturated ({limit} in flight)")


class Bulkhead:
    """Sheds load instead of queueing: acquire() raises BulkheadFull the
    moment `limit` requests are already in flight. A plain counter, not a
    Semaphore — we never want callers waiting in line here; waiting is
    exactly the failure mode this exists to prevent."""

    def __init__(self, name: str, limit: int) -> None:
        self.name       = name
        self.limit      = limit
        self._in_flight = 0

    @asynccontextmanager
    async def acquire(self):
        if self._in_flight >= self.limit:
            raise BulkheadFull(self.name, self.limit)
        self._in_flight += 1
        try:
            yield
        finally:
            self._in_flight -= 1

    @property
    def in_flight(self) -> int:
        return self._in_flight


_bulkheads: dict[str, Bulkhead] = {}


def get_bulkhead(name: str, default_limit: int) -> Bulkhead:
    """Named singleton bulkheads; limit overridable per deployment via
    BULKHEAD_<NAME>_LIMIT (e.g. BULKHEAD_AI_LIMIT=64)."""
    if name not in _bulkheads:
        limit = int(os.getenv(f"BULKHEAD_{name.upper()}_LIMIT", str(default_limit)))
        _bulkheads[name] = Bulkhead(name, limit)
    return _bulkheads[name]


def compute_backoff_delay(
    attempt: int, base_delay: float, max_delay: float = 30.0, *, jitter: bool = True,
) -> float:
    """Exponential backoff with optional jitter — the actual formula shared
    by app/ai/retries.py's with_retry (AI-provider retry policy: broad
    exception handling, terminal-error short-circuit, per-attempt timeout)
    and app/core/maintenance.py's with_retry (DB/OS retry policy: narrow
    exception whitelist, args passthrough, error-counter side effect).

    Those two are deliberately NOT merged into one function — their retry-
    eligibility policies differ in ways that matter for correctness (the DB
    version retrying on arbitrary exceptions would silently mask real bugs
    as "transient"). This is the one piece of math that was actually
    duplicated between them."""
    delay = base_delay * (2 ** attempt)
    if jitter:
        import random
        delay += random.uniform(0, 0.5)
    return min(delay, max_delay)


def bulkhead_snapshot() -> dict[str, dict]:
    return {
        n: {"limit": b.limit, "in_flight": b.in_flight}
        for n, b in _bulkheads.items()
    }
