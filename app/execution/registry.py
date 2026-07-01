"""
Runtime Registry — discovers available executables once at server startup.
Results are cached module-level; drivers query has() per request.
"""
from __future__ import annotations

import asyncio
import logging
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

_PROBE_TARGETS = [
    "python3", "python", "node", "npm", "npx", "pnpm", "bun",
    "uvicorn", "java", "cargo", "go", "ruby", "php", "deno",
]


async def discover() -> None:
    """Probe all runtimes concurrently. Call once at app startup."""
    infos = await asyncio.gather(
        *[_probe(n) for n in _PROBE_TARGETS],
        return_exceptions=True,
    )
    for name, info in zip(_PROBE_TARGETS, infos):
        _registry[name] = (
            info if isinstance(info, RuntimeInfo)
            else RuntimeInfo(name=name, available=False)
        )
    available = [n for n, r in _registry.items() if r.available]
    log.info("Runtime registry ready. Available: %s", available)


async def _probe(name: str) -> RuntimeInfo:
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


def has(name: str) -> bool:
    """Return True if the runtime is available. 'python' also checks 'python3'."""
    if _registry.get(name, RuntimeInfo(name, False)).available:
        return True
    if name == "python":
        return _registry.get("python3", RuntimeInfo("python3", False)).available
    return False


def best_python() -> str:
    """Return whichever of python3/python is available."""
    return "python3" if has("python3") else "python"


def get(name: str) -> Optional[RuntimeInfo]:
    return _registry.get(name)


def to_dict() -> dict:
    return {
        n: {"available": r.available, "version": r.version}
        for n, r in _registry.items()
    }
