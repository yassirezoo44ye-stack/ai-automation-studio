"""
Backward-compat shim — all functionality now lives in app.runtime.registry.
Existing imports of 'from app.execution import registry' continue to work.
"""
from app.runtime.registry import (  # noqa: F401
    RuntimeInfo,
    discover,
    has,
    best_python,
    get,
    has_env,
    to_dict,
)
