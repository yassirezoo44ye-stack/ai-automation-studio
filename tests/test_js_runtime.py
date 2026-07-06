"""
Test matrix for the JavaScript Runtime Executor.

Covers every execution path defined in the spec:
  - npm project
  - pnpm project
  - yarn project
  - bun project
  - missing package.json
  - missing script
  - broken npm executable
  - missing node_modules
  - corrupted lockfile (invalid JSON)
  - multiple lockfiles (conflict)
  - fallback execution (npm-cli.js)
  - packageManager field in package.json
  - detection caching (no repeated probes)
  - ScriptResolver
  - WorkspaceValidator external-services detection
  - RuntimeManager.server_argv()
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

from app.execution.js_runtime.adapters import (
    BunAdapter,
    NpmAdapter,
    NpmCliJsFallbackAdapter,
    PnpmAdapter,
    YarnAdapter,
)
from app.execution.js_runtime.detector import (
    PackageManagerDetector,
    _exe_cache,
    _ws_cache,
)
from app.execution.js_runtime.errors import (
    LockfileConflict,
    PackageJsonMissing,
    PackageManagerNotFound,
    ScriptNotFound,
)
from app.execution.js_runtime.manager import RuntimeManager
from app.execution.js_runtime.resolver import ScriptResolver
from app.execution.js_runtime.validator import WorkspaceValidator


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clear_caches():
    """Isolate every test — clear detector caches before each run."""
    _exe_cache.clear()
    _ws_cache.clear()
    yield
    _exe_cache.clear()
    _ws_cache.clear()


def _pkg(tmp_path: Path, scripts: dict | None = None, pm_field: str | None = None) -> Path:
    """Write a minimal package.json into tmp_path."""
    data: dict = {"name": "test-pkg", "version": "1.0.0"}
    if scripts is not None:
        data["scripts"] = scripts
    if pm_field:
        data["packageManager"] = pm_field
    (tmp_path / "package.json").write_text(json.dumps(data))
    return tmp_path


def _lockfile(tmp_path: Path, name: str) -> Path:
    (tmp_path / name).write_text("# lockfile\n")
    return tmp_path


def _mock_probe(available: set[str]):
    """Patch _probe_exe to return True only for names in `available`."""
    def _probe(name: str) -> bool:
        return name in available
    return patch("app.execution.js_runtime.adapters._probe_exe", side_effect=_probe)


# ── Adapter unit tests ────────────────────────────────────────────────────────

class TestAdapterArgBuilding:
    def test_npm_install_args(self):
        a = NpmAdapter()
        assert a.install_args() == ["npm", "install", "--ignore-scripts"]

    def test_npm_run_args(self):
        a = NpmAdapter()
        assert a.run_args("build") == ["npm", "run", "build"]

    def test_pnpm_install_args(self):
        a = PnpmAdapter()
        assert a.install_args() == ["pnpm", "install", "--ignore-scripts"]

    def test_pnpm_run_args(self):
        a = PnpmAdapter()
        assert a.run_args("dev") == ["pnpm", "run", "dev"]

    def test_yarn_install_no_non_interactive(self):
        a = YarnAdapter()
        args = a.install_args()
        assert args[0] == "yarn"
        assert "install" in args
        assert "--non-interactive" in args

    def test_yarn_run_args_no_run_keyword(self):
        a = YarnAdapter()
        # yarn classic: yarn <script>
        assert a.run_args("start") == ["yarn", "start"]

    def test_bun_run_args(self):
        a = BunAdapter()
        assert a.run_args("test") == ["bun", "run", "test"]

    def test_npm_cli_fallback_args(self):
        a = NpmCliJsFallbackAdapter("/usr/local/lib/node_modules/npm/bin/npm-cli.js")
        assert a.run_args("start") == [
            "node",
            "/usr/local/lib/node_modules/npm/bin/npm-cli.js",
            "run",
            "start",
        ]

    def test_npm_cli_fallback_install_args(self):
        a = NpmCliJsFallbackAdapter("/usr/local/lib/node_modules/npm/bin/npm-cli.js")
        args = a.install_args()
        assert args[:2] == ["node", "/usr/local/lib/node_modules/npm/bin/npm-cli.js"]
        assert "install" in args


# ── Detection tests ───────────────────────────────────────────────────────────

class TestLockfileDetection:
    def test_npm_lockfile(self, tmp_path):
        _pkg(tmp_path)
        _lockfile(tmp_path, "package-lock.json")
        with _mock_probe({"npm"}):
            result = PackageManagerDetector().detect(tmp_path)
        assert result.adapter.name == "npm"
        assert result.method == "lockfile"
        assert "package-lock.json" in result.evidence

    def test_pnpm_lockfile(self, tmp_path):
        _pkg(tmp_path)
        _lockfile(tmp_path, "pnpm-lock.yaml")
        with _mock_probe({"pnpm"}):
            result = PackageManagerDetector().detect(tmp_path)
        assert result.adapter.name == "pnpm"
        assert result.method == "lockfile"

    def test_yarn_lockfile(self, tmp_path):
        _pkg(tmp_path)
        _lockfile(tmp_path, "yarn.lock")
        with _mock_probe({"yarn"}):
            result = PackageManagerDetector().detect(tmp_path)
        assert result.adapter.name == "yarn"
        assert result.method == "lockfile"

    def test_bun_lockfile_highest_priority(self, tmp_path):
        _pkg(tmp_path)
        # Even if all lockfiles exist, bun.lockb wins
        for lf in ("bun.lockb", "pnpm-lock.yaml", "yarn.lock", "package-lock.json"):
            _lockfile(tmp_path, lf)
        with _mock_probe({"bun", "pnpm", "yarn", "npm"}):
            result = PackageManagerDetector().detect(tmp_path)
        assert result.adapter.name == "bun"

    def test_multiple_lockfiles_records_conflicts(self, tmp_path):
        _pkg(tmp_path)
        _lockfile(tmp_path, "pnpm-lock.yaml")
        _lockfile(tmp_path, "yarn.lock")
        with _mock_probe({"pnpm", "yarn"}):
            result = PackageManagerDetector().detect(tmp_path)
        # Higher-priority lockfile wins; conflicts recorded
        assert result.adapter.name == "pnpm"
        assert "yarn.lock" in result.lockfile_conflicts


class TestPackageManagerFieldDetection:
    def test_packageManager_field_used_when_no_lockfile(self, tmp_path):
        _pkg(tmp_path, pm_field="pnpm@8.6.0")
        with _mock_probe({"pnpm"}):
            result = PackageManagerDetector().detect(tmp_path)
        assert result.adapter.name == "pnpm"
        assert result.method == "packageManager_field"

    def test_packageManager_field_ignored_if_pm_not_installed(self, tmp_path):
        _pkg(tmp_path, pm_field="pnpm@8.6.0")
        with _mock_probe({"npm"}):
            result = PackageManagerDetector().detect(tmp_path)
        # Falls through to probe — npm is available
        assert result.adapter.name == "npm"
        assert result.method == "probe"


class TestExecutableProbeDetection:
    def test_probe_used_when_no_lockfile(self, tmp_path):
        _pkg(tmp_path)
        with _mock_probe({"npm"}):
            result = PackageManagerDetector().detect(tmp_path)
        assert result.adapter.name == "npm"
        assert result.method == "probe"

    def test_bun_preferred_over_npm_in_probe(self, tmp_path):
        _pkg(tmp_path)
        with _mock_probe({"npm", "bun"}):
            result = PackageManagerDetector().detect(tmp_path)
        assert result.adapter.name == "bun"

    def test_no_pm_available_raises(self, tmp_path):
        _pkg(tmp_path)
        with _mock_probe(set()):
            with pytest.raises(PackageManagerNotFound) as exc_info:
                PackageManagerDetector().detect(tmp_path)
        err = exc_info.value
        assert err.tried  # at least some names were tried


class TestNpmCliFallback:
    def test_fallback_used_when_npm_broken(self, tmp_path):
        _pkg(tmp_path)
        _lockfile(tmp_path, "package-lock.json")
        fake_cli = tmp_path / "npm-cli.js"
        fake_cli.write_text("// fake")

        with (
            _mock_probe(set()),  # all PMs broken
            patch(
                "app.execution.js_runtime.adapters.NpmCliJsFallbackAdapter._SEARCH_PATHS",
                (str(fake_cli),),
            ),
            patch("app.execution.js_runtime.adapters._probe_exe", return_value=False),
            # node itself is available for the fallback verify()
            patch.object(NpmCliJsFallbackAdapter, "verify", return_value=True),
        ):
            result = PackageManagerDetector().detect(tmp_path)
        assert result.adapter.name == "npm-cli"
        assert result.method == "fallback"

    def test_fallback_find_returns_none_when_no_cli(self):
        with patch(
            "app.execution.js_runtime.adapters.NpmCliJsFallbackAdapter._SEARCH_PATHS",
            ("/nonexistent/npm-cli.js",),
        ):
            assert NpmCliJsFallbackAdapter.find() is None


class TestDetectionCaching:
    def test_second_call_uses_cache(self, tmp_path):
        _pkg(tmp_path)
        _lockfile(tmp_path, "package-lock.json")
        probe_calls: list[str] = []

        def counting_probe(name: str) -> bool:
            probe_calls.append(name)
            return name == "npm"

        with patch("app.execution.js_runtime.adapters._probe_exe", side_effect=counting_probe):
            d = PackageManagerDetector()
            d.detect(tmp_path)
            calls_after_first = len(probe_calls)
            d.detect(tmp_path)
            calls_after_second = len(probe_calls)

        # No additional probes on second call
        assert calls_after_first == calls_after_second


# ── ScriptResolver tests ──────────────────────────────────────────────────────

class TestScriptResolver:
    def test_resolve_existing_script(self, tmp_path):
        _pkg(tmp_path, scripts={"build": "tsc", "dev": "vite"})
        r = ScriptResolver()
        assert r.resolve(tmp_path, "build") == "build"

    def test_resolve_missing_script_raises(self, tmp_path):
        _pkg(tmp_path, scripts={"build": "tsc"})
        r = ScriptResolver()
        with pytest.raises(ScriptNotFound) as exc_info:
            r.resolve(tmp_path, "nonexistent")
        err = exc_info.value
        assert err.script == "nonexistent"
        assert "build" in err.available

    def test_resolve_start_finds_dev_when_no_start(self, tmp_path):
        _pkg(tmp_path, scripts={"dev": "vite"})
        r = ScriptResolver()
        assert r.resolve_start(tmp_path) == "dev"

    def test_resolve_start_prefers_start_over_dev(self, tmp_path):
        _pkg(tmp_path, scripts={"start": "node index.js", "dev": "vite"})
        r = ScriptResolver()
        assert r.resolve_start(tmp_path) == "start"

    def test_resolve_start_returns_none_when_no_scripts(self, tmp_path):
        _pkg(tmp_path, scripts={})
        r = ScriptResolver()
        assert r.resolve_start(tmp_path) is None

    def test_resolve_build_finds_build_script(self, tmp_path):
        _pkg(tmp_path, scripts={"build": "tsc"})
        r = ScriptResolver()
        assert r.resolve_build(tmp_path) == "build"

    def test_missing_package_json_raises(self, tmp_path):
        r = ScriptResolver()
        with pytest.raises(PackageJsonMissing):
            r.resolve(tmp_path, "build")

    def test_corrupted_json_raises(self, tmp_path):
        (tmp_path / "package.json").write_text("{invalid json")
        r = ScriptResolver()
        with pytest.raises(PackageJsonMissing):
            r.resolve(tmp_path, "build")

    def test_list_scripts_returns_dict(self, tmp_path):
        _pkg(tmp_path, scripts={"build": "tsc", "test": "jest"})
        r = ScriptResolver()
        scripts = r.list_scripts(tmp_path)
        assert "build" in scripts
        assert "test" in scripts


# ── WorkspaceValidator tests ──────────────────────────────────────────────────

class TestWorkspaceValidator:
    def test_valid_workspace_passes(self, tmp_path):
        _pkg(tmp_path, scripts={"dev": "vite"})
        (tmp_path / "node_modules").mkdir()
        v = WorkspaceValidator()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=b"v20.0.0", stderr=b"")
            report = v.validate(tmp_path, script="dev", require_modules=True)
        assert report.ok
        assert not report.issues

    def test_missing_package_json_is_issue(self, tmp_path):
        v = WorkspaceValidator()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=b"v20.0.0", stderr=b"")
            report = v.validate(tmp_path)
        assert not report.ok
        assert any("package.json" in i for i in report.issues)

    def test_missing_script_is_issue(self, tmp_path):
        _pkg(tmp_path, scripts={"build": "tsc"})
        v = WorkspaceValidator()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=b"v20.0.0", stderr=b"")
            report = v.validate(tmp_path, script="nonexistent")
        assert not report.ok
        assert any("nonexistent" in i for i in report.issues)

    def test_missing_node_modules_is_issue_when_required(self, tmp_path):
        _pkg(tmp_path)
        v = WorkspaceValidator()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=b"v20.0.0", stderr=b"")
            report = v.validate(tmp_path, require_modules=True)
        assert not report.ok
        assert any("node_modules" in i for i in report.issues)

    def test_external_services_detected_as_warning(self, tmp_path):
        data = {
            "name": "test",
            "dependencies": {"pg": "^8.0.0", "redis": "^4.0.0"},
        }
        (tmp_path / "package.json").write_text(json.dumps(data))
        v = WorkspaceValidator()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=b"v20.0.0", stderr=b"")
            report = v.validate(tmp_path)
        assert any("PostgreSQL" in w or "Redis" in w for w in report.warnings)
        services = report.diagnostics.get("external_services", [])
        assert "PostgreSQL" in services or "Redis" in services

    def test_multiple_lockfiles_is_warning(self, tmp_path):
        _pkg(tmp_path)
        _lockfile(tmp_path, "pnpm-lock.yaml")
        _lockfile(tmp_path, "yarn.lock")
        v = WorkspaceValidator()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=b"v20.0.0", stderr=b"")
            report = v.validate(tmp_path)
        assert any("lockfile" in w.lower() for w in report.warnings)

    def test_node_not_found_is_issue(self, tmp_path):
        _pkg(tmp_path)
        v = WorkspaceValidator()
        with patch("subprocess.run", side_effect=FileNotFoundError("node not found")):
            report = v.validate(tmp_path)
        assert any("node" in i.lower() for i in report.issues)


# ── RuntimeManager integration tests ─────────────────────────────────────────

class TestRuntimeManager:
    def test_server_argv_uses_dev_script(self, tmp_path):
        _pkg(tmp_path, scripts={"dev": "vite"})
        _lockfile(tmp_path, "package-lock.json")
        m = RuntimeManager()
        with _mock_probe({"npm"}):
            argv = m.server_argv(tmp_path, port=8100)
        assert "npm" in argv[0]
        assert "dev" in argv

    def test_server_argv_prefers_start_over_dev(self, tmp_path):
        _pkg(tmp_path, scripts={"start": "node index.js", "dev": "vite"})
        _lockfile(tmp_path, "package-lock.json")
        m = RuntimeManager()
        with _mock_probe({"npm"}):
            argv = m.server_argv(tmp_path, port=8100)
        assert "start" in argv

    def test_server_argv_falls_back_to_node_entry(self, tmp_path):
        _pkg(tmp_path, scripts={})
        (tmp_path / "index.js").write_text("// entry")
        m = RuntimeManager()
        with _mock_probe({"npm"}):
            argv = m.server_argv(tmp_path, port=8100)
        assert argv == ["node", "index.js"]

    def test_detect_returns_detection_result(self, tmp_path):
        _pkg(tmp_path)
        _lockfile(tmp_path, "pnpm-lock.yaml")
        m = RuntimeManager()
        with _mock_probe({"pnpm"}):
            result = m.detect(tmp_path)
        assert result.adapter.name == "pnpm"

    def test_list_scripts(self, tmp_path):
        _pkg(tmp_path, scripts={"build": "tsc", "test": "jest"})
        m = RuntimeManager()
        scripts = m.list_scripts(tmp_path)
        assert set(scripts.keys()) == {"build", "test"}

    @pytest.mark.asyncio
    async def test_run_script_raises_script_not_found(self, tmp_path):
        _pkg(tmp_path, scripts={"build": "tsc"})
        _lockfile(tmp_path, "package-lock.json")
        m = RuntimeManager()
        with _mock_probe({"npm"}):
            with pytest.raises(ScriptNotFound):
                await m.run_script(tmp_path, "nonexistent")

    @pytest.mark.asyncio
    async def test_run_script_raises_when_no_pm(self, tmp_path):
        _pkg(tmp_path, scripts={"build": "tsc"})
        m = RuntimeManager()
        with _mock_probe(set()):
            with pytest.raises(PackageManagerNotFound):
                await m.run_script(tmp_path, "build")

    @pytest.mark.asyncio
    async def test_install_returns_false_when_no_pm(self, tmp_path):
        _pkg(tmp_path)
        m = RuntimeManager()
        with _mock_probe(set()):
            ok, lines = await m.install(tmp_path)
        assert not ok
        assert lines  # error message returned


# ── EnvironmentProbe tests ────────────────────────────────────────────────────

class TestEnvironmentProbe:
    def test_probe_returns_result(self, tmp_path):
        _pkg(tmp_path, scripts={"dev": "vite"})
        _lockfile(tmp_path, "package-lock.json")
        from app.execution.js_runtime.probe import EnvironmentProbe
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=b"v20.0.0", stderr=b"")
            result = EnvironmentProbe().probe(tmp_path)
        assert result.pkg_json_exists is True
        assert result.lockfile_found == "package-lock.json"

    def test_probe_detects_missing_package_json(self, tmp_path):
        from app.execution.js_runtime.probe import EnvironmentProbe
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=b"v20.0.0", stderr=b"")
            result = EnvironmentProbe().probe(tmp_path)
        assert result.pkg_json_exists is False
        assert result.lockfile_found is None

    def test_probe_as_log_lines_is_non_empty(self, tmp_path):
        _pkg(tmp_path)
        from app.execution.js_runtime.probe import EnvironmentProbe
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=b"v20.0.0", stderr=b"")
            result = EnvironmentProbe().probe(tmp_path)
        lines = result.as_log_lines()
        assert len(lines) > 5
        assert any("HOME" in l for l in lines)
        assert any("npm cache" in l for l in lines)

    def test_probe_warns_when_home_npm_unwritable(self, tmp_path):
        from app.execution.js_runtime.probe import EnvironmentProbe
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        npm_dir = fake_home / ".npm"
        npm_dir.mkdir()

        with (
            patch.dict("os.environ", {"HOME": str(fake_home)}, clear=False),
            patch("os.access", return_value=False),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0, stdout=b"v20.0.0", stderr=b"")
            result = EnvironmentProbe().probe(tmp_path)
        assert result.warnings  # should have at least one warning


class TestNpmWritableEnv:
    def test_force_overrides_existing_bad_cache(self):
        from app.execution.js_runtime.manager import _npm_writable_env
        with patch.dict("os.environ", {
            "npm_config_cache": "/home/axon/.npm",
            "NPM_CONFIG_CACHE": "/home/axon/.npm",
        }):
            env = _npm_writable_env()
        # Must override, not keep the broken value
        assert env["npm_config_cache"] == "/tmp/npm-cache"
        assert env["NPM_CONFIG_CACHE"] == "/tmp/npm-cache"
        assert env["npm_config_logs_dir"] == "/tmp/npm-logs"

    def test_env_contains_all_required_keys(self):
        from app.execution.js_runtime.manager import _npm_writable_env
        env = _npm_writable_env()
        assert "npm_config_cache" in env
        assert "npm_config_logs_dir" in env
        assert "NPM_CONFIG_CACHE" in env
        assert "NPM_CONFIG_LOGS_DIR" in env
        assert "PNPM_HOME" in env


# ── Error hierarchy tests ─────────────────────────────────────────────────────

class TestErrorHierarchy:
    def test_all_errors_are_js_runtime_error(self):
        from app.execution.js_runtime.errors import (
            ExecutionFailed, ExecutionTimeout, JsRuntimeError,
            LockfileConflict, NodeModulesMissing, PackageJsonMissing,
            PackageManagerBroken, PackageManagerNotFound, RuntimeUnavailable,
            ScriptNotFound,
        )
        for cls in (
            PackageManagerNotFound, PackageManagerBroken, ScriptNotFound,
            PackageJsonMissing, NodeModulesMissing, RuntimeUnavailable,
            ExecutionTimeout, ExecutionFailed, LockfileConflict,
        ):
            assert issubclass(cls, JsRuntimeError)

    def test_package_manager_not_found_has_fix(self):
        err = PackageManagerNotFound(message="not found", tried=["npm", "pnpm"])
        assert err.fix
        assert err.tried == ["npm", "pnpm"]

    def test_script_not_found_has_available_list(self):
        err = ScriptNotFound(message="missing", script="deploy", available=["build", "test"])
        assert err.script == "deploy"
        assert "build" in err.available

    def test_error_to_dict(self):
        err = PackageManagerNotFound(message="not found", tried=["npm"])
        d = err.to_dict()
        assert d["error_type"] == "PackageManagerNotFound"
        assert d["message"] == "not found"
        assert d["fix"]
