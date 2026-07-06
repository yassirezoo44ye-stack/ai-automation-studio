"""
PhaseRunner — three-phase execution engine.

Phase A: Environment validation
    Collects HOME, PATH, node version, PM selection, filesystem writability.
    Fails fast if node or any writable /tmp is missing.

Phase B: Dependency resolution
    Detects whether node_modules already satisfies the dependency graph.
    If not satisfied: runs install with explicit cache/log dirs.
    Hard-stops on any non-zero exit with no node_modules present.

Phase C: Application execution
    Resolves the start script, launches the server, waits for port binding.
    Captures full stdout+stderr during startup window.

No phase may start unless the previous phase passed.

Usage:
    runner = PhaseRunner(project_id, ws, info)
    async for event_type, payload in runner.run():
        yield _ev(event_type, **payload)
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import socket
import subprocess
import time
from pathlib import Path
from typing import AsyncIterator, Optional

from app.execution import process_mgr
from app.runtime import process as rt_process

from .adapters import ADAPTER_REGISTRY, NpmAdapter, NpmCliJsFallbackAdapter
from .detector import PackageManagerDetector
from .error_codes import (
    RuntimeErrorCode,
    classify_install_error,
    fixes_for,
    message_for,
)
from .errors import JsRuntimeError, PackageManagerNotFound
from .report import (
    DependencyReport,
    EnvironmentReport,
    LaunchReport,
    RuntimeReport,
)
from .resolver import ScriptResolver

log = logging.getLogger(__name__)

_INSTALL_TIMEOUT = 120.0
_SERVER_START_TIMEOUT = 25.0

# PM probe order: deterministic tools first, npm last
_PROBE_ORDER = ("pnpm", "yarn", "bun", "npm")

# Path where we cache the dependency graph checksum inside node_modules
_DEP_CHECKSUM_FILE = ".js-runtime-checksum"

# External service dependencies that cannot run in sandbox
_EXTERNAL_DEPS: dict[str, str] = {
    "pg": "PostgreSQL", "pg-pool": "PostgreSQL",
    "mysql": "MySQL", "mysql2": "MySQL",
    "mongoose": "MongoDB", "mongodb": "MongoDB",
    "redis": "Redis", "ioredis": "Redis",
    "bullmq": "Redis/BullMQ", "bull": "Redis/Bull",
    "prisma": "Database (Prisma)", "@prisma/client": "Database (Prisma)",
    "typeorm": "Database (TypeORM)", "sequelize": "Database (Sequelize)",
    "knex": "Database (Knex)", "amqplib": "RabbitMQ", "kafkajs": "Kafka",
}


class PhaseRunner:
    """
    Orchestrates the three execution phases for a single project run.

    Yields (event_type: str, payload: dict) tuples for every SSE event.
    The driver converts these with _ev(event_type, **payload).
    """

    def __init__(self, project_id: str, ws: Path, info) -> None:
        self.project_id = project_id
        self.ws = ws
        self.info = info
        self._detector = PackageManagerDetector()
        self._resolver = ScriptResolver()
        self._report = RuntimeReport(project_id=project_id, workspace=str(ws))

    async def run(self) -> AsyncIterator[tuple[str, dict]]:
        """
        Execute all three phases in order, yielding SSE events.
        Stops after the first phase that fails.
        """
        # ── Phase A ───────────────────────────────────────────────────────────
        async for ev in self._phase_a():
            yield ev
        if not self._report.environment or not self._report.environment.passed:
            yield "report", self._report.to_sse_dict()
            return

        # ── Phase B ───────────────────────────────────────────────────────────
        async for ev in self._phase_b():
            yield ev
        if not self._report.dependencies or not self._report.dependencies.passed:
            yield "report", self._report.to_sse_dict()
            return

        # ── Phase C ───────────────────────────────────────────────────────────
        async for ev in self._phase_c():
            yield ev
        yield "report", self._report.to_sse_dict()

    # ── Phase A: Environment Validation ───────────────────────────────────────

    async def _phase_a(self) -> AsyncIterator[tuple[str, dict]]:
        yield "status", {"message": "🔍 Phase A: Validating environment…"}

        env_report = EnvironmentReport(passed=False)
        env_report.workspace_path = str(self.ws)
        env_report.workspace_exists = self.ws.exists()
        env_report.workspace_readable = os.access(str(self.ws), os.R_OK)
        env_report.home = os.environ.get("HOME", os.path.expanduser("~"))
        env_report.path = os.environ.get("PATH", "")
        env_report.tmp_writable = os.access("/tmp", os.W_OK)
        env_report.home_writable = os.access(env_report.home, os.W_OK)

        # Node version
        env_report.node_version = _run_ver(["node", "--version"])

        # Workspace check
        if not env_report.workspace_exists:
            env_report.error_code = RuntimeErrorCode.ENV_INVALID_WORKSPACE
            env_report.message = message_for(env_report.error_code)
            env_report.suggested_fix = fixes_for(env_report.error_code)
            self._report.environment = env_report
            yield "error", _phase_error(env_report)
            return

        # Node check
        if env_report.node_version in ("", "unavailable"):
            env_report.error_code = RuntimeErrorCode.ENV_NODE_MISSING
            env_report.message = message_for(env_report.error_code)
            env_report.suggested_fix = fixes_for(env_report.error_code)
            self._report.environment = env_report
            yield "error", _phase_error(env_report)
            return

        # /tmp writability (needed for npm cache redirect)
        if not env_report.tmp_writable:
            env_report.error_code = RuntimeErrorCode.ENV_TMP_NOT_WRITABLE
            env_report.message = message_for(env_report.error_code)
            env_report.suggested_fix = fixes_for(env_report.error_code)
            self._report.environment = env_report
            yield "error", _phase_error(env_report)
            return

        # Package manager detection
        try:
            detection = self._detector.detect(self.ws)
            env_report.pm_name    = detection.adapter.name
            env_report.pm_version = _run_ver(detection.adapter.cmd + ["--version"])
            env_report.pm_method  = detection.method
            env_report.pm_evidence = detection.evidence
            env_report.pm_cmd     = detection.adapter.cmd
        except JsRuntimeError as exc:
            env_report.error_code = RuntimeErrorCode.ENV_PM_MISSING
            env_report.message    = str(exc)
            env_report.suggested_fix = exc.fix
            env_report.technical_details = {"tried": getattr(exc, "tried", [])}
            self._report.environment = env_report
            yield "error", _phase_error(env_report)
            return

        env_report.passed = True
        self._report.environment = env_report

        # Stream diagnostics as log lines
        for line in _env_summary(env_report):
            yield "log", {"stream": "stdout", "line": line, "ts": round(time.time(), 3)}

    # ── Phase B: Dependency Resolution ────────────────────────────────────────

    async def _phase_b(self) -> AsyncIterator[tuple[str, dict]]:
        yield "status", {"message": "📦 Phase B: Resolving dependencies…"}

        dep_report = DependencyReport(passed=False)
        ws = self.ws

        # Check for external services (block before any install)
        services = _check_external_services(ws)
        if services:
            dep_report.error_code = RuntimeErrorCode.DEP_EXTERNAL_SERVICE
            dep_report.message = f"Requires external services: {', '.join(services)}"
            dep_report.suggested_fix = fixes_for(RuntimeErrorCode.DEP_EXTERNAL_SERVICE)
            dep_report.technical_details = {"services": services}
            self._report.dependencies = dep_report
            yield "unsupported", {
                "project_type": self.info.project_type,
                "error": dep_report.message,
                "details": "Projects that depend on databases or queues must be run locally.",
                "local_run_hint": "docker compose up",
                "fix": dep_report.suggested_fix,
            }
            return

        # package.json
        pkg_json = ws / "package.json"
        if not pkg_json.exists():
            dep_report.error_code = RuntimeErrorCode.DEP_PKG_JSON_MISSING
            dep_report.message = message_for(dep_report.error_code)
            dep_report.suggested_fix = fixes_for(dep_report.error_code)
            self._report.dependencies = dep_report
            yield "error", _phase_error(dep_report)
            return

        dep_report.pkg_json_path = str(pkg_json)

        try:
            pkg_data = json.loads(pkg_json.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            dep_report.error_code = RuntimeErrorCode.DEP_PKG_JSON_INVALID
            dep_report.message = f"package.json JSON error: {exc}"
            dep_report.suggested_fix = fixes_for(RuntimeErrorCode.DEP_PKG_JSON_INVALID)
            self._report.dependencies = dep_report
            yield "error", _phase_error(dep_report)
            return

        # Lockfile
        for lf in ("pnpm-lock.yaml", "yarn.lock", "package-lock.json", "bun.lockb"):
            if (ws / lf).exists():
                dep_report.lockfile = lf
                break

        dep_report.node_modules_existed = (ws / "node_modules").exists()

        # Check if node_modules already satisfies the dependency graph
        if dep_report.node_modules_existed:
            reason = _deps_satisfied(ws, pkg_data)
            if reason:
                dep_report.install_skipped_reason = reason
                dep_report.passed = True
                self._report.dependencies = dep_report
                yield "status", {"message": f"✓ Dependencies already satisfied ({reason})"}
                return

        # Run install
        yield "status", {"message": f"📦 Installing dependencies…"}
        detection = self._detector.detect(self.ws)
        adapter = detection.adapter

        # For npm: always pass explicit --cache so it never touches ~/.npm
        install_argv = _explicit_npm_install_args(adapter)
        env = _npm_env()

        dep_report.install_ran = True
        dep_report.install_exit_code = 0
        start = time.monotonic()

        async for raw, code in rt_process.stream_process(
            install_argv, cwd=ws, env=env,
            timeout=_INSTALL_TIMEOUT, merge_stderr=False,
        ):
            if code is not None:
                dep_report.install_exit_code = code
                break
            if raw.startswith("[stderr] "):
                actual = raw[len("[stderr] "):]
                dep_report.install_stderr.append(actual)
                yield "log", {"stream": "stderr", "line": actual, "ts": round(time.time(), 3)}
            else:
                dep_report.install_stdout.append(raw)
                yield "log", {"stream": "stdout", "line": raw, "ts": round(time.time(), 3)}

        dep_report.install_duration_s = round(time.monotonic() - start, 2)

        log.info(
            "[%s] install exit=%d duration=%.2fs stdout=%d stderr=%d",
            ws.name, dep_report.install_exit_code,
            dep_report.install_duration_s,
            len(dep_report.install_stdout), len(dep_report.install_stderr),
        )

        if dep_report.install_exit_code != 0 and not (ws / "node_modules").exists():
            # Classify the exact error from stderr
            code = classify_install_error(dep_report.install_stderr)
            dep_report.error_code = code
            dep_report.message = message_for(code)
            dep_report.suggested_fix = fixes_for(code)
            dep_report.technical_details = {
                "exit_code": dep_report.install_exit_code,
                "pm": adapter.name,
                "command": " ".join(install_argv),
                "node_version": self._report.environment.node_version if self._report.environment else "?",
                "stderr_tail": dep_report.install_stderr[-30:],
            }
            self._report.dependencies = dep_report
            yield "error", {
                "category": "dependency_installation",
                "error": dep_report.message,
                "error_code": code.value,
                "details": _install_failure_details(dep_report),
                "fix": dep_report.suggested_fix,
                "severity": "high",
                "recoverable": False,
            }
            return

        # Write checksum so we skip install on next run
        _write_dep_checksum(ws, pkg_data)

        dep_report.passed = True
        self._report.dependencies = dep_report

        if dep_report.install_exit_code != 0:
            yield "status", {"message": "⚠ Install exited non-zero but node_modules present — continuing"}
        else:
            yield "status", {"message": f"✓ Dependencies installed in {dep_report.install_duration_s}s"}

    # ── Phase C: Application Execution ────────────────────────────────────────

    async def _phase_c(self) -> AsyncIterator[tuple[str, dict]]:
        yield "status", {"message": "🚀 Phase C: Launching application…"}

        pt = self.info.project_type

        if pt in ("react", "vue", "svelte", "vite", "nextjs", "nuxt"):
            async for ev in self._launch_build_project():
                yield ev
        else:
            async for ev in self._launch_server():
                yield ev

    async def _launch_server(self) -> AsyncIterator[tuple[str, dict]]:
        port = process_mgr.allocate_port()
        if port is None:
            report = LaunchReport.failure(
                RuntimeErrorCode.EXEC_PORT_UNAVAILABLE,
                technical_details={"port_pool": "exhausted"},
            )
            self._report.launch = report
            yield "error", _phase_error(report)
            return

        script = self._resolver.resolve_start(self.ws)
        detection = self._detector.detect(self.ws)
        adapter = detection.adapter

        if script:
            argv = adapter.run_args(script)
            if script in ("dev", "preview"):
                argv += ["--", "--host", "0.0.0.0", "--port", str(port)]
        else:
            entry = _find_entry(self.ws)
            argv = ["node", entry]
            script = entry

        env = {**os.environ, "PORT": str(port), "NODE_ENV": "development",
               **_npm_env()}

        yield "status", {"message": f"▶ {' '.join(argv)}  (port {port}, pm={adapter.name})"}

        start = time.time()
        try:
            rp = await process_mgr.start_server(
                project_id=self.project_id, args=argv, cwd=str(self.ws),
                env=env, port=port, project_type=self.info.project_type,
            )
        except Exception as exc:
            process_mgr._used_ports.discard(port)
            report = LaunchReport.failure(
                RuntimeErrorCode.EXEC_SERVER_CRASH,
                technical_details={"error": str(exc), "argv": argv},
                script=script, argv=argv, port=port,
            )
            self._report.launch = report
            yield "error", _phase_error(report)
            return

        yield "status", {"message": f"⏳ Waiting for server on :{port}…"}

        stdout_lines: list[str] = []
        stderr_lines: list[str] = []
        ready = False
        deadline = time.time() + _SERVER_START_TIMEOUT

        while time.time() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                    ready = True
                    break
            except OSError:
                pass
            if not rp.alive:
                break
            import asyncio
            for pipe, tag in ((rp.process.stdout, "stdout"), (rp.process.stderr, "stderr")):
                if not pipe:
                    continue
                try:
                    line = await asyncio.wait_for(pipe.readline(), timeout=0.3)
                    if line:
                        decoded = line.decode("utf-8", errors="replace").rstrip()
                        (stdout_lines if tag == "stdout" else stderr_lines).append(decoded)
                        yield "log", {"stream": tag, "line": decoded, "ts": round(time.time(), 3)}
                except asyncio.TimeoutError:
                    pass
            await asyncio.sleep(0.1)

        if not ready:
            try:
                rp.process.kill()
            except Exception:
                pass
            process_mgr._release(self.project_id)

            code = (
                RuntimeErrorCode.EXEC_SERVER_CRASH
                if not rp.alive
                else RuntimeErrorCode.EXEC_SERVER_TIMEOUT
            )
            report = LaunchReport.failure(
                code,
                technical_details={
                    "port": port, "argv": argv,
                    "stdout_tail": stdout_lines[-20:],
                    "stderr_tail": stderr_lines[-20:],
                    "alive_at_timeout": rp.alive,
                },
                script=script, argv=argv, port=port,
                crash_stdout=stdout_lines, crash_stderr=stderr_lines,
            )
            self._report.launch = report
            yield "error", {
                "category": "server_launch",
                "error": report.message,
                "error_code": code.value,
                "details": (
                    f"Port {port} — timeout {_SERVER_START_TIMEOUT}s\n"
                    f"Command: {' '.join(argv)}\n\n"
                    + ("\n".join(stderr_lines[-20:]) or "(no stderr output)")
                ),
                "fix": report.suggested_fix,
                "severity": "high",
                "recoverable": False,
            }
            return

        duration = round(time.time() - start, 2)
        report = LaunchReport(
            passed=True, script=script, argv=argv,
            port=port, startup_duration_s=duration,
        )
        self._report.launch = report
        yield "server_ready", {
            "preview_url": f"/api/projects/{self.project_id}/proxy/",
            "port": port,
            "project_type": self.info.project_type,
            "message": f"✓ Server ready in {duration}s (pm={adapter.name}, script={script})",
            "command": " ".join(argv),
        }

    async def _launch_build_project(self) -> AsyncIterator[tuple[str, dict]]:
        # Check for pre-built output first
        for dist_dir in ("dist", "build", "out", ".next/static"):
            for html in ("index.html", "404.html"):
                html_path = self.ws / dist_dir / html
                if html_path.exists():
                    content = html_path.read_text(encoding="utf-8")
                    report = LaunchReport(passed=True, script="(pre-built)")
                    self._report.launch = report
                    yield "html", {
                        "html_content": content,
                        "entry_file": f"{dist_dir}/{html}",
                        "project_type": self.info.project_type,
                        "message": f"Serving pre-built {dist_dir}/{html}",
                    }
                    return

        # Run build script
        build_script = self._resolver.resolve_build(self.ws)
        if not build_script:
            report = LaunchReport.failure(
                RuntimeErrorCode.EXEC_SCRIPT_MISSING,
                technical_details={"available": list(self._resolver.list_scripts(self.ws).keys())},
                script="build",
            )
            self._report.launch = report
            yield "unsupported", {
                "project_type": self.info.project_type,
                "error": f"{self.info.project_type} requires a build step — no build script found",
                "details": "Add a 'build' script to package.json",
                "local_run_hint": "npm install && npm run dev",
            }
            return

        detection = self._detector.detect(self.ws)
        adapter = detection.adapter
        argv = adapter.run_args(build_script)
        env = _npm_env()

        yield "status", {"message": f"🔨 Building with {adapter.name} run {build_script}…"}

        stdout_lines: list[str] = []
        stderr_lines: list[str] = []
        rc = 0

        async for raw, code in rt_process.stream_process(
            argv, cwd=self.ws, env=env, timeout=180.0, merge_stderr=False,
        ):
            if code is not None:
                rc = code
                break
            if raw.startswith("[stderr] "):
                actual = raw[len("[stderr] "):]
                stderr_lines.append(actual)
                yield "log", {"stream": "stderr", "line": actual, "ts": round(time.time(), 3)}
            else:
                stdout_lines.append(raw)
                yield "log", {"stream": "stdout", "line": raw, "ts": round(time.time(), 3)}

        if rc != 0:
            report = LaunchReport.failure(
                RuntimeErrorCode.EXEC_BUILD_FAILED,
                technical_details={"exit_code": rc, "stderr_tail": stderr_lines[-20:]},
                script=build_script, argv=argv,
                crash_stdout=stdout_lines, crash_stderr=stderr_lines,
            )
            self._report.launch = report
            yield "error", _phase_error(report)
            return

        for dist_dir in ("dist", "build", "out"):
            html_path = self.ws / dist_dir / "index.html"
            if html_path.exists():
                content = html_path.read_text(encoding="utf-8")
                report = LaunchReport(passed=True, script=build_script, argv=argv)
                self._report.launch = report
                yield "html", {
                    "html_content": content,
                    "entry_file": f"{dist_dir}/index.html",
                    "project_type": self.info.project_type,
                    "message": f"Build complete — serving {dist_dir}/index.html",
                }
                return

        report = LaunchReport.failure(
            RuntimeErrorCode.EXEC_BUILD_FAILED,
            technical_details={"reason": "no index.html found after build"},
            script=build_script,
        )
        self._report.launch = report
        yield "unsupported", {
            "project_type": self.info.project_type,
            "error": "Build completed but no index.html found in dist/, build/, or out/",
            "local_run_hint": "npm install && npm run dev",
        }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _run_ver(cmd: list[str]) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=5)
        return r.stdout.decode().strip() if r.returncode == 0 else "unavailable"
    except Exception:
        return "unavailable"


def _npm_env() -> dict:
    """
    Full environment with npm cache/log dirs forced to /tmp.
    Both lowercase and uppercase forms set for cross-version compatibility.
    Never uses setdefault — always overrides.
    """
    env = dict(os.environ)
    env["npm_config_cache"]    = "/tmp/npm-cache"
    env["npm_config_logs_dir"] = "/tmp/npm-logs"
    env["NPM_CONFIG_CACHE"]    = "/tmp/npm-cache"
    env["NPM_CONFIG_LOGS_DIR"] = "/tmp/npm-logs"
    env["PNPM_HOME"]           = "/tmp/pnpm-home"
    return env


def _explicit_npm_install_args(adapter) -> list[str]:
    """
    For npm/npm-cli adapters: append --cache flag explicitly so it never
    falls back to global npm configuration or ~/.npm.
    For pnpm/yarn/bun: use the adapter's install_args() unchanged.
    """
    args = adapter.install_args()
    if adapter.name in ("npm", "npm-cli"):
        # --cache overrides any npm config file setting
        args = args + ["--cache", "/tmp/npm-cache", "--logs-dir", "/tmp/npm-logs"]
    return args


def _deps_satisfied(ws: Path, pkg_data: dict) -> str:
    """
    Return a non-empty reason string if node_modules already satisfies the
    declared dependencies, or empty string if install is needed.

    Checks:
    1. Checksum file matches current package.json + lockfile hash
    2. All top-level direct deps exist as directories in node_modules
    """
    nm = ws / "node_modules"
    if not nm.exists():
        return ""

    # Checksum check (fast path)
    checksum_file = nm / _DEP_CHECKSUM_FILE
    if checksum_file.exists():
        stored = checksum_file.read_text().strip()
        current = _dep_checksum(ws, pkg_data)
        if stored == current:
            return "checksum match"

    # Presence check: verify first 20 direct deps exist
    all_deps = list(pkg_data.get("dependencies", {}).keys())
    missing = [d for d in all_deps[:20] if not (nm / d).exists()]
    if missing:
        return ""

    if all_deps:
        return "deps present (no lockfile change)"

    # No deps declared — nothing to install
    return "no dependencies declared"


def _dep_checksum(ws: Path, pkg_data: dict) -> str:
    """SHA-256 of declared deps + lockfile content (if present)."""
    h = hashlib.sha256()
    deps = {**pkg_data.get("dependencies", {}), **pkg_data.get("devDependencies", {})}
    h.update(json.dumps(deps, sort_keys=True).encode())
    for lf in ("pnpm-lock.yaml", "yarn.lock", "package-lock.json", "bun.lockb"):
        p = ws / lf
        if p.exists():
            try:
                h.update(p.read_bytes())
            except Exception:
                pass
            break
    return h.hexdigest()


def _write_dep_checksum(ws: Path, pkg_data: dict) -> None:
    try:
        checksum_file = ws / "node_modules" / _DEP_CHECKSUM_FILE
        checksum_file.write_text(_dep_checksum(ws, pkg_data))
    except Exception:
        pass  # non-fatal


def _check_external_services(ws: Path) -> list[str]:
    pkg_json = ws / "package.json"
    if not pkg_json.exists():
        return []
    try:
        data = json.loads(pkg_json.read_text())
        all_deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
        seen: dict[str, str] = {}
        for dep, svc in _EXTERNAL_DEPS.items():
            if dep in all_deps:
                seen[svc] = svc
        return list(seen.values())
    except Exception:
        return []


_ENTRY_CANDIDATES = (
    "index.js", "server.js", "app.js", "main.js",
    "src/index.js", "src/server.js",
)


def _find_entry(ws: Path) -> str:
    for name in _ENTRY_CANDIDATES:
        if (ws / name).exists():
            return name
    return "index.js"


def _env_summary(r: EnvironmentReport) -> list[str]:
    return [
        "── Phase A: Environment ─────────────────────────────────",
        f"  HOME          : {r.home}",
        f"  home writable : {r.home_writable}",
        f"  /tmp writable : {r.tmp_writable}",
        f"  node          : {r.node_version}",
        f"  pm            : {r.pm_name} {r.pm_version}  [{r.pm_method}: {r.pm_evidence}]",
        f"  pm command    : {' '.join(r.pm_cmd)}",
        "──────────────────────────────────────────────────────────",
    ]


def _install_failure_details(dep: DependencyReport) -> str:
    lines = [
        f"exit code : {dep.install_exit_code}",
        f"pm        : {dep.technical_details.get('pm', '?')}",
        f"command   : {dep.technical_details.get('command', '?')}",
        f"node      : {dep.technical_details.get('node_version', '?')}",
        "",
        "── Full stderr ──",
        *dep.install_stderr,
    ]
    return "\n".join(lines)


def _phase_error(phase_report) -> dict:
    return {
        "category": "runtime_phase",
        "error": phase_report.message,
        "error_code": phase_report.error_code.value if phase_report.error_code else "UNKNOWN",
        "details": json.dumps(phase_report.technical_details, indent=2) if phase_report.technical_details else "",
        "fix": phase_report.suggested_fix,
        "severity": "high",
        "recoverable": False,
    }
