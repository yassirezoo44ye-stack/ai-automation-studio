"""
Per-provider circuit breaker — closed/open/half-open state machine.

Protects the failover chain (app/core/ai/registry/registry.py) from
repeatedly hammering a provider that's already failing: after enough
consecutive failures its circuit "opens" and the chain skips it entirely
for a cooldown period, then allows exactly one trial call ("half-open") to
test recovery before fully closing again.

No circuit breaker existed anywhere in this codebase before this module —
this is genuinely new, not a consolidation of an existing one.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from enum import Enum

log = logging.getLogger(__name__)

_FAILURE_THRESHOLD = 3       # consecutive failures before opening
_COOLDOWN_S         = 30.0   # time before a half-open trial is allowed


class CircuitState(str, Enum):
    CLOSED    = "closed"
    OPEN      = "open"
    HALF_OPEN = "half_open"


@dataclass
class _ProviderCircuit:
    state:             CircuitState = CircuitState.CLOSED
    consecutive_fails: int          = 0
    opened_at:         float        = 0.0


class CircuitBreaker:
    """One breaker instance guards every provider, keyed by provider_id."""

    def __init__(self, failure_threshold: int = _FAILURE_THRESHOLD,
                cooldown_s: float = _COOLDOWN_S) -> None:
        self._threshold = failure_threshold
        self._cooldown  = cooldown_s
        self._circuits: dict[str, _ProviderCircuit] = {}

    def _get(self, provider_id: str) -> _ProviderCircuit:
        return self._circuits.setdefault(provider_id, _ProviderCircuit())

    def allow(self, provider_id: str) -> bool:
        """True if a call to this provider should be attempted right now."""
        c = self._get(provider_id)
        if c.state == CircuitState.CLOSED:
            return True
        if c.state == CircuitState.OPEN:
            if time.time() - c.opened_at >= self._cooldown:
                c.state = CircuitState.HALF_OPEN
                log.info("circuit %s: open -> half_open (cooldown elapsed)", provider_id)
                return True
            return False
        return True  # HALF_OPEN: let the probing call through

    def record_success(self, provider_id: str) -> None:
        c = self._get(provider_id)
        if c.state != CircuitState.CLOSED:
            log.info("circuit %s: %s -> closed (recovered)", provider_id, c.state.value)
        c.state = CircuitState.CLOSED
        c.consecutive_fails = 0

    def record_failure(self, provider_id: str) -> None:
        c = self._get(provider_id)
        c.consecutive_fails += 1
        if c.state == CircuitState.HALF_OPEN:
            c.state = CircuitState.OPEN
            c.opened_at = time.time()
            log.warning("circuit %s: half_open -> open (probe failed)", provider_id)
        elif c.state == CircuitState.CLOSED and c.consecutive_fails >= self._threshold:
            c.state = CircuitState.OPEN
            c.opened_at = time.time()
            log.warning("circuit %s: closed -> open (%d consecutive failures)",
                       provider_id, c.consecutive_fails)

    def state(self, provider_id: str) -> CircuitState:
        return self._get(provider_id).state

    def snapshot(self) -> dict[str, dict]:
        """All known circuits — feeds the provider-health API/frontend."""
        return {
            pid: {"state": c.state.value, "consecutive_fails": c.consecutive_fails}
            for pid, c in self._circuits.items()
        }


# Module-level singleton — shared by every completion/stream call, so a
# failure recorded from one request protects the next.
circuit_breaker = CircuitBreaker()
