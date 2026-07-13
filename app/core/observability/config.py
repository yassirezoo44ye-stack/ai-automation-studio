"""
ObservabilityConfig — every observability feature flag as an environment
variable. Toggling is "flip an env var and restart," not a code change,
per this phase's own requirement. No database-backed flag system: there's
no existing precedent for one in this codebase, and a per-request DB
lookup to check a flag would itself be the kind of overhead this phase's
performance budget warns against.

Properties read the environment live (not cached at import/startup time)
— cheap (a single os.getenv call), and it means tests can toggle a flag
via monkeypatch without needing to reset a cached singleton.
"""
from __future__ import annotations

import os


def _bool_env(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() not in ("false", "0", "no", "off")


class ObservabilityConfig:
    @property
    def tracing_enabled(self) -> bool:
        return _bool_env("OBS_TRACING_ENABLED", True)

    @property
    def metrics_enabled(self) -> bool:
        return _bool_env("OBS_METRICS_ENABLED", True)

    @property
    def audit_enabled(self) -> bool:
        return _bool_env("OBS_AUDIT_ENABLED", True)

    @property
    def alerts_enabled(self) -> bool:
        return _bool_env("OBS_ALERTS_ENABLED", True)

    @property
    def sampling_rate(self) -> float:
        """Fraction of access-log lines actually emitted. 1.0 (the
        default) logs every request — never drop data unless explicitly
        configured to."""
        try:
            rate = float(os.getenv("OBS_SAMPLING_RATE", "1.0"))
        except ValueError:
            return 1.0
        return max(0.0, min(rate, 1.0))


_config: ObservabilityConfig | None = None


def get_observability_config() -> ObservabilityConfig:
    global _config
    if _config is None:
        _config = ObservabilityConfig()
    return _config
