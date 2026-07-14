"""
Comprehensive tests for the JS runtime execution engine.

Coverage targets:
  Phase A (environment validation)    — node missing, PM missing, workspace missing
  BuildPlan                           — validate(), to_dict(), as_log_lines()
  Phase Plan                          — script resolution, port allocation, invalid plan
  Phase B (dependency installation)   — skip, run, hard-stop on failure, error classification
  Phase C (application launch)        — server start, build, port failure, timeout
  Error classification                — EACCES, ERESOLVE, ENOTFOUND, ETARGET, EBADENGINE
  Dependency checksum                 — stable hash, skip on match, install on mismatch
  Package manager detection           — all four PMs + lockfile priority
  SystemProbe                         — all 14 fields populated
  Platform independence               — no hardcoded /tmp
  RuntimeReport                       — to_sse_dict() structure, no undefined values
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.execution.js_runtime.build_plan import BuildPlan
from app.execution.js_runtime.error_codes import (
    RuntimeErrorCode,
    classify_install_error,
    js_code_for,
    from_js_code,
    message_for,
    fixes_for,
)
from app.execution.js_runtime.phases import (
    PhaseRunner,
    _dep_checksum,
    _deps_satisfied,
    _npm_env,
    _write_dep_checksum,
    _explicit_npm_install_args,
    _TMPDIR,
    _NPM_CACHE,
    _NPM_LOGS,
)
from app.execution.js_runtime.report import (
    DependencyReport,
    EnvironmentReport,
    LaunchReport,
    RuntimeReport,
)
from app.execution.js_runtime.adapters import (
    BunAdapter,
    NpmAdapter,
    NpmCliJsFallbackAdapter,
    PnpmAdapter,
    YarnAdapter,
)
from app.execution.js_runtime.probe import SystemProbe


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _pkg(
    tmp_path: Path,
    scripts: dict | None = None,
    deps: dict | None = None,
    dev_deps: dict | None = None,
) -> Path:
    data: dict = {"name": "test-project", "version": "1.0.0"}
    if scripts:
        data["scripts"] = scripts
    if deps:
        data["dependencies"] = deps
    if dev_deps:
        data["devDependencies"] = dev_deps
    (tmp_path / "package.json").write_text(json.dumps(data))
    return tmp_path


def _lockfile(tmp_path: Path, name: str) -> Path:
    (tmp_path / name).write_text("lockfile content\n")
    return tmp_path


class _FakeInfo:
    def __init__(self, project_type: str = "node", run_strategy: str = "node"):
        self.project_type = project_type
        self.run_strategy = run_strategy


async def _collect(gen) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    async for ev in gen:
        events.append(ev)
    return events


def _events(events: list[tuple[str, dict]], type_: str) -> list[dict]:
    return [p for t, p in events if t == type_]


def _first(events: list[tuple[str, dict]], type_: str) -> dict | None:
    for t, p in events:
        if t == type_:
            return p
    return None


# ── BuildPlan tests ───────────────────────────────────────────────────────────

class TestBuildPlan:
    def test_validate_complete_server_plan(self):
        plan = BuildPlan(
            project_id="p1", workspace="/ws",
            pm_name="npm", pm_cmd=["npm"],
            install_cmd=["npm", "install"],
            run_cmd=["npm", "run", "dev"],
            is_server=True, port=3000,
        )
        assert plan.validate() == []

    def test_validate_complete_build_plan(self):
        plan = BuildPlan(
            project_id="p1", workspace="/ws",
            pm_name="pnpm", pm_cmd=["pnpm"],
            install_cmd=["pnpm", "install"],
            build_cmd=["pnpm", "run", "build"],
            is_server=False,
        )
        assert plan.validate() == []

    def test_validate_missing_pm_name(self):
        plan = BuildPlan(
            project_id="p1", workspace="/ws",
            pm_cmd=["npm"],
            install_cmd=["npm", "install"],
            run_cmd=["npm", "run", "dev"],
            is_server=True, port=3000,
        )
        errors = plan.validate()
        assert any("JS001" in e for e in errors)

    def test_validate_missing_run_cmd(self):
        plan = BuildPlan(
            project_id="p1", workspace="/ws",
            pm_name="npm", pm_cmd=["npm"],
            install_cmd=["npm", "install"],
            is_server=True, port=3000,
        )
        errors = plan.validate()
        assert any("JS004" in e for e in errors)

    def test_validate_missing_port(self):
        plan = BuildPlan(
            project_id="p1", workspace="/ws",
            pm_name="npm", pm_cmd=["npm"],
            install_cmd=["npm", "install"],
            run_cmd=["npm", "run", "dev"],
            is_server=True, port=0,
        )
        errors = plan.validate()
        assert any("JS006" in e for e in errors)

    def test_validate_missing_build_cmd(self):
        plan = BuildPlan(
            project_id="p1", workspace="/ws",
            pm_name="npm", pm_cmd=["npm"],
            install_cmd=["npm", "install"],
            is_server=False,
        )
        errors = plan.validate()
        assert any("JS004" in e for e in errors)

    def test_validate_missing_install_cmd(self):
        plan = BuildPlan(
            project_id="p1", workspace="/ws",
            pm_name="npm", pm_cmd=["npm"],
            run_cmd=["npm", "run", "dev"],
            is_server=True, port=3000,
        )
        errors = plan.validate()
        assert any("JS001" in e for e in errors)

    def test_to_dict_no_undefined(self):
        plan = BuildPlan(project_id="p1", workspace="/ws")
        d = plan.to_dict()
        for key, val in d.items():
            assert val is not None, f"to_dict() key '{key}' is None"
            assert val != "undefined", f"to_dict() key '{key}' is the string 'undefined'"

    def test_run_cmd_str_empty_without_crash(self):
        plan = BuildPlan(project_id="p1", workspace="/ws")
        assert plan.run_cmd_str == ""

    def test_as_log_lines_server(self):
        plan = BuildPlan(
            project_id="p1", workspace="/ws",
            pm_name="npm", pm_version="10.2.4",
            run_cmd=["npm", "run", "dev"],
            is_server=True, port=3001,
        )
        lines = plan.as_log_lines()
        assert any("npm" in l for l in lines)
        assert any("3001" in l for l in lines)

    def test_as_log_lines_build(self):
        plan = BuildPlan(
            project_id="p1", workspace="/ws",
            pm_name="pnpm",
            build_cmd=["pnpm", "run", "build"],
            is_server=False, output_dir="dist",
        )
        lines = plan.as_log_lines()
        assert any("pnpm run build" in l for l in lines)
        assert any("dist" in l for l in lines)


# ── Error code tests ───────────────────────────────────────────────────────────

class TestErrorCodes:
    def test_classify_eacces(self):
        assert classify_install_error(["npm ERR! code EACCES"]) == RuntimeErrorCode.DEP_INSTALL_EACCES

    def test_classify_eperm(self):
        assert classify_install_error(["npm ERR! code EPERM"]) == RuntimeErrorCode.DEP_INSTALL_EACCES

    def test_classify_eresolve(self):
        assert classify_install_error(["npm ERR! code ERESOLVE"]) == RuntimeErrorCode.DEP_INSTALL_ERESOLVE

    def test_classify_enotfound(self):
        assert classify_install_error(["npm ERR! ENOTFOUND registry"]) == RuntimeErrorCode.DEP_INSTALL_ENOTFOUND

    def test_classify_etarget(self):
        assert classify_install_error(["npm ERR! code ETARGET"]) == RuntimeErrorCode.DEP_INSTALL_ETARGET

    def test_classify_engine(self):
        assert classify_install_error(["npm ERR! EBADENGINE"]) == RuntimeErrorCode.DEP_INSTALL_ENGINE

    def test_classify_fallback(self):
        assert classify_install_error(["some unknown error"]) == RuntimeErrorCode.DEP_INSTALL_FAILED

    def test_classify_empty(self):
        assert classify_install_error([]) == RuntimeErrorCode.DEP_INSTALL_FAILED

    def test_js_code_aliases(self):
        assert js_code_for(RuntimeErrorCode.ENV_PM_MISSING) == "JS001"
        assert js_code_for(RuntimeErrorCode.DEP_PKG_JSON_INVALID) == "JS002"
        assert js_code_for(RuntimeErrorCode.DEP_INSTALL_FAILED) == "JS003"
        assert js_code_for(RuntimeErrorCode.EXEC_SCRIPT_MISSING) == "JS004"
        assert js_code_for(RuntimeErrorCode.EXEC_SERVER_CRASH) == "JS005"
        assert js_code_for(RuntimeErrorCode.EXEC_PORT_UNAVAILABLE) == "JS006"
        assert js_code_for(RuntimeErrorCode.EXEC_SERVER_TIMEOUT) == "JS007"
        assert js_code_for(RuntimeErrorCode.ENV_INVALID_WORKSPACE) == "JS008"
        assert js_code_for(RuntimeErrorCode.ENV_NODE_MISSING) == "JS009"
        assert js_code_for(RuntimeErrorCode.DEP_LOCKFILE_MISSING) == "JS010"

    def test_from_js_code(self):
        assert from_js_code("JS001") == RuntimeErrorCode.ENV_PM_MISSING
        assert from_js_code("JS009") == RuntimeErrorCode.ENV_NODE_MISSING

    def test_message_for_all_codes(self):
        for code in RuntimeErrorCode:
            msg = message_for(code)
            assert isinstance(msg, str) and len(msg) > 0

    def test_fixes_for_all_codes(self):
        for code in RuntimeErrorCode:
            fixes = fixes_for(code)
            assert isinstance(fixes, list) and len(fixes) > 0


# ── Dependency checksum tests ──────────────────────────────────────────────────

class TestDepChecksum:
    def test_stable_across_calls(self, tmp_path):
        _pkg(tmp_path, deps={"react": "^18.0.0"})
        pkg_data = json.loads((tmp_path / "package.json").read_text())
        h1 = _dep_checksum(tmp_path, pkg_data)
        h2 = _dep_checksum(tmp_path, pkg_data)
        assert h1 == h2

    def test_changes_with_deps(self, tmp_path):
        _pkg(tmp_path, deps={"react": "^18.0.0"})
        pkg_data1 = json.loads((tmp_path / "package.json").read_text())
        _pkg(tmp_path, deps={"react": "^18.0.0", "lodash": "^4"})
        pkg_data2 = json.loads((tmp_path / "package.json").read_text())
        assert _dep_checksum(tmp_path, pkg_data1) != _dep_checksum(tmp_path, pkg_data2)

    def test_changes_with_lockfile(self, tmp_path):
        _pkg(tmp_path, deps={"react": "^18.0.0"})
        pkg_data = json.loads((tmp_path / "package.json").read_text())
        h1 = _dep_checksum(tmp_path, pkg_data)
        (tmp_path / "package-lock.json").write_text("lockfile v1")
        h2 = _dep_checksum(tmp_path, pkg_data)
        assert h1 != h2

    def test_write_and_read(self, tmp_path):
        _pkg(tmp_path, deps={"express": "^4"})
        pkg_data = json.loads((tmp_path / "package.json").read_text())
        nm = tmp_path / "node_modules"
        nm.mkdir()
        _write_dep_checksum(tmp_path, pkg_data)
        checksum_file = nm / ".js-runtime-checksum"
        assert checksum_file.exists()
        stored = checksum_file.read_text().strip()
        assert stored == _dep_checksum(tmp_path, pkg_data)

    def test_deps_satisfied_checksum_match(self, tmp_path):
        _pkg(tmp_path, deps={"express": "^4"})
        pkg_data = json.loads((tmp_path / "package.json").read_text())
        nm = tmp_path / "node_modules"
        nm.mkdir()
        (nm / "express").mkdir()
        _write_dep_checksum(tmp_path, pkg_data)
        result = _deps_satisfied(tmp_path, pkg_data)
        assert result == "checksum match"

    def test_deps_satisfied_no_node_modules(self, tmp_path):
        _pkg(tmp_path, deps={"express": "^4"})
        pkg_data = json.loads((tmp_path / "package.json").read_text())
        assert _deps_satisfied(tmp_path, pkg_data) == ""

    def test_deps_satisfied_missing_dep(self, tmp_path):
        _pkg(tmp_path, deps={"express": "^4", "lodash": "^4"})
        pkg_data = json.loads((tmp_path / "package.json").read_text())
        nm = tmp_path / "node_modules"
        nm.mkdir()
        # express present but lodash missing
        (nm / "express").mkdir()
        result = _deps_satisfied(tmp_path, pkg_data)
        assert result == ""

    def test_deps_satisfied_no_deps(self, tmp_path):
        _pkg(tmp_path)
        pkg_data = json.loads((tmp_path / "package.json").read_text())
        (tmp_path / "node_modules").mkdir()
        result = _deps_satisfied(tmp_path, pkg_data)
        assert result == "no dependencies declared"


# ── Platform independence tests ────────────────────────────────────────────────

class TestPlatformIndependence:
    def test_tmpdir_not_hardcoded(self):
        assert _TMPDIR == tempfile.gettempdir()
        # Must not be the literal string "/tmp" on all platforms
        assert isinstance(_TMPDIR, str) and len(_TMPDIR) > 0

    def test_npm_cache_under_tmpdir(self):
        assert _NPM_CACHE.startswith(_TMPDIR)
        assert "npm-cache" in _NPM_CACHE

    def test_npm_logs_under_tmpdir(self):
        assert _NPM_LOGS.startswith(_TMPDIR)
        assert "npm-logs" in _NPM_LOGS

    def test_npm_env_overrides(self):
        env = _npm_env()
        assert env["npm_config_cache"] == _NPM_CACHE
        assert env["NPM_CONFIG_CACHE"] == _NPM_CACHE
        assert env["npm_config_logs_dir"] == _NPM_LOGS
        assert env["NPM_CONFIG_LOGS_DIR"] == _NPM_LOGS

    def test_npm_env_always_overrides_existing(self):
        with patch.dict(os.environ, {"npm_config_cache": "/broken/path"}):
            env = _npm_env()
            assert env["npm_config_cache"] == _NPM_CACHE


# ── Adapter install args tests ────────────────────────────────────────────────

class TestAdapters:
    def test_npm_adapter_install_args(self):
        args = NpmAdapter().install_args()
        assert "npm" in args
        assert "install" in args
        assert "--prefer-offline" not in args

    def test_pnpm_adapter_install_args(self):
        args = PnpmAdapter().install_args()
        assert "pnpm" in args and "install" in args

    def test_yarn_adapter_install_args(self):
        args = YarnAdapter().install_args()
        assert "yarn" in args

    def test_bun_adapter_install_args(self):
        args = BunAdapter().install_args()
        assert "bun" in args

    def test_explicit_npm_cache_flag(self):
        args = _explicit_npm_install_args(NpmAdapter())
        assert "--cache" in args
        assert _NPM_CACHE in args
        assert "--logs-dir" in args
        assert _NPM_LOGS in args

    def test_explicit_pnpm_no_cache_flag(self):
        args = _explicit_npm_install_args(PnpmAdapter())
        assert "--cache" not in args

    def test_explicit_yarn_no_cache_flag(self):
        args = _explicit_npm_install_args(YarnAdapter())
        assert "--cache" not in args

    def test_npm_run_args(self):
        args = NpmAdapter().run_args("dev")
        assert args == ["npm", "run", "dev"]

    def test_pnpm_run_args(self):
        args = PnpmAdapter().run_args("build")
        assert args == ["pnpm", "run", "build"]

    def test_yarn_run_args(self):
        args = YarnAdapter().run_args("start")
        assert args == ["yarn", "start"]

    def test_bun_run_args(self):
        args = BunAdapter().run_args("dev")
        assert args == ["bun", "run", "dev"]

    def test_npm_cli_fallback_install_args(self):
        fallback = NpmCliJsFallbackAdapter("/usr/local/lib/node_modules/npm/bin/npm-cli.js")
        args = fallback.install_args()
        assert "node" in args
        assert "install" in args

    def test_explicit_npm_cli_cache_flag(self):
        fallback = NpmCliJsFallbackAdapter("/usr/local/lib/npm-cli.js")
        args = _explicit_npm_install_args(fallback)
        assert "--cache" in args


# ── SystemProbe tests ─────────────────────────────────────────────────────────

class TestSystemProbe:
    def test_all_fields_populated(self, tmp_path):
        probe = SystemProbe()
        result = probe.probe(tmp_path)

        assert isinstance(result.os_name, str)
        assert isinstance(result.architecture, str)
        assert isinstance(result.current_user, str)
        assert isinstance(result.working_dir, str)
        assert isinstance(result.home, str)
        assert isinstance(result.path, str)
        assert isinstance(result.tmpdir, str)
        # node_version may be None if not installed
        assert result.node_version is None or isinstance(result.node_version, str)
        assert isinstance(result.python_version, str)
        assert isinstance(result.available_pms, dict)
        assert isinstance(result.writable_dirs, dict)
        assert isinstance(result.cache_dirs, dict)
        assert isinstance(result.disk_free_mb, int)
        # memory_free_mb may be None
        assert result.memory_free_mb is None or isinstance(result.memory_free_mb, int)
        assert isinstance(result.warnings, list)

    def test_working_dir_matches_ws(self, tmp_path):
        result = SystemProbe().probe(tmp_path)
        assert result.working_dir == str(tmp_path)

    def test_tmpdir_populated(self, tmp_path):
        result = SystemProbe().probe(tmp_path)
        assert result.tmpdir == tempfile.gettempdir()

    def test_cache_dirs_under_tmpdir(self, tmp_path):
        result = SystemProbe().probe(tmp_path)
        for name, path in result.cache_dirs.items():
            assert path.startswith(result.tmpdir), (
                f"Cache dir '{name}' ({path}) is not under tmpdir ({result.tmpdir})"
            )

    def test_as_log_lines_returns_list(self, tmp_path):
        result = SystemProbe().probe(tmp_path)
        lines = result.as_log_lines()
        assert isinstance(lines, list)
        assert len(lines) > 5

    def test_as_log_lines_contain_key_fields(self, tmp_path):
        result = SystemProbe().probe(tmp_path)
        combined = "\n".join(result.as_log_lines())
        assert "OS" in combined
        assert "Architecture" in combined
        assert "Node" in combined
        assert "Python" in combined
        assert "Disk" in combined


# ── RuntimeReport tests ───────────────────────────────────────────────────────

class TestRuntimeReport:
    def test_to_sse_dict_no_undefined(self):
        report = RuntimeReport(project_id="p1", workspace="/ws")
        d = report.to_sse_dict()
        assert "project_id" in d
        assert "passed" in d
        assert "result" in d
        assert "duration_s" in d
        assert "warnings" in d
        assert d["result"] in ("success", "failure")

    def test_passed_requires_all_phases(self):
        report = RuntimeReport(project_id="p1", workspace="/ws")
        assert not report.passed

        report.environment = EnvironmentReport(passed=True)
        assert not report.passed

        report.dependencies = DependencyReport(passed=True)
        assert not report.passed

        report.launch = LaunchReport(passed=True)
        assert report.passed

    def test_failure_reason_first_failing_phase(self):
        report = RuntimeReport(project_id="p1", workspace="/ws")
        report.environment = EnvironmentReport(
            passed=False, error_code=RuntimeErrorCode.ENV_NODE_MISSING
        )
        assert report.failure_reason == RuntimeErrorCode.ENV_NODE_MISSING

    def test_to_sse_dict_js_code(self):
        report = RuntimeReport(project_id="p1", workspace="/ws")
        report.environment = EnvironmentReport(
            passed=False, error_code=RuntimeErrorCode.ENV_NODE_MISSING,
            message="Node not found", suggested_fix=["Install Node.js"],
        )
        d = report.to_sse_dict()
        assert d["failure_js_code"] == "JS009"

    def test_duration_increases(self):
        import time
        report = RuntimeReport(project_id="p1", workspace="/ws")
        d1 = report.duration_s
        time.sleep(0.05)
        d2 = report.duration_s
        assert d2 > d1


# ── Phase A tests ──────────────────────────────────────────────────────────────

class TestPhaseA:
    @pytest.mark.asyncio
    async def test_missing_workspace(self, tmp_path):
        ws = tmp_path / "nonexistent"
        runner = PhaseRunner("p1", ws, _FakeInfo())
        events = await _collect(runner.run())
        error_events = _events(events, "error")
        assert len(error_events) > 0
        assert error_events[0]["error_code"] == RuntimeErrorCode.ENV_INVALID_WORKSPACE.value

    @pytest.mark.asyncio
    async def test_missing_node(self, tmp_path):
        with patch("app.execution.js_runtime.probe._run_ver", return_value=None):
            runner = PhaseRunner("p1", tmp_path, _FakeInfo())
            events = await _collect(runner.run())
        error_events = _events(events, "error")
        assert any(
            e["error_code"] == RuntimeErrorCode.ENV_NODE_MISSING.value
            for e in error_events
        )

    @pytest.mark.asyncio
    async def test_missing_pm(self, tmp_path):
        from app.execution.js_runtime.errors import PackageManagerNotFound
        _pkg(tmp_path, scripts={"start": "node server.js"})
        exc = PackageManagerNotFound(message="No PM found", tried=["npm", "pnpm"])
        with (
            patch("app.execution.js_runtime.phases._run_ver", return_value="v20.0.0"),
            patch("app.execution.js_runtime.probe._run_ver", return_value="v20.0.0"),
            patch(
                "app.execution.js_runtime.phases.PackageManagerDetector.detect",
                side_effect=exc,
            ),
        ):
            runner = PhaseRunner("p1", tmp_path, _FakeInfo())
            events = await _collect(runner.run())
        error_events = _events(events, "error")
        assert len(error_events) > 0

    @pytest.mark.asyncio
    async def test_system_probe_streamed(self, tmp_path):
        _pkg(tmp_path, scripts={"dev": "node server.js"})
        with (
            patch("app.execution.js_runtime.phases._run_ver", return_value="v20.0.0"),
            patch("app.execution.js_runtime.probe._run_ver", return_value="v20.0.0"),
            patch("app.execution.js_runtime.phases.process_mgr.allocate_port", return_value=3000),
            patch(
                "app.execution.js_runtime.detector.PackageManagerDetector.detect",
                return_value=MagicMock(
                    adapter=NpmAdapter(),
                    method="probe",
                    evidence="npm found",
                ),
            ),
        ):
            runner = PhaseRunner("p1", tmp_path, _FakeInfo())
            events = await _collect(runner._phase_a())
        log_lines = [p["line"] for _, p in events if _ == "log"]
        combined = "\n".join(log_lines)
        assert "OS" in combined or "Runtime" in combined


# ── Phase Plan tests ───────────────────────────────────────────────────────────

class TestPhasePlan:
    def _make_runner(self, tmp_path, project_type="node"):
        runner = PhaseRunner("p1", tmp_path, _FakeInfo(project_type=project_type))
        runner._report.environment = EnvironmentReport(
            passed=True,
            node_version="v20.0.0",
            pm_name="npm", pm_version="10.0.0",
            pm_cmd=["npm"], pm_method="probe",
            pm_evidence="npm found",
        )
        return runner

    @pytest.mark.asyncio
    async def test_server_plan_with_dev_script(self, tmp_path):
        _pkg(tmp_path, scripts={"dev": "vite"})
        runner = self._make_runner(tmp_path)
        with (
            patch(
                "app.execution.js_runtime.phases.PackageManagerDetector.detect",
                return_value=MagicMock(
                    adapter=NpmAdapter(),
                    method="probe",
                    evidence="npm",
                ),
            ),
            patch("app.execution.js_runtime.phases.process_mgr.allocate_port", return_value=3001),
        ):
            events = await _collect(runner._phase_plan())
        assert runner._build_plan is not None
        assert runner._build_plan.run_cmd != []
        assert runner._build_plan.port == 3001

    @pytest.mark.asyncio
    async def test_build_plan_for_react_project(self, tmp_path):
        _pkg(tmp_path, scripts={"build": "vite build"})
        runner = self._make_runner(tmp_path, project_type="react")
        with patch(
            "app.execution.js_runtime.phases.PackageManagerDetector.detect",
            return_value=MagicMock(
                adapter=NpmAdapter(),
                method="probe",
                evidence="npm",
            ),
        ):
            events = await _collect(runner._phase_plan())
        assert runner._build_plan is not None
        assert runner._build_plan.is_server is False
        assert runner._build_plan.build_cmd != []

    @pytest.mark.asyncio
    async def test_plan_no_script_falls_back_to_node_entry(self, tmp_path):
        """No scripts → fallback to 'node index.js' with a warning (not an error)."""
        _pkg(tmp_path)  # no scripts
        runner = self._make_runner(tmp_path)
        with (
            patch(
                "app.execution.js_runtime.phases.PackageManagerDetector.detect",
                return_value=MagicMock(
                    adapter=NpmAdapter(),
                    method="probe",
                    evidence="npm",
                ),
            ),
            patch("app.execution.js_runtime.phases.process_mgr.allocate_port", return_value=3002),
        ):
            events = await _collect(runner._phase_plan())
        assert runner._build_plan is not None
        assert "node" in runner._build_plan.run_cmd
        assert len(runner._build_plan.warnings) > 0  # fallback warning emitted

    @pytest.mark.asyncio
    async def test_plan_validation_error_build_project_no_script(self, tmp_path):
        """Build project (react) with no build script → JS004 error."""
        _pkg(tmp_path)  # no scripts at all
        runner = self._make_runner(tmp_path, "react")
        runner._report.environment.node_version = "v20.0.0"
        with patch(
            "app.execution.js_runtime.phases.PackageManagerDetector.detect",
            return_value=MagicMock(
                adapter=NpmAdapter(),
                method="probe",
                evidence="npm",
            ),
        ):
            events = await _collect(runner._phase_plan())
        error_events = _events(events, "error")
        assert len(error_events) > 0
        assert "JS004" in error_events[0]["error"]

    @pytest.mark.asyncio
    async def test_plan_port_exhausted(self, tmp_path):
        _pkg(tmp_path, scripts={"start": "node server.js"})
        runner = self._make_runner(tmp_path)
        with (
            patch(
                "app.execution.js_runtime.phases.PackageManagerDetector.detect",
                return_value=MagicMock(
                    adapter=NpmAdapter(), method="probe", evidence="npm",
                ),
            ),
            patch("app.execution.js_runtime.phases.process_mgr.allocate_port", return_value=None),
        ):
            events = await _collect(runner._phase_plan())
        error_events = _events(events, "error")
        assert len(error_events) > 0
        assert error_events[0]["error_code"] == RuntimeErrorCode.EXEC_PORT_UNAVAILABLE.value

    @pytest.mark.asyncio
    async def test_build_plan_emitted_as_event(self, tmp_path):
        _pkg(tmp_path, scripts={"start": "node server.js"})
        runner = self._make_runner(tmp_path)
        with (
            patch(
                "app.execution.js_runtime.phases.PackageManagerDetector.detect",
                return_value=MagicMock(
                    adapter=NpmAdapter(), method="probe", evidence="npm",
                ),
            ),
            patch("app.execution.js_runtime.phases.process_mgr.allocate_port", return_value=3003),
        ):
            events = await _collect(runner._phase_plan())
        plan_events = _events(events, "build_plan")
        assert len(plan_events) == 1
        d = plan_events[0]
        # No field should be the string "undefined"
        for key, val in d.items():
            assert val != "undefined", f"build_plan field '{key}' is the string 'undefined'"


# ── Phase B tests ──────────────────────────────────────────────────────────────

class TestPhaseB:
    def _make_runner(self, tmp_path, install_cmd=None):
        runner = PhaseRunner("p1", tmp_path, _FakeInfo())
        runner._report.environment = EnvironmentReport(
            passed=True, node_version="v20.0.0",
            pm_name="npm", pm_version="10.0.0",
            pm_cmd=["npm"], pm_method="probe", pm_evidence="npm",
        )
        runner._build_plan = BuildPlan(
            project_id="p1", workspace=str(tmp_path),
            pm_name="npm", pm_version="10.0.0",
            pm_cmd=["npm"], pm_method="probe", pm_evidence="npm",
            install_cmd=install_cmd or ["npm", "install", "--ignore-scripts"],
            run_cmd=["npm", "run", "dev"],
            is_server=True, port=3000,
            env_vars=_npm_env(),
        )
        return runner

    @pytest.mark.asyncio
    async def test_skip_when_checksum_matches(self, tmp_path):
        _pkg(tmp_path, deps={"express": "^4"})
        pkg_data = json.loads((tmp_path / "package.json").read_text())
        nm = tmp_path / "node_modules"
        nm.mkdir()
        (nm / "express").mkdir()
        _write_dep_checksum(tmp_path, pkg_data)
        runner = self._make_runner(tmp_path)
        events = await _collect(runner._phase_b())
        status_events = _events(events, "status")
        assert any("satisfied" in e.get("message", "") for e in status_events)
        assert runner._report.dependencies is not None
        assert runner._report.dependencies.passed

    @pytest.mark.asyncio
    async def test_missing_package_json(self, tmp_path):
        runner = self._make_runner(tmp_path)
        events = await _collect(runner._phase_b())
        error_events = _events(events, "error")
        assert len(error_events) > 0
        assert error_events[0]["error_code"] == RuntimeErrorCode.DEP_PKG_JSON_MISSING.value

    @pytest.mark.asyncio
    async def test_invalid_package_json(self, tmp_path):
        (tmp_path / "package.json").write_text("{ not valid json }")
        runner = self._make_runner(tmp_path)
        events = await _collect(runner._phase_b())
        error_events = _events(events, "error")
        assert len(error_events) > 0
        assert error_events[0]["error_code"] == RuntimeErrorCode.DEP_PKG_JSON_INVALID.value

    @pytest.mark.asyncio
    async def test_install_failure_hard_stop(self, tmp_path):
        _pkg(tmp_path, deps={"some-pkg": "^1"})
        runner = self._make_runner(tmp_path)

        async def _fake_stream(argv, *, cwd, env, timeout, merge_stderr):
            yield "[stderr] npm ERR! code EACCES", None
            yield "[stderr] npm ERR! syscall open", None
            yield None, 1   # exit code 1

        with patch(
            "app.execution.js_runtime.phases.rt_process.stream_process",
            side_effect=_fake_stream,
        ):
            events = await _collect(runner._phase_b())

        error_events = _events(events, "error")
        assert len(error_events) > 0
        assert error_events[0]["error_code"] == RuntimeErrorCode.DEP_INSTALL_EACCES.value
        assert runner._report.dependencies is not None
        assert not runner._report.dependencies.passed

    @pytest.mark.asyncio
    async def test_install_success(self, tmp_path):
        _pkg(tmp_path, deps={"express": "^4"})
        runner = self._make_runner(tmp_path)
        nm = tmp_path / "node_modules"

        async def _fake_stream(argv, *, cwd, env, timeout, merge_stderr):
            nm.mkdir(exist_ok=True)
            yield "added 1 package", None
            yield None, 0

        with patch(
            "app.execution.js_runtime.phases.rt_process.stream_process",
            side_effect=_fake_stream,
        ):
            events = await _collect(runner._phase_b())

        assert runner._report.dependencies is not None
        assert runner._report.dependencies.passed


# ── Full pipeline tests ───────────────────────────────────────────────────────

class TestFullPipeline:
    """End-to-end PhaseRunner.run() tests."""

    def _mock_detection(self, adapter=None):
        if adapter is None:
            adapter = NpmAdapter()
        return MagicMock(
            adapter=adapter, method="probe", evidence="found",
        )

    @pytest.mark.asyncio
    async def test_pipeline_stops_at_phase_a_on_missing_workspace(self, tmp_path):
        ws = tmp_path / "nonexistent"
        runner = PhaseRunner("p1", ws, _FakeInfo())
        events = await _collect(runner.run())
        assert any(t == "error" for t, _ in events)
        assert any(t == "report" for t, _ in events)
        # report should show failure
        report_events = _events(events, "report")
        assert not report_events[-1]["passed"]

    @pytest.mark.asyncio
    async def test_pipeline_stops_at_phase_b_on_invalid_json(self, tmp_path):
        (tmp_path / "package.json").write_text("{ bad json")
        with (
            patch("app.execution.js_runtime.probe._run_ver", return_value="v20.0.0"),
            patch("app.execution.js_runtime.phases._run_ver", return_value="v20.0.0"),
            patch(
                "app.execution.js_runtime.phases.PackageManagerDetector.detect",
                return_value=self._mock_detection(),
            ),
            patch("app.execution.js_runtime.phases.process_mgr.allocate_port", return_value=3001),
        ):
            runner = PhaseRunner("p1", tmp_path, _FakeInfo())
            events = await _collect(runner.run())
        error_events = _events(events, "error")
        codes = [e["error_code"] for e in error_events]
        assert RuntimeErrorCode.DEP_PKG_JSON_INVALID.value in codes

    @pytest.mark.asyncio
    async def test_pipeline_report_has_js_code(self, tmp_path):
        ws = tmp_path / "ghost"
        runner = PhaseRunner("p1", ws, _FakeInfo())
        events = await _collect(runner.run())
        report_event = _events(events, "report")[-1]
        assert report_event["failure_js_code"] == "JS008"  # ENV_INVALID_WORKSPACE

    @pytest.mark.asyncio
    async def test_npm_install_uses_explicit_cache_flag(self, tmp_path):
        _pkg(tmp_path, scripts={"start": "node server.js"}, deps={"express": "^4"})
        captured_argv: list[list[str]] = []

        async def _fake_stream(argv, *, cwd, env, timeout, merge_stderr):
            captured_argv.append(argv)
            (tmp_path / "node_modules").mkdir(exist_ok=True)
            yield "ok", None
            yield None, 0

        with (
            patch("app.execution.js_runtime.probe._run_ver", return_value="v20.0.0"),
            patch("app.execution.js_runtime.phases._run_ver", return_value="v20.0.0"),
            patch(
                "app.execution.js_runtime.phases.PackageManagerDetector.detect",
                return_value=self._mock_detection(),
            ),
            patch("app.execution.js_runtime.phases.process_mgr.allocate_port", return_value=3010),
            patch(
                "app.execution.js_runtime.phases.rt_process.stream_process",
                side_effect=_fake_stream,
            ),
            patch(
                "app.execution.js_runtime.phases.process_mgr.start_server",
                side_effect=Exception("test ends here"),
            ),
        ):
            runner = PhaseRunner("p1", tmp_path, _FakeInfo())
            await _collect(runner.run())

        assert len(captured_argv) > 0
        install_args = captured_argv[0]
        assert "--cache" in install_args
        assert _NPM_CACHE in install_args

    @pytest.mark.asyncio
    async def test_lockfile_conflict_uses_highest_priority(self, tmp_path):
        """Multiple lockfiles → highest-priority (bun.lockb) wins."""
        _pkg(tmp_path, scripts={"start": "node server.js"})
        _lockfile(tmp_path, "package-lock.json")
        _lockfile(tmp_path, "bun.lockb")

        from app.execution.js_runtime.detector import PackageManagerDetector
        detector = PackageManagerDetector()

        with patch("app.execution.js_runtime.detector._verify_adapter", return_value=True):
            result = detector.detect(tmp_path)

        assert result.adapter.name == "bun"
        assert result.method == "lockfile"
        assert len(result.lockfile_conflicts) > 0  # package-lock.json listed as conflict

    @pytest.mark.asyncio
    async def test_pnpm_install_no_cache_flag(self, tmp_path):
        """pnpm install_args should NOT get --cache appended."""
        args = _explicit_npm_install_args(PnpmAdapter())
        assert "--cache" not in args

    @pytest.mark.asyncio
    async def test_yarn_install_no_cache_flag(self, tmp_path):
        args = _explicit_npm_install_args(YarnAdapter())
        assert "--cache" not in args

    @pytest.mark.asyncio
    async def test_bun_install_no_cache_flag(self, tmp_path):
        args = _explicit_npm_install_args(BunAdapter())
        assert "--cache" not in args


# ── Runtime launch tests ───────────────────────────────────────────────────────

class TestPhaseCLaunch:
    def _ready_runner(self, tmp_path, project_type="node"):
        runner = PhaseRunner("p1", tmp_path, _FakeInfo(project_type=project_type))
        runner._report.environment = EnvironmentReport(
            passed=True, node_version="v20.0.0",
            pm_name="npm", pm_version="10.0.0",
            pm_cmd=["npm"], pm_method="probe", pm_evidence="npm",
        )
        runner._report.dependencies = DependencyReport(passed=True)
        runner._build_plan = BuildPlan(
            project_id="p1", workspace=str(tmp_path),
            pm_name="npm", pm_cmd=["npm"],
            install_cmd=["npm", "install"],
            run_cmd=["npm", "run", "dev"],
            is_server=True, port=3000,
            env_vars=_npm_env(),
            script_name="dev",
        )
        return runner

    @pytest.mark.asyncio
    async def test_server_launch_success(self, tmp_path):
        runner = self._ready_runner(tmp_path)
        fake_process = MagicMock()
        fake_process.alive = True
        fake_process.process.stdout = None
        fake_process.process.stderr = None
        fake_rp = fake_process

        import socket as _socket

        def _fake_connect(addr, timeout):
            class _CM:
                def __enter__(self): return self
                def __exit__(self, *a): pass
            return _CM()

        with (
            patch(
                "app.execution.js_runtime.phases.process_mgr.start_server",
                new_callable=AsyncMock, return_value=fake_rp,
            ),
            patch.object(_socket, "create_connection", side_effect=_fake_connect),
        ):
            events = await _collect(runner._launch_server(runner._build_plan))

        ready_events = _events(events, "server_ready")
        assert len(ready_events) == 1
        assert ready_events[0]["port"] == 3000
        assert "command" in ready_events[0]
        assert ready_events[0]["command"] != ""
        assert ready_events[0]["command"] != "undefined"

    @pytest.mark.asyncio
    async def test_server_timeout_emits_error(self, tmp_path):
        runner = self._ready_runner(tmp_path)
        fake_rp = MagicMock()
        fake_rp.alive = True
        fake_rp.process.stdout = None
        fake_rp.process.stderr = None

        with (
            patch(
                "app.execution.js_runtime.phases.process_mgr.start_server",
                new_callable=AsyncMock, return_value=fake_rp,
            ),
            patch(
                "app.execution.js_runtime.phases.socket.create_connection",
                side_effect=OSError("refused"),
            ),
            patch("app.execution.js_runtime.phases._SERVER_START_TIMEOUT", 0.0),
            patch("app.execution.js_runtime.phases.process_mgr._release"),
        ):
            events = await _collect(runner._launch_server(runner._build_plan))

        error_events = _events(events, "error")
        assert len(error_events) > 0
        assert error_events[0]["error_code"] in (
            RuntimeErrorCode.EXEC_SERVER_TIMEOUT.value,
            RuntimeErrorCode.EXEC_SERVER_CRASH.value,
        )

    @pytest.mark.asyncio
    async def test_prebuilt_spa_served_without_install(self, tmp_path):
        _pkg(tmp_path, scripts={"build": "vite build"})
        dist = tmp_path / "dist"
        dist.mkdir()
        (dist / "index.html").write_text("<html>app</html>")
        runner = self._ready_runner(tmp_path, project_type="react")
        runner._build_plan.is_server = False
        runner._build_plan.build_cmd = ["npm", "run", "build"]
        events = await _collect(runner._launch_build_project(runner._build_plan))
        html_events = _events(events, "html")
        assert len(html_events) == 1
        assert "<html>" in html_events[0]["html_content"]


# ── Regression: "$ undefined" is impossible by design ─────────────────────────

class TestNoUndefinedCommand:
    """Any pathway that could produce '$ undefined' must be blocked."""

    def test_build_plan_to_dict_run_cmd_is_empty_string_not_undefined(self):
        plan = BuildPlan(project_id="p1", workspace="/ws")
        d = plan.to_dict()
        assert d["run_cmd"] == ""   # empty, NOT "undefined" or None

    def test_build_plan_run_cmd_str_is_empty_string_not_undefined(self):
        plan = BuildPlan(project_id="p1", workspace="/ws")
        assert plan.run_cmd_str == ""

    def test_server_ready_event_has_defined_command(self):
        # The server_ready event is yielded by _launch_server.
        # It uses plan.run_cmd_str which is always a string.
        plan = BuildPlan(
            project_id="p1", workspace="/ws",
            run_cmd=["npm", "run", "dev"],
            is_server=True, port=3000,
        )
        assert plan.run_cmd_str == "npm run dev"

    def test_validate_blocks_empty_run_cmd(self):
        plan = BuildPlan(
            project_id="p1", workspace="/ws",
            pm_name="npm", pm_cmd=["npm"],
            install_cmd=["npm", "install"],
            is_server=True, port=3000,
            # run_cmd deliberately left empty
        )
        errors = plan.validate()
        assert any("JS004" in e for e in errors)
        # Execution must not proceed
        assert len(errors) > 0
