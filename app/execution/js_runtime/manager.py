"""
RuntimeManager — the single public interface for JavaScript project execution.

External callers (drivers, routers) only ever touch this class.
The rest of the runtime layer (detector, adapters, resolver, validator)
is an internal implementation detail that the manager orchestrates.

Usage:
    manager = RuntimeManager()

    # Resolve which PM to use (cached):
    result = manager.detect(ws)
    print(result.adapter.name, result.method, result.evidence)

    # Install dependencies:
    ok, log_lines = await manager.install(ws)

    # Run a named script and collect all output:
    rc, stdout, stderr = await manager.run_script(ws, "build", timeout=180)

    # Get the argv for a server start command (for process_mgr):
    argv = manager.server_argv(ws, port=8100)

    # Validate before execution:
    report = manager.validate(ws, script="dev")
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional

from app.runtime import process as rt_process

from .detector import DetectionResult, PackageManagerDetector
from .errors import (
    ExecutionFailed,
    ExecutionTimeout,
    JsRuntimeError,
    PackageJsonMissing,
    ScriptNotFound,
)
from .resolver import ScriptResolver
from .validator import ValidationReport, WorkspaceValidator

log = logging.getLogger(__name__)

# Default timeouts (seconds)
_INSTALL_TIMEOUT = 120.0
_SCRIPT_TIMEOUT  = 180.0

# Scripts tried in order for "start server" resolution
_START_PREFERENCE = ("start", "dev", "serve", "preview")
_ENTRY_CANDIDATES = (
    "index.js", "server.js", "app.js", "main.js",
    "src/index.js", "src/server.js",
)


class RuntimeManager:
    """
    Orchestrates package manager detection, validation, and execution.

    One instance is sufficient for the entire application lifetime.
    All mutable state is held in the caches inside the detector.
    """

    def __init__(self) -> None:
        self._detector  = PackageManagerDetector()
        self._resolver  = ScriptResolver()
        self._validator = WorkspaceValidator()

    # ── Detection ─────────────────────────────────────────────────────────────

    def detect(self, ws: Path) -> DetectionResult:
        """Return the detected package manager for this workspace (cached)."""
        return self._detector.detect(ws)

    # ── Validation ────────────────────────────────────────────────────────────

    def validate(
        self,
        ws: Path,
        *,
        script: Optional[str] = None,
        require_modules: bool = False,
    ) -> ValidationReport:
        """Run pre-execution checks and return a ValidationReport."""
        return self._validator.validate(ws, script=script, require_modules=require_modules)

    # ── Script resolution ─────────────────────────────────────────────────────

    def list_scripts(self, ws: Path) -> dict[str, str]:
        """Return all scripts from package.json, or {} if missing."""
        return self._resolver.list_scripts(ws)

    def resolve_start_script(self, ws: Path) -> Optional[str]:
        """Return the best server start script name, or None."""
        return self._resolver.resolve_start(ws)

    def resolve_build_script(self, ws: Path) -> Optional[str]:
        """Return the build script name, or None."""
        return self._resolver.resolve_build(ws)

    # ── Execution ─────────────────────────────────────────────────────────────

    async def install(
        self, ws: Path, *, timeout: float = _INSTALL_TIMEOUT
    ) -> tuple[bool, list[str]]:
        """
        Install dependencies in `ws` using the detected package manager.

        Returns:
            (success: bool, log_lines: list[str])
        """
        try:
            result = self.detect(ws)
        except JsRuntimeError as exc:
            return False, [str(exc)] + exc.fix

        adapter = result.adapter
        log.info(
            "[%s] installing with %s (%s)",
            ws.name, adapter.name, result.evidence,
        )

        argv = adapter.install_args()
        _log_execution(ws, argv, reason=result.evidence)

        # Point npm cache and logs at /tmp so Render's read-only home dir
        # (/home/axon/.npm) doesn't cause permission errors.
        env = _npm_writable_env()

        rc, stdout, stderr = await rt_process.run_process(argv, cwd=ws, timeout=timeout, env=env)
        lines = stdout + stderr
        success = rc == 0

        if not success:
            log.warning("[%s] install failed (exit %d)", ws.name, rc)
        else:
            log.info("[%s] install completed in %s", ws.name, adapter.name)

        return success, lines

    async def run_script(
        self,
        ws: Path,
        script: str,
        *,
        timeout: float = _SCRIPT_TIMEOUT,
        extra_env: Optional[dict] = None,
    ) -> tuple[int, list[str], list[str]]:
        """
        Run a package.json script and collect all output.

        Returns:
            (returncode: int, stdout_lines: list[str], stderr_lines: list[str])

        Raises:
            ScriptNotFound         — script missing from package.json
            PackageJsonMissing     — no package.json
            JsRuntimeError subclass — PM detection failed
        """
        # Validate script exists before spawning any process
        self._resolver.resolve(ws, script)

        result = self.detect(ws)
        adapter = result.adapter
        argv = adapter.run_args(script)

        log.info(
            "[%s] running script %r with %s (%s) argv=%s",
            ws.name, script, adapter.name, result.evidence, argv,
        )
        _log_execution(ws, argv, reason=result.evidence)

        start = time.monotonic()
        rc, stdout, stderr = await rt_process.run_process(
            argv, cwd=ws, timeout=timeout, env=extra_env,
        )
        duration = time.monotonic() - start

        log.info(
            "[%s] script %r finished: exit=%d duration=%.2fs",
            ws.name, script, rc, duration,
        )

        if rc == -1 and any("timed out" in l.lower() for l in stderr):
            raise ExecutionTimeout(
                message=f'Script "{script}" timed out after {timeout:.0f}s',
                timeout_seconds=timeout,
                script=script,
            )

        return rc, stdout, stderr

    def server_argv(
        self,
        ws: Path,
        port: int,
        *,
        vite_host: bool = True,
    ) -> list[str]:
        """
        Build the argv list to start a dev/production server.

        Strategy:
          1. Resolve start/dev/serve/preview script from package.json
          2. Use the detected PM's run_args()
          3. For Vite-based projects, inject --host 0.0.0.0 --port <port>
          4. Fall back to `node <entry>` if no script exists
        """
        script = self._resolver.resolve_start(ws)
        if script is None:
            entry = _find_entry(ws)
            log.info("[%s] no start script found, falling back to node %s", ws.name, entry)
            return ["node", entry]

        try:
            result = self.detect(ws)
        except JsRuntimeError:
            return ["node", _find_entry(ws)]

        adapter = result.adapter
        argv = adapter.run_args(script)

        if vite_host and script in ("dev", "preview"):
            argv += ["--", "--host", "0.0.0.0", "--port", str(port)]

        log.info(
            "[%s] server argv: %s (pm=%s, script=%s)",
            ws.name, argv, adapter.name, script,
        )
        return argv


# ── Singleton for application-wide reuse ─────────────────────────────────────
#
# Callers import this and call it directly.
# No dependency injection needed — detection caches are process-scoped.

runtime_manager = RuntimeManager()


# ── Internal helpers ──────────────────────────────────────────────────────────

def _log_execution(ws: Path, argv: list[str], *, reason: str) -> None:
    log.info(
        "execute | cwd=%s | cmd=%s | pm_reason=%s",
        ws, " ".join(argv), reason,
    )


def _find_entry(ws: Path) -> str:
    for name in _ENTRY_CANDIDATES:
        if (ws / name).exists():
            return name
    return "index.js"


def _npm_writable_env() -> dict:
    """
    Return env overrides that redirect npm's cache and log directories to
    /tmp, which is always writable.  On Render the home dir (/home/axon)
    may be read-only, causing npm install to fail with a permissions error
    even though the install itself would succeed.
    """
    import os as _os
    env = dict(_os.environ)
    env.setdefault("npm_config_cache", "/tmp/npm-cache")
    env.setdefault("npm_config_logs_dir", "/tmp/npm-logs")
    # pnpm uses a different cache var
    env.setdefault("PNPM_HOME", "/tmp/pnpm-home")
    return env
