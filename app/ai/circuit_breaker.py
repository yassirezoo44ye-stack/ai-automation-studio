"""
Per-provider circuit breaker — closed/open/half-open state machine.

Protects the failover chain (app/core/ai/registry/registry.py) from
repeatedly hammering a provider that's already failing: after enough
consecutive failures its circuit "opens" and the chain skips it entirely
for a cooldown period, then allows exactly one trial call ("half-open") to
test recovery before fully closing again.

The state machine itself is domain-agnostic and now lives in
app/core/reliability.py (the Performance & Reliability phase generalized
it for reuse by non-AI callers) — this module keeps its original public
surface (CircuitBreaker, CircuitState, the `circuit_breaker` singleton) so
every existing AI call site works unchanged.
"""
from app.core.reliability import CircuitBreaker, CircuitState

__all__ = ["CircuitBreaker", "CircuitState", "circuit_breaker"]

# Module-level singleton — shared by every completion/stream call, so a
# failure recorded from one request protects the next.
circuit_breaker = CircuitBreaker()
