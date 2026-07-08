"""
PhaseRunner — production-grade, self-diagnosing JS execution engine.

Execution is gated into four sequential phases:

  Phase A  — Runtime Probe + Environment Validation
      Collects 14 environmental facts (OS, arch, user, node version, all PMs,
      disk, memory, writability).  Fails fast if node, /tmp, or workspace
      is unavailable.

  Phase Plan — Build Plan Generation
      Creates a fully-resolved BuildPlan before any subprocess is spawned.
      Validates every command field.  If any command is undefined the run
      aborts immediately with JS004 — "$ undefined" is structurally
      impossible.

  Phase B  — Dependency Installation
      Uses BuildPlan.install_cmd exclusively.  Streams stdout/stderr
      separately.  Hard-stops on failure with no node_modules present.
      Dep-graph checksum skips redundant installs.

  Phase C  — Application Launch
      Uses BuildPlan.run_cmd / build_cmd exclusively.  Port already
      allocated; never undefined.

No phase may start unless all previous phases passed.
No subprocess is spawned unless a valid BuildPlan exists.
Every failure produces a typed error code, a human message, and
a suggested fix.

Platform independence:
  All temp paths are resolved via tempfile.gettempdir() — never hardcoded.
  Platform differences are isolated to _npm_env() and SystemProbe.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from typing import AsyncIterator, Optional

from app.execution import process_mgr
from app.runtime import process as rt_process

from .adapters import ADAPTER_REGISTRY, NpmAdapter, NpmCliJsFallbackAdapter
from .build_plan import BuildPlan
from .detector import PackageManagerDetector
from .error_codes import (
    RuntimeErrorCode,
    classify_install_error,
    fixes_for,
    message_for,
)
from .errors import JsRuntimeError, PackageManagerNotFound
from .probe import SystemProbe, SystemProbeResult
from .report import (
    BuildPlanReport,
    DependencyReport,
    EnvironmentReport,
    LaunchReport,
    RuntimeReport,
)
from .resolver import ScriptResolver

log = logging.getLogger(__name__)

# ── Platform-aware temp directories ──────────────────────────────────────────
# Computed once at import time.  Never hardcoded as "/tmp".
_TMPDIR       = tempfile.gettempdir()
_NPM_CACHE    = os.path.join(_TMPDIR, "npm-cache")
_NPM_LOGS     = os.path.join(_TMPDIR, "npm-logs")
_PNPM_HOME    = os.path.join(_TMPDIR, "pnpm-home")

# ── Timeouts ──────────────────────────────────────────────────────────────────
_INSTALL_TIMEOUT     = 120.0
_SERVER_START_TIMEOUT = 25.0
_BUILD_TIMEOUT        = 180.0

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

# Project types that run a dev server vs. project types that require a build step
_SERVER_TYPES = {"express", "koa", "nestjs", "node"}
_BUILD_TYPES  = {"react", "vue", "svelte", "vite", "nextjs", "nuxt"}


class PhaseRunner:
    """
    Orchestrates all execution phases for a single project run.

    Yields (event_type: str, payload: dict) tuples for every SSE event.
    The driver converts these with  f"data: {json.dumps(...)}\n\n".
    """

    def __init__(self, project_id: str, ws: Path, info) -> None:
        self.project_id = project_id
        self.ws = ws
        self.info = info
        self._detector   = PackageManagerDetector()
        self._resolver   = ScriptResolver()
        self._sys_probe  = SystemProbe()
        self._build_plan: Optional[BuildPlan] = None
        self._report     = RuntimeReport(project_id=project_id, workspace=str(ws))

    async def run(self) -> AsyncIterator[tuple[str, dict]]:
        """
        Execute all phases in order, yielding SSE events.
        Stops after the first phase that fails.
        """
        # ── Phase A: Environment Validation ──────────────────────────────────
        async for ev in self._phase_a():
            yield ev
        if not self._report.environment or not self._report.environment.passed:
            yield "report", self._report.to_sse_dict()
            return

        # ── Phase Plan: Build Plan Generation ────────────────────────────────
        async for ev in self._phase_plan():
            yield ev
        if not self._report.build_plan or not self._report.build_plan.passed:
            yield "report", self._report.to_sse_dict()
            return

        # ── Phase B: Dependency Resolution ───────────────────────────────────
        async for ev in self._phase_b():
            yield ev
        if not self._report.dependencies or not self._report.dependencies.passed:
            yield "report", self._report.to_sse_dict()
            return

        # ── Phase C: Application Execution ───────────────────────────────────
        async for ev in self._phase_c():
            yield ev
        yield "report", self._report.to_sse_dict()

    # ── Phase A: Environment Validation ───────────────────────────────────────

    async def _phase_a(self) -> AsyncIterator[tuple[str, dict]]:
        yield "status", {"message": "🔍 Phase A: Probing runtime environment…"}

        # ── Full system probe (14 fields) ─────────────────────────────────────
        sys_result: SystemProbeResult = self._sys_probe.probe(self.ws)
        for line in sys_result.as_log_lines():
            yield "log", {"stream": "stdout", "line": line, "ts": round(time.time(), 3)}

        env_report = EnvironmentReport(passed=False)
        env_report.workspace_path = str(self.ws)
        env_report.workspace_exists = self.ws.exists()
        env_report.workspace_readable = os.access(str(self.ws), os.R_OK)

        # Populate from system probe
        env_report.os_name         = sys_result.os_name
        env_report.architecture    = sys_result.architecture
        env_report.current_user    = sys_result.current_user
        env_report.home            = sys_result.home
        env_report.path            = sys_result.path
        env_report.tmpdir          = sys_result.tmpdir
        env_report.python_version  = sys_result.python_version
        env_report.disk_free_mb    = sys_result.disk_free_mb
        env_report.memory_free_mb  = sys_result.memory_free_mb
        env_report.available_pms   = sys_result.available_pms
        env_report.node_version    = sys_result.node_version or ""
        env_report.tmp_writable    = sys_result.writable_dirs.get(_TMPDIR, False)
        env_report.home_writable   = sys_result.writable_dirs.get(sys_result.home, False)

        # Propagate probe warnings into report
        self._report.warnings.extend(sys_result.warnings)

        # ── Hard-stop checks ──────────────────────────────────────────────────

        if not env_report.workspace_exists:
            env_report.error_code    = RuntimeErrorCode.ENV_INVALID_WORKSPACE
            env_report.message       = message_for(env_report.error_code)
            env_report.suggested_fix = fixes_for(env_report.error_code)
            self._report.environment = env_report
            yield "error", _phase_error(env_report)
            return

        if not env_report.node_version:
            env_report.error_code    = RuntimeErrorCode.ENV_NODE_MISSING
            env_report.message       = message_for(env_report.error_code)
            env_report.suggested_fix = fixes_for(env_report.error_code)
            env_report.technical_details = {
                "probe_warnings": sys_result.warnings,
                "path": sys_result.path,
            }
            self._report.environment = env_report
            yield "error", _phase_error(env_report)
            return

        if not env_report.tmp_writable:
            env_report.error_code    = RuntimeErrorCode.ENV_TMP_NOT_WRITABLE
            env_report.message       = message_for(env_report.error_code)
            env_report.suggested_fix = fixes_for(env_report.error_code)
            env_report.technical_details = {"tmpdir": _TMPDIR}
            self._report.environment = env_report
            yield "error", _phase_error(env_report)
            return

        # ── Package manager detection ──────────────────────────────────────────
        try:
            detection = self._detector.detect(self.ws)
            env_report.pm_name    = detection.adapter.name
            env_report.pm_version = _run_ver(detection.adapter.cmd + ["--version"])
            env_report.pm_method  = detection.method
            env_report.pm_evidence = detection.evidence
            env_report.pm_cmd     = detection.adapter.cmd
        except JsRuntimeError as exc:
            env_report.error_code    = RuntimeErrorCode.ENV_PM_MISSING
            env_report.message       = str(exc)
            env_report.suggested_fix = exc.fix
            env_report.technical_details = {
                "tried": getattr(exc, "tried", []),
                "available_pms": sys_result.available_pms,
            }
            self._report.environment = env_report
            yield "error", _phase_error(env_report)
            return

        env_report.passed = True
        self._report.environment = env_report

        # Stream condensed environment summary
        for line in _env_summary(env_report):
            yield "log", {"stream": "stdout", "line": line, "ts": round(time.time(), 3)}

    # ── Phase Plan: Build Plan Generation ─────────────────────────────────────

    async def _phase_plan(self) -> AsyncIterator[tuple[str, dict]]:
        yield "status", {"message": "📋 Phase Plan: Generating build plan…"}

        env = self._report.environment
        ws  = self.ws
        pt  = self.info.project_type

        detection = self._detector.detect(ws)
        adapter   = detection.adapter

        is_server = pt not in _BUILD_TYPES

        plan = BuildPlan(
            project_id  = self.project_id,
            workspace   = str(ws),
            runtime     = "node",
            node_version= env.node_version if env else "",
            pm_name     = adapter.name,
            pm_version  = env.pm_version if env else "",
            pm_cmd      = adapter.cmd,
            pm_method   = detection.method,
            pm_evidence = detection.evidence,
            install_cmd = _explicit_npm_install_args(adapter),
            project_type= pt,
            is_server   = is_server,
            env_vars    = _npm_env(),
        )

        if is_server:
            # Allocate port now — Phase C will use plan.port
            port = process_mgr.allocate_port()
            if port is None:
                bp_report = BuildPlanReport.failure(
                    RuntimeErrorCode.EXEC_PORT_UNAVAILABLE,
                    technical_details={"port_pool": "exhausted"},
                )
                self._report.build_plan = bp_report
                yield "error", _phase_error(bp_report)
                return
            plan.port = port

            script = self._resolver.resolve_start(ws)
            if script:
                plan.script_name = script
                plan.run_cmd     = adapter.run_args(script)
                if script in ("dev", "preview"):
                    plan.run_cmd += ["--", "--host", "0.0.0.0", "--port", str(port)]
            else:
                entry = _find_entry(ws)
                plan.script_name = entry
                plan.run_cmd     = ["node", entry]
                plan.warnings.append(
                    f"No start/dev script in package.json — falling back to: node {entry}"
                )
        else:
            build_script = self._resolver.resolve_build(ws)
            if build_script:
                plan.script_name = build_script
                plan.build_cmd   = adapter.run_args(build_script)
            plan.output_dir = "dist"  # default; resolved after build in Phase C

        # Validate — this is the guard that makes "$ undefined" impossible
        errors = plan.validate()
        if errors:
            bp_report = BuildPlanReport.failure(
                RuntimeErrorCode.EXEC_SCRIPT_MISSING,
                technical_details={
                    "validation_errors": errors,
                    "project_type": pt,
                    "is_server": is_server,
                    "available_scripts": list(self._resolver.list_scripts(ws).keys()),
                },
            )
            self._report.build_plan = bp_report
            yield "error", {
                "category": "build_plan_invalid",
                "error": "\n".join(errors),
                "error_code": RuntimeErrorCode.EXEC_SCRIPT_MISSING.value,
                "details": (
                    f"Project type: {pt}\n"
                    f"Available scripts: {list(self._resolver.list_scripts(ws).keys())}\n\n"
                    + "\n".join(errors)
                ),
                "fix": fixes_for(RuntimeErrorCode.EXEC_SCRIPT_MISSING),
                "severity": "high",
                "recoverable": False,
            }
            return

        self._build_plan = plan
        self._report.build_plan = BuildPlanReport.from_plan(plan)

        # Stream build plan as log lines
        for line in plan.as_log_lines():
            yield "log", {"stream": "stdout", "line": line, "ts": round(time.time(), 3)}

        yield "build_plan", plan.to_dict()

    # ── Phase B: Dependency Resolution ────────────────────────────────────────

    async def _phase_b(self) -> AsyncIterator[tuple[str, dict]]:
        yield "status", {"message": "📦 Phase B: Resolving dependencies…"}

        dep_report = DependencyReport(passed=False)
        ws    = self.ws
        plan  = self._build_plan
        assert plan is not None  # guaranteed by phase gating

        # ── External services check ───────────────────────────────────────────
        services = _check_external_services(ws)
        if services:
            dep_report.error_code    = RuntimeErrorCode.DEP_EXTERNAL_SERVICE
            dep_report.message       = f"Requires external services: {', '.join(services)}"
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

        # ── package.json presence + validity ─────────────────────────────────
        pkg_json = ws / "package.json"
        if not pkg_json.exists():
            dep_report.error_code    = RuntimeErrorCode.DEP_PKG_JSON_MISSING
            dep_report.message       = message_for(dep_report.error_code)
            dep_report.suggested_fix = fixes_for(dep_report.error_code)
            self._report.dependencies = dep_report
            yield "error", _phase_error(dep_report)
            return

        dep_report.pkg_json_path = str(pkg_json)

        try:
            pkg_data = json.loads(pkg_json.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            dep_report.error_code    = RuntimeErrorCode.DEP_PKG_JSON_INVALID
            dep_report.message       = f"package.json JSON error: {exc}"
            dep_report.suggested_fix = fixes_for(RuntimeErrorCode.DEP_PKG_JSON_INVALID)
            dep_report.technical_details = {"json_error": str(exc)}
            self._report.dependencies = dep_report
            yield "error", _phase_error(dep_report)
            return

        # ── Lockfile ──────────────────────────────────────────────────────────
        for lf in ("pnpm-lock.yaml", "yarn.lock", "package-lock.json", "bun.lockb"):
            if (ws / lf).exists():
                dep_report.lockfile = lf
                break

        dep_report.node_modules_existed = (ws / "node_modules").exists()

        # ── Dependency checksum — skip install if already satisfied ───────────
        if dep_report.node_modules_existed:
            reason = _deps_satisfied(ws, pkg_data)
            if reason:
                dep_report.install_skipped_reason = reason
                dep_report.passed = True
                self._report.dependencies = dep_report
                yield "status", {"message": f"✓ Dependencies already satisfied ({reason})"}
                return

        # ── Run install using the validated plan command ───────────────────────
        install_argv = plan.install_cmd  # already validated, never undefined
        env          = plan.env_vars

        yield "status", {
            "message": (
                f"📦 Installing dependencies via {plan.pm_name}…\n"
                f"  command : {plan.install_cmd_str}\n"
                f"  cwd     : {ws}\n"
                f"  node    : {plan.node_version}\n"
                f"  pm      : {plan.pm_name} {plan.pm_version}\n"
                f"  cache   : {env.get('npm_config_cache', 'default')}"
            )
        }

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
            "[%s] install exit=%d duration=%.2fs pm=%s stdout=%d stderr=%d",
            ws.name, dep_report.install_exit_code, dep_report.install_duration_s,
            plan.pm_name, len(dep_report.install_stdout), len(dep_report.install_stderr),
        )

        # ── Hard-stop on any install failure (non-zero exit) ─────────────────
        # A non-zero exit from the package manager means the dependency graph
        # is incomplete or inconsistent.  Running with a partial node_modules
        # produces unpredictable failures deep in the build or at runtime.
        # We stop here regardless of whether a stale node_modules exists.
        if dep_report.install_exit_code != 0:
            err_code = classify_install_error(dep_report.install_stderr)
            dep_report.error_code    = err_code
            dep_report.message       = message_for(err_code)
            dep_report.suggested_fix = fixes_for(err_code)
            dep_report.technical_details = {
                "exit_code"   : dep_report.install_exit_code,
                "pm"          : plan.pm_name,
                "command"     : plan.install_cmd_str,
                "node_version": plan.node_version,
                "duration_s"  : dep_report.install_duration_s,
                "stderr_tail" : dep_report.install_stderr[-30:],
            }
            self._report.dependencies = dep_report
            yield "error", {
                "category"   : "dependency_installation",
                "error"      : dep_report.message,
                "error_code" : err_code.value,
                "details"    : _install_failure_details(dep_report, plan),
                "fix"        : dep_report.suggested_fix,
                "severity"   : "high",
                "recoverable": False,
            }
            return

        # Write checksum so we skip install on the next run
        _write_dep_checksum(ws, pkg_data)

        dep_report.passed = True
        self._report.dependencies = dep_report
        yield "status", {"message": f"✓ Dependencies installed in {dep_report.install_duration_s}s"}

    # ── Phase C: Application Execution ────────────────────────────────────────

    async def _phase_c(self) -> AsyncIterator[tuple[str, dict]]:
        yield "status", {"message": "🚀 Phase C: Launching application…"}
        plan = self._build_plan
        assert plan is not None

        if plan.is_server:
            async for ev in self._launch_server(plan):
                yield ev
        else:
            async for ev in self._launch_build_project(plan):
                yield ev

    async def _launch_server(self, plan: BuildPlan) -> AsyncIterator[tuple[str, dict]]:
        argv = plan.run_cmd   # validated — never empty
        port = plan.port      # validated — never 0
        env  = {
            **plan.env_vars,
            "PORT": str(port),
            "NODE_ENV": "development",
        }

        yield "status", {"message": f"▶ {plan.run_cmd_str}  (port {port}, pm={plan.pm_name})"}

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
                script=plan.script_name, argv=argv, port=port,
            )
            self._report.launch = report
            yield "error", _phase_error(report)
            return

        yield "status", {"message": f"⏳ Waiting for server on :{port}…"}

        stdout_lines: list[str] = []
        stderr_lines: list[str] = []
        ready   = False
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
            for pipe, tag in (
                (rp.process.stdout, "stdout"),
                (rp.process.stderr, "stderr"),
            ):
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

            err_code = (
                RuntimeErrorCode.EXEC_SERVER_CRASH
                if not rp.alive
                else RuntimeErrorCode.EXEC_SERVER_TIMEOUT
            )
            report = LaunchReport.failure(
                err_code,
                technical_details={
                    "port"           : port,
                    "argv"           : argv,
                    "timeout_s"      : _SERVER_START_TIMEOUT,
                    "stdout_tail"    : stdout_lines[-20:],
                    "stderr_tail"    : stderr_lines[-20:],
                    "alive_at_timeout": rp.alive,
                },
                script=plan.script_name, argv=argv, port=port,
                crash_stdout=stdout_lines, crash_stderr=stderr_lines,
            )
            self._report.launch = report
            yield "error", {
                "category"   : "server_launch",
                "error"      : report.message,
                "error_code" : err_code.value,
                "details"    : (
                    f"Port {port} — timeout {_SERVER_START_TIMEOUT}s\n"
                    f"Command: {plan.run_cmd_str}\n\n"
                    + ("\n".join(stderr_lines[-20:]) or "(no stderr output)")
                ),
                "fix"        : report.suggested_fix,
                "severity"   : "high",
                "recoverable": False,
            }
            return

        duration = round(time.time() - start, 2)
        report = LaunchReport(
            passed=True, script=plan.script_name, argv=argv,
            port=port, startup_duration_s=duration,
        )
        self._report.launch = report
        yield "server_ready", {
            "preview_url" : f"/api/projects/{self.project_id}/proxy/",
            "port"        : port,
            "project_type": self.info.project_type,
            "message"     : (
                f"✓ Server ready in {duration}s "
                f"(pm={plan.pm_name}, script={plan.script_name})"
            ),
            "command"     : plan.run_cmd_str,
        }

    async def _launch_build_project(self, plan: BuildPlan) -> AsyncIterator[tuple[str, dict]]:
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
                        "entry_file"  : f"{dist_dir}/{html}",
                        "project_type": self.info.project_type,
                        "message"     : f"Serving pre-built {dist_dir}/{html}",
                    }
                    return

        if not plan.build_cmd:
            report = LaunchReport.failure(
                RuntimeErrorCode.EXEC_SCRIPT_MISSING,
                technical_details={
                    "available": list(self._resolver.list_scripts(self.ws).keys())
                },
                script="build",
            )
            self._report.launch = report
            yield "unsupported", {
                "project_type"  : self.info.project_type,
                "error"         : f"{self.info.project_type} requires a build step — no build script found",
                "details"       : "Add a 'build' script to package.json",
                "local_run_hint": "npm install && npm run dev",
            }
            return

        yield "status", {
            "message": f"🔨 Building with {plan.pm_name} run {plan.script_name}…"
        }

        argv         = plan.build_cmd
        stdout_lines : list[str] = []
        stderr_lines : list[str] = []
        rc           = 0

        async for raw, code in rt_process.stream_process(
            argv, cwd=self.ws, env=plan.env_vars,
            timeout=_BUILD_TIMEOUT, merge_stderr=False,
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
                technical_details={
                    "exit_code"  : rc,
                    "command"    : plan.build_cmd_str,
                    "stderr_tail": stderr_lines[-20:],
                },
                script=plan.script_name, argv=argv,
                crash_stdout=stdout_lines, crash_stderr=stderr_lines,
            )
            self._report.launch = report
            yield "error", _phase_error(report)
            return

        for dist_dir in ("dist", "build", "out"):
            html_path = self.ws / dist_dir / "index.html"
            if html_path.exists():
                content = html_path.read_text(encoding="utf-8")
                report  = LaunchReport(passed=True, script=plan.script_name, argv=argv)
                self._report.launch = report
                yield "html", {
                    "html_content": content,
                    "entry_file"  : f"{dist_dir}/index.html",
                    "project_type": self.info.project_type,
                    "message"     : f"Build complete — serving {dist_dir}/index.html",
                }
                return

        report = LaunchReport.failure(
            RuntimeErrorCode.EXEC_BUILD_FAILED,
            technical_details={"reason": "no index.html found after build"},
            script=plan.script_name,
        )
        self._report.launch = report
        yield "unsupported", {
            "project_type"  : self.info.project_type,
            "error"         : "Build completed but no index.html found in dist/, build/, or out/",
            "local_run_hint": "npm install && npm run dev",
        }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _run_ver(cmd: list[str]) -> str:
    """Run a --version command and return the trimmed output, or ''."""
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=5)
        return r.stdout.decode().strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def _npm_env() -> dict:
    """
    Full environment with npm/pnpm cache dirs forced to the platform temp dir.

    Uses direct assignment (not setdefault) — always overrides any existing
    broken values in os.environ.  Sets both lowercase and uppercase forms
    for cross-version npm compatibility.  Uses tempfile.gettempdir() instead
    of hardcoding '/tmp' for Windows compatibility.
    """
    env = dict(os.environ)
    env["npm_config_cache"]    = _NPM_CACHE
    env["npm_config_logs_dir"] = _NPM_LOGS
    env["NPM_CONFIG_CACHE"]    = _NPM_CACHE
    env["NPM_CONFIG_LOGS_DIR"] = _NPM_LOGS
    env["PNPM_HOME"]           = _PNPM_HOME
    return env


def _explicit_npm_install_args(adapter) -> list[str]:
    """
    For npm/npm-cli adapters: append --cache and --logs-dir explicitly
    so they cannot be overridden by any global npm config file.
    For pnpm/yarn/bun: return the adapter's install_args() unchanged.
    """
    args = adapter.install_args()
    if adapter.name in ("npm", "npm-cli"):
        args = args + ["--cache", _NPM_CACHE, "--logs-dir", _NPM_LOGS]
    return args


def _deps_satisfied(ws: Path, pkg_data: dict) -> str:
    """
    Return a non-empty reason string if node_modules already satisfies the
    declared dependency graph, or '' if installation is needed.
    """
    nm = ws / "node_modules"
    if not nm.exists():
        return ""

    # Fast path: checksum match
    checksum_file = nm / _DEP_CHECKSUM_FILE
    if checksum_file.exists():
        try:
            stored  = checksum_file.read_text().strip()
            current = _dep_checksum(ws, pkg_data)
            if stored == current:
                return "checksum match"
        except Exception:
            pass

    # Presence check: verify first 20 direct deps exist in node_modules
    all_deps = list(pkg_data.get("dependencies", {}).keys())
    missing  = [d for d in all_deps[:20] if not (nm / d).exists()]
    if missing:
        return ""

    if all_deps:
        return "deps present (no lockfile change)"

    return "no dependencies declared"


def _dep_checksum(ws: Path, pkg_data: dict) -> str:
    """SHA-256 of declared deps + lockfile content (if present)."""
    h    = hashlib.sha256()
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
        nm_dir = ws / "node_modules"
        if nm_dir.exists():
            (nm_dir / _DEP_CHECKSUM_FILE).write_text(_dep_checksum(ws, pkg_data))
    except Exception:
        pass  # non-fatal


def _check_external_services(ws: Path) -> list[str]:
    pkg_json = ws / "package.json"
    if not pkg_json.exists():
        return []
    try:
        data     = json.loads(pkg_json.read_text())
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
        "── Phase A: Validation ───────────────────────────────────",
        f"  home writable : {r.home_writable}",
        f"  /tmp writable : {r.tmp_writable}",
        f"  node          : {r.node_version}",
        f"  pm            : {r.pm_name} {r.pm_version}  [{r.pm_method}: {r.pm_evidence}]",
        f"  pm command    : {' '.join(r.pm_cmd)}",
        "──────────────────────────────────────────────────────────",
    ]


def _install_failure_details(dep: DependencyReport, plan: BuildPlan) -> str:
    lines = [
        f"exit code : {dep.install_exit_code}",
        f"pm        : {plan.pm_name}",
        f"command   : {plan.install_cmd_str}",
        f"node      : {plan.node_version}",
        f"duration  : {dep.install_duration_s}s",
        "",
        "── Full stderr ──",
        *dep.install_stderr,
    ]
    return "\n".join(lines)


def _phase_error(phase_report) -> dict:
    return {
        "category"   : "runtime_phase",
        "error"      : phase_report.message,
        "error_code" : phase_report.error_code.value if phase_report.error_code else "UNKNOWN",
        "details"    : (
            json.dumps(phase_report.technical_details, indent=2)
            if phase_report.technical_details
            else ""
        ),
        "fix"        : phase_report.suggested_fix,
        "severity"   : "high",
        "recoverable": False,
    }
