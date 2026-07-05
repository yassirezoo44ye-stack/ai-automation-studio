"""
RuntimeControlPlane — Phase 1.

The single, authoritative facade for all runtime capability queries.

API
---
  runtime.can(tool)          → bool
  runtime.require(tool)      → raises StructuredRuntimeError if missing
  runtime.getCapabilities()  → dict  (same schema as /api/runtime/capabilities)

No other module should call shutil.which() or subprocess to probe tools.
All queries go through this object (backed by app.runtime.registry which
ran discover() at startup).
"""
from __future__ import annotations

from app.runtime import capabilities, registry
from app.runtime.errors import StructuredRuntimeError

# Human-readable fix hints per tool — kept here so they stay consistent
# across every error message the system emits.
_FIX_HINTS: dict[str, list[str]] = {
    "python":  [
        "Install Python 3.11+ from https://python.org",
        "Ensure 'python3' (Linux/macOS) or 'python' (Windows) is on PATH",
    ],
    "python3": [
        "Install Python 3.11+ from https://python.org",
        "Ensure 'python3' is on PATH",
    ],
    "node": [
        "Install Node.js 20 LTS from https://nodejs.org",
        "Restart the server after installation",
    ],
    "npm": [
        "npm ships with Node.js — reinstall Node.js 20 LTS",
        "Or run: npm install -g npm@latest",
    ],
    "npx": [
        "npx ships with Node.js 5.2+ — update Node.js to 20 LTS",
    ],
    "uvicorn": [
        "pip install uvicorn",
        "Or add 'uvicorn' to your project's requirements.txt",
    ],
    "fastapi": [
        "pip install fastapi",
        "Or add 'fastapi' to your project's requirements.txt",
    ],
    "docker": [
        "Install Docker Desktop from https://docker.com",
        "Ensure the Docker daemon is running",
    ],
    "gradle": [
        "Install Gradle from https://gradle.org",
        "Or install Android Studio which bundles Gradle",
    ],
    "java": [
        "Install JDK 17+ from https://adoptium.net (Eclipse Temurin)",
        "Set JAVA_HOME to the JDK installation directory",
    ],
}

_DEFAULT_FIX = ["Install the tool and ensure it is on PATH", "Restart the server after installation"]


class RuntimeControlPlane:
    """
    Thin, stateless facade over app.runtime.registry.

    All state lives in the registry module-level cache populated by
    registry.discover() at startup. This class adds typed methods and
    structured error production on top.
    """

    # ── Primary API ───────────────────────────────────────────────────────────

    def can(self, tool: str) -> bool:
        """Return True if *tool* is available on this machine."""
        return registry.has(tool)

    def require(self, tool: str) -> None:
        """
        Assert that *tool* is available.

        Raises StructuredRuntimeError (never FileNotFoundError) if missing.
        Callers convert this to an SSE error via exc.to_sse().
        """
        if not registry.has(tool):
            fix = _FIX_HINTS.get(tool, _DEFAULT_FIX)
            raise StructuredRuntimeError(tool, fix)

    def getCapabilities(self) -> dict:
        """Return derived capability flags (same payload as /api/runtime/capabilities)."""
        return capabilities.get().to_dict()

    # ── Convenience helpers used by drivers ───────────────────────────────────

    def best_python(self) -> str:
        """Return whichever of python3/python is available (prefers python3)."""
        return registry.best_python()

    def info(self, tool: str):
        """Return RuntimeInfo for a tool, or None if unknown."""
        return registry.get(tool)

    def available_tools(self) -> list[str]:
        """Return names of all tools currently on PATH."""
        return [n for n, r in registry.to_dict().items() if r.get("available")]

    def fix_hints(self, tool: str) -> list[str]:
        """Return installation hints for a named tool."""
        return _FIX_HINTS.get(tool, _DEFAULT_FIX)


# Module-level singleton — import this directly: `from app.runtime.control_plane import runtime`
runtime = RuntimeControlPlane()
