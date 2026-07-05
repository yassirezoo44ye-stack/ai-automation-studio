"""
Runtime Capabilities — derived feature flags computed from the registry.

Callers ask "can I do X?" instead of "is tool Y present?". Capabilities
are computed once after discovery and cached.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

from app.runtime import registry


@dataclass
class Capabilities:
    # ── Python ──────────────────────────────────────────────────────
    can_run_python: bool       # python / python3 on PATH
    can_run_fastapi: bool      # python present (uvicorn pip-installed on demand)
    can_run_flask: bool        # python present
    can_build_exe: bool        # python present (PyInstaller via pip)

    # ── Node ────────────────────────────────────────────────────────
    can_run_node: bool         # node on PATH
    can_run_react: bool        # node + npm on PATH
    can_build_electron: bool   # node + npm on PATH

    # ── Android ─────────────────────────────────────────────────────
    can_build_apk: bool        # java + ANDROID_HOME (or ANDROID_SDK_ROOT)
    can_build_python_apk: bool # python + java + android sdk (BeeWare Briefcase)
    can_build_web_apk: bool    # node + npm + npx + java + android sdk (Capacitor)

    # ── Java ────────────────────────────────────────────────────────
    can_run_java: bool         # java on PATH

    def to_dict(self) -> dict:
        return asdict(self)


_capabilities: Capabilities | None = None


def compute() -> Capabilities:
    """Compute capabilities from current registry state. Idempotent."""
    global _capabilities

    python_ok  = registry.has("python") or registry.has("python3")
    node_ok    = registry.has("node")
    npm_ok     = registry.has("npm")
    npx_ok     = registry.has("npx")
    java_ok    = registry.has("java")
    android_ok = registry.has_env("ANDROID_HOME") or registry.has_env("ANDROID_SDK_ROOT")

    _capabilities = Capabilities(
        can_run_python       = python_ok,
        can_run_fastapi      = python_ok,
        can_run_flask        = python_ok,
        can_build_exe        = python_ok,
        can_run_node         = node_ok,
        can_run_react        = node_ok and npm_ok,
        can_build_electron   = node_ok and npm_ok,
        can_build_apk        = java_ok and android_ok,
        can_build_python_apk = python_ok and java_ok and android_ok,
        can_build_web_apk    = node_ok and npm_ok and npx_ok and java_ok and android_ok,
        can_run_java         = java_ok,
    )
    return _capabilities


def get() -> Capabilities:
    """Return cached capabilities. Falls back to computing if not yet done."""
    if _capabilities is None:
        return compute()
    return _capabilities
