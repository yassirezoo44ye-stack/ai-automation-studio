"""
Backward-compat shim — all functionality now lives in app.runtime.preflight.
Existing imports continue to work unchanged.
"""
from app.runtime.preflight import (  # noqa: F401
    ToolCheck,
    PreflightResult,
    run_preflight,
    preflight_error_events,
)
