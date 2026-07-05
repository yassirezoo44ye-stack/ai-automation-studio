"""
Runtime Registry — discovers available executables once at server startup.
Results are cached module-level; all callers query has() / get() / best_python().

This is the single source of truth for tool availability across the entire
application. No other module should call shutil.which() or probe executables
directly — query this module instead.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger(__name__)


@dataclass
class RuntimeInfo:
    name: str
    available: bool
    path: Optional[str] = None
    version: Optional[str] = None


_registry: dict[str, RuntimeInfo] = {}
_env_registry: dict[str, bool] = {}

_PROBE_TARGETS = [
    "python3", "python", "node", "npm", "npx", "pnpm", "bun",
    "uvicorn", "java", "javac", "gradle", "cargo", "go", "ruby", "php", "deno",
]

_ENV_TARGETS = ["ANDROID_HOME", "ANDROID_SDK_ROOT", "JAVA_HOME"]


async def discover() -> None:
    """Probe all runtimes concurrently. Call once at application startup."""
    infos = await asyncio.gather(
        *[_probe(n) for n in _PROBE_TARGETS],
        return_exceptions=True,
    )
    for name, info in zip(_PROBE_TARGETS, infos):
        _registry[name] = (
            info if isinstance(info, RuntimeInfo)
            else RuntimeInfo(name=name, available=False)
        )

    for env_key in _ENV_TARGETS:
        _env_registry[env_key] = bool(os.environ.get(env_key))

    available = [n for n, r in _registry.items() if r.available]
    log.info("Runtime registry ready. Available: %s", available)


async def _probe(name: str) -> RuntimeInfo:
    """Probe a single executable: check PATH, then get its --version."""
    path = shutil.which(name)
    if not path:
        return RuntimeInfo(name=name, available=False)
    try:
        proc = await asyncio.create_subprocess_exec(
            name, "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await asyncio.wait_for(proc.communicate(), timeout=3.0)
        version = (out or err).decode("utf-8", errors="replace").strip().split("\n")[0][:80]
    except Exception:
        version = None
    return RuntimeInfo(name=name, available=True, path=path, version=version)


# ── Public query API ─────────────────────────────────────────────────────────

def has(name: str) -> bool:
    """Return True if the runtime is available. 'python' also checks 'python3'."""
    if _registry.get(name, RuntimeInfo(name, False)).available:
        return True
    if name == "python":
        return _registry.get("python3", RuntimeInfo("python3", False)).available
    return False


def best_python() -> str:
    """Return whichever of python3/python is available (prefers python3)."""
    return "python3" if has("python3") else "python"


def get(name: str) -> Optional[RuntimeInfo]:
    """Return RuntimeInfo for a tool, or None if unknown."""
    return _registry.get(name)


def has_env(key: str) -> bool:
    """Return True if the environment variable is set and non-empty."""
    return _env_registry.get(key, False)


def to_dict() -> dict:
    """Serialize the full registry for API responses / diagnostics."""
    result: dict = {
        n: {"available": r.available, "path": r.path, "version": r.version}
        for n, r in _registry.items()
    }
    for key in _ENV_TARGETS:
        result[key] = {
            "available": _env_registry.get(key, False),
            "path": os.environ.get(key),
            "version": None,
        }
    return result
