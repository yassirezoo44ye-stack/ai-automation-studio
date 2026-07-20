"""
Retry/resilience for integrations — a thin, named instance of the
EXISTING generic CircuitBreaker (app/core/reliability.py), not a
reimplementation. Targets are keyed "{provider_id}:{organization_id}"
so one org's failing connection can't trip the breaker for every other
org using the same provider.
"""
from __future__ import annotations

from app.core.reliability import CircuitBreaker

_breaker: CircuitBreaker | None = None


def get_integration_circuit_breaker() -> CircuitBreaker:
    global _breaker
    if _breaker is None:
        _breaker = CircuitBreaker()
    return _breaker


def is_connection_allowed(provider_id: str, organization_id: str) -> bool:
    """False when the breaker is open for this connection — callers
    (sync_engine, webhook dispatch) should skip the call and surface
    IntegrationStatus.DEGRADED instead of hammering a known-failing target."""
    return get_integration_circuit_breaker().allow(f"{provider_id}:{organization_id}")
