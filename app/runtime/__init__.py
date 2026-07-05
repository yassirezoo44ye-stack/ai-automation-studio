"""
app.runtime — Runtime Platform

Single source of truth for tool detection, process launching, capability
flags, pre-flight validation, and diagnostics.

Public surface
--------------
from app.runtime import registry      # has(), get(), best_python(), to_dict()
from app.runtime import capabilities  # get() → Capabilities, compute()
from app.runtime import process       # stream_process(), run_process(), start_persistent()
from app.runtime import preflight     # run_preflight(), preflight_error_events()
from app.runtime import diagnostics   # generate() → HealthReport

Startup sequence (called by app/main.py)
-----------------------------------------
await registry.discover()   # probe all runtimes
capabilities.compute()      # derive capability flags
"""
from app.runtime import registry, capabilities, process, preflight, diagnostics

__all__ = ["registry", "capabilities", "process", "preflight", "diagnostics"]
