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
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional

from app.runtime import process as rt_process

from .detector import DetectionResult, PackageManagerDetector
from .errors import (
    ExecutionFailed,
    ExecutionTimeout,
    JsRuntimeError,
    PackageJsonMissing,
    ScriptNotFound,
)
from .probe import EnvironmentProbe, ProbeResult
from .resolver import ScriptResolver
from .validator import ValidationReport, WorkspaceValidator

log = logging.getLogger(__name__)

# Default timeouts (seconds)
_INSTALL_TIMEOUT = 120.0


@dataclass
class InstallResult:
    """
    Complete record of a dependency installation attempt.

    Every field is populated — nothing is truncated, nothing is hidden.
    The driver uses this to decide whether to continue or abort.
    """
    exit_code: int
    success: bool
    pm_name: str
    pm_cmd: list[str]
    cwd: str
    pkg_json_path: str
    node_version: str
    npm_version: str
    home: str
    npm_cache: str
    stdout_lines: list[str] = field(default_factory=list)
    stderr_lines: list[str] = field(default_factory=list)

    @property
    def all_output(self) -> list[str]:
        return self.stdout_lines + self.stderr_lines

    def failure_summary(self) -> list[str]:
        """
        Return the lines that contain the actual npm error code.
        npm error codes (EACCES, ERESOLVE, ENOTFOUND, etc.) appear in stderr.
        Returns ALL stderr so no information is lost.
        """
        return self.stderr_lines if self.stderr_lines else self.stdout_lines
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
        self._probe     = EnvironmentProbe()

    # ── Environment probe ─────────────────────────────────────────────────────

    def probe(self, ws: Path) -> ProbeResult:
        """Collect direct evidence about the runtime environment."""
        return self._probe.probe(ws)

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
        self,
        ws: Path,
        *,
        timeout: float = _INSTALL_TIMEOUT,
    ) -> AsyncIterator[tuple[str, str, Optional[InstallResult]]]:
        """
        Install dependencies and stream every output line in real-time.

        Yields:
            (stream: "stdout"|"stderr", line: str, None)   — each output line
            ("result", "", InstallResult)                   — final sentinel

        stderr is captured separately so the exact npm error code (EACCES,
        ERESOLVE, ENOTFOUND, etc.) is always visible and never mixed with
        stdout progress lines.

        Nothing is truncated.  The driver must handle all lines.
        """
        import os as _os
        import subprocess as _sp

        env = _npm_writable_env()
        home = env.get("HOME", _os.path.expanduser("~"))
        npm_cache = env["npm_config_cache"]

        # Collect node/npm versions synchronously (fast, <5 s each)
        def _ver(cmd: list[str]) -> str:
            try:
                r = _sp.run(cmd, capture_output=True, timeout=5)
                return r.stdout.decode().strip() if r.returncode == 0 else "unavailable"
            except Exception as exc:
                return f"error: {exc}"

        node_ver = _ver(["node", "--version"])

        try:
            detection = self.detect(ws)
        except JsRuntimeError as exc:
            yield "stderr", str(exc), None
            for fix_line in exc.fix:
                yield "stderr", fix_line, None
            yield "result", "", InstallResult(
                exit_code=1, success=False,
                pm_name="unknown", pm_cmd=[],
                cwd=str(ws),
                pkg_json_path=str(ws / "package.json"),
                node_version=node_ver, npm_version="unavailable",
                home=home, npm_cache=npm_cache,
                stderr_lines=[str(exc)] + exc.fix,
            )
            return

        adapter = detection.adapter
        argv = adapter.install_args()
        npm_ver = _ver(argv[:1] + ["--version"])

        # ── Pre-install diagnostic header ─────────────────────────────────────
        header = [
            "── Dependency Installation ──────────────────────────────────",
            f"  pm         : {adapter.name}  ({detection.method}: {detection.evidence})",
            f"  command    : {' '.join(argv)}",
            f"  cwd        : {ws}",
            f"  package.json: {ws / 'package.json'} (exists={( ws / 'package.json').exists()})",
            f"  node       : {node_ver}",
            f"  npm/pm ver : {npm_ver}",
            f"  HOME       : {home}",
            f"  npm cache  : {npm_cache}",
            "─────────────────────────────────────────────────────────────",
        ]
        for h in header:
            yield "stdout", h, None

        log.info("[%s] install: %s  cwd=%s  node=%s  npm=%s  cache=%s",
                 ws.name, " ".join(argv), ws, node_ver, npm_ver, npm_cache)

        # ── Stream subprocess output with separated stderr ────────────────────
        stdout_lines: list[str] = []
        stderr_lines: list[str] = []

        async for raw_line, code in rt_process.stream_process(
            argv, cwd=ws, env=env, timeout=timeout, merge_stderr=False,
        ):
            if code is not None:
                rc = code
                break
            if raw_line.startswith("[stderr] "):
                actual = raw_line[len("[stderr] "):]
                stderr_lines.append(actual)
                yield "stderr", actual, None
            else:
                stdout_lines.append(raw_line)
                yield "stdout", raw_line, None
        else:
            rc = 0

        success = rc == 0
        log.info("[%s] install exit=%d stdout=%d stderr=%d",
                 ws.name, rc, len(stdout_lines), len(stderr_lines))

        result = InstallResult(
            exit_code=rc, success=success,
            pm_name=adapter.name, pm_cmd=argv,
            cwd=str(ws),
            pkg_json_path=str(ws / "package.json"),
            node_version=node_ver, npm_version=npm_ver,
            home=home, npm_cache=npm_cache,
            stdout_lines=stdout_lines,
            stderr_lines=stderr_lines,
        )
        yield "result", "", result

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
    Return a full environment dict with npm cache/log dirs forced to /tmp.

    Uses direct assignment (not setdefault) so that broken values already
    in os.environ are overridden.  On Render the home dir (/home/axon) is
    read-only — npm tries to write logs to ~/.npm/_logs before downloading
    any packages and fails immediately.

    npm respects both the lowercase npm_config_* form and the uppercase
    NPM_CONFIG_* form; we set both to be safe across npm versions.
    """
    import os as _os
    env = dict(_os.environ)
    # Force /tmp for cache and logs — override whatever may be set
    env["npm_config_cache"]     = "/tmp/npm-cache"
    env["npm_config_logs_dir"]  = "/tmp/npm-logs"
    env["NPM_CONFIG_CACHE"]     = "/tmp/npm-cache"
    env["NPM_CONFIG_LOGS_DIR"]  = "/tmp/npm-logs"
    # pnpm home
    env["PNPM_HOME"] = "/tmp/pnpm-home"
    return env
