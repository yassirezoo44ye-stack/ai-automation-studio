"""
Comprehensive tests for the Execution Platform.

Coverage targets:
  - BuildCache: key computation, hit/miss, store/restore, eviction
  - ArtifactSystem: add_file, add_bytes, add_text, add_directory, cleanup
  - ExecutionSandbox: creation, npm_env, cleanup
  - ExecutionMetrics: phases, derived timing, to_dict
  - ExecutionReport: fields, finish(), to_dict(), to_sse_dict()
  - TypedEvent subclasses: to_sse_dict()
  - PlatformError hierarchy: factory functions, to_dict()
  - RuntimeRegistry: register, select, priority order
  - NodeRuntime: detect()
  - PythonRuntime: detect()
  - DockerRuntime: detect()
  - ElectronRuntime: detect()
  - UnifiedExecutionEngine: workspace validation, runtime selection,
                            SSE event stream, cleanup always called
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path



# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_node_project(ws: Path) -> None:
    (ws / "package.json").write_text(json.dumps({
        "name": "test-app",
        "version": "1.0.0",
        "scripts": {"start": "node index.js"},
        "dependencies": {"express": "^4.18.0"},
    }))
    (ws / "index.js").write_text("console.log('hello')")


def _make_python_project(ws: Path) -> None:
    (ws / "main.py").write_text("print('hello')")
    (ws / "requirements.txt").write_text("requests==2.31.0\n")


def _make_docker_project(ws: Path) -> None:
    (ws / "Dockerfile").write_text("FROM node:18\nCOPY . .\nCMD node index.js\n")


def _make_electron_project(ws: Path) -> None:
    (ws / "package.json").write_text(json.dumps({
        "name": "my-electron-app",
        "devDependencies": {"electron": "^28.0.0"},
        "main": "main.js",
    }))
    (ws / "main.js").write_text("")


# ─────────────────────────────────────────────────────────────────────────────
# BuildCache
# ─────────────────────────────────────────────────────────────────────────────

class TestBuildCache:
    def test_key_for_node_is_stable(self, tmp_path):
        from app.execution.platform.cache import BuildCache
        ws = tmp_path / "ws"
        ws.mkdir()
        _make_node_project(ws)
        cache = BuildCache(root=tmp_path / "cache")
        k1 = cache.key_for_node(ws, "v20.11.0")
        k2 = cache.key_for_node(ws, "v20.11.0")
        assert k1 == k2
        assert len(k1) == 16

    def test_key_changes_with_deps(self, tmp_path):
        from app.execution.platform.cache import BuildCache
        ws = tmp_path / "ws"
        ws.mkdir()
        _make_node_project(ws)
        cache = BuildCache(root=tmp_path / "cache")
        k1 = cache.key_for_node(ws, "v20.11.0")
        # Change deps
        (ws / "package.json").write_text(json.dumps({
            "dependencies": {"lodash": "^4.17.0"},
        }))
        k2 = cache.key_for_node(ws, "v20.11.0")
        assert k1 != k2

    def test_key_changes_with_node_version(self, tmp_path):
        from app.execution.platform.cache import BuildCache
        ws = tmp_path / "ws"
        ws.mkdir()
        _make_node_project(ws)
        cache = BuildCache(root=tmp_path / "cache")
        k1 = cache.key_for_node(ws, "v18.0.0")
        k2 = cache.key_for_node(ws, "v20.0.0")
        assert k1 != k2

    def test_key_for_python_is_stable(self, tmp_path):
        from app.execution.platform.cache import BuildCache
        ws = tmp_path / "ws"
        ws.mkdir()
        _make_python_project(ws)
        cache = BuildCache(root=tmp_path / "cache")
        k1 = cache.key_for_python(ws, "3.11.0")
        k2 = cache.key_for_python(ws, "3.11.0")
        assert k1 == k2

    def test_has_miss_on_empty(self, tmp_path):
        from app.execution.platform.cache import BuildCache
        cache = BuildCache(root=tmp_path / "cache")
        assert cache.has("nonexistent") is False

    def test_store_and_restore_node_modules(self, tmp_path):
        from app.execution.platform.cache import BuildCache
        ws = tmp_path / "ws"
        ws.mkdir()
        _make_node_project(ws)

        # Create a fake node_modules
        nm = tmp_path / "nm"
        nm.mkdir()
        (nm / "some_package").mkdir()
        (nm / "some_package" / "index.js").write_text("module.exports={}")

        cache = BuildCache(root=tmp_path / "cache")
        key = cache.key_for_node(ws, "v20.11.0")

        assert cache.store_node_modules(key, nm) is True
        assert cache.has(key) is True

        # Restore to a different target
        target = tmp_path / "restored_nm"
        assert cache.restore_node_modules(key, target) is True
        assert (target / "some_package" / "index.js").exists()

    def test_restore_miss_returns_false(self, tmp_path):
        from app.execution.platform.cache import BuildCache
        cache = BuildCache(root=tmp_path / "cache")
        target = tmp_path / "target"
        assert cache.restore_node_modules("missing_key", target) is False

    def test_evict_expired(self, tmp_path):
        from app.execution.platform.cache import BuildCache, CacheEntry
        cache = BuildCache(root=tmp_path / "cache")
        # Inject a fake expired entry
        stale = CacheEntry(
            key="stale",
            runtime="node",
            created_at=time.time() - 999999,
            size_bytes=0,
            data_path=str(tmp_path / "nowhere"),
        )
        cache._entries["stale"] = stale
        assert cache.evict_expired() == 1
        assert "stale" not in cache._entries

    def test_stats_returns_dict(self, tmp_path):
        from app.execution.platform.cache import BuildCache
        cache = BuildCache(root=tmp_path / "cache")
        s = cache.stats()
        assert "entries" in s
        assert "total_size_mb" in s
        assert "root" in s


# ─────────────────────────────────────────────────────────────────────────────
# ArtifactSystem
# ─────────────────────────────────────────────────────────────────────────────

class TestArtifactSystem:
    def test_add_bytes_and_get(self, tmp_path):
        from app.execution.platform.artifacts import ArtifactSystem
        arts = ArtifactSystem("exec-1", root=tmp_path)
        arts.init()
        art = arts.add_bytes("log", "install.log", b"npm install ok")
        assert art is not None
        assert art.kind == "log"
        assert art.size_bytes == len(b"npm install ok")
        assert arts.get(art.id) is art

    def test_add_text(self, tmp_path):
        from app.execution.platform.artifacts import ArtifactSystem
        arts = ArtifactSystem("exec-2", root=tmp_path)
        arts.init()
        art = arts.add_text("report", "report.json", '{"success": true}')
        assert art is not None
        assert Path(art.path).read_bytes() == b'{"success": true}'

    def test_add_file(self, tmp_path):
        from app.execution.platform.artifacts import ArtifactSystem
        src = tmp_path / "build.log"
        src.write_text("build output")

        arts = ArtifactSystem("exec-3", root=tmp_path / "arts")
        arts.init()
        art = arts.add_file("log", "build.log", src)
        assert art is not None
        assert art.exists

    def test_add_file_missing_returns_none(self, tmp_path):
        from app.execution.platform.artifacts import ArtifactSystem
        arts = ArtifactSystem("exec-4", root=tmp_path)
        arts.init()
        result = arts.add_file("log", "missing.log", tmp_path / "does_not_exist.log")
        assert result is None

    def test_add_directory(self, tmp_path):
        from app.execution.platform.artifacts import ArtifactSystem
        src = tmp_path / "dist"
        src.mkdir()
        (src / "index.html").write_text("<html/>")

        arts = ArtifactSystem("exec-5", root=tmp_path / "arts")
        arts.init()
        art = arts.add_directory("dist", "dist", src)
        assert art is not None
        assert art.name.endswith(".zip")

    def test_by_kind(self, tmp_path):
        from app.execution.platform.artifacts import ArtifactSystem
        arts = ArtifactSystem("exec-6", root=tmp_path)
        arts.init()
        arts.add_bytes("log", "a.log", b"log1")
        arts.add_bytes("report", "r.json", b"{}")
        arts.add_bytes("log", "b.log", b"log2")
        assert len(arts.by_kind("log")) == 2
        assert len(arts.by_kind("report")) == 1

    def test_count_and_total_size(self, tmp_path):
        from app.execution.platform.artifacts import ArtifactSystem
        arts = ArtifactSystem("exec-7", root=tmp_path)
        arts.init()
        arts.add_bytes("log", "a.log", b"hello")
        arts.add_bytes("log", "b.log", b"world")
        assert arts.count() == 2
        assert arts.total_size_bytes() == 10

    def test_save_and_load_index(self, tmp_path):
        from app.execution.platform.artifacts import ArtifactSystem
        arts = ArtifactSystem("exec-8", root=tmp_path)
        arts.init()
        arts.add_bytes("log", "log.txt", b"content")
        arts.save_index()

        loaded = ArtifactSystem.load("exec-8", root=tmp_path)
        assert loaded.count() == 1

    def test_cleanup_removes_files(self, tmp_path):
        from app.execution.platform.artifacts import ArtifactSystem
        arts = ArtifactSystem("exec-9", root=tmp_path)
        arts.init()
        art = arts.add_bytes("log", "log.txt", b"content")
        p = Path(art.path)
        assert p.exists()
        arts.cleanup()
        assert not p.exists()


# ─────────────────────────────────────────────────────────────────────────────
# ExecutionSandbox
# ─────────────────────────────────────────────────────────────────────────────

class TestExecutionSandbox:
    def test_create_makes_dirs(self, tmp_path):
        from app.execution.platform.sandbox import ExecutionSandbox
        ws = tmp_path / "project"
        ws.mkdir()
        (ws / "index.js").write_text("console.log('hi')")

        sb = ExecutionSandbox(ws, "exec-sandbox-1")
        # Override base dir to tmp_path for isolation
        sb._base_dir = tmp_path / "executions"
        sb._root     = sb._base_dir / "exec-sandbox-1"

        paths = sb.create()
        assert paths.workspace.exists()
        assert paths.cache.exists()
        assert paths.logs.exists()
        assert paths.artifacts.exists()
        assert paths.tmp.exists()

    def test_workspace_copy_skips_node_modules(self, tmp_path):
        from app.execution.platform.sandbox import ExecutionSandbox
        ws = tmp_path / "project"
        ws.mkdir()
        (ws / "index.js").write_text("console.log('hi')")
        nm = ws / "node_modules"
        nm.mkdir()
        (nm / "pkg" ).mkdir()
        (nm / "pkg" / "index.js").write_text("")

        sb = ExecutionSandbox(ws, "exec-sandbox-2")
        sb._base_dir = tmp_path / "executions"
        sb._root     = sb._base_dir / "exec-sandbox-2"
        paths = sb.create()

        # node_modules should not be copied
        assert not (paths.workspace / "node_modules").exists()
        assert (paths.workspace / "index.js").exists()

    def test_npm_env_override(self, tmp_path):
        from app.execution.platform.sandbox import ExecutionSandbox
        ws = tmp_path / "ws"
        ws.mkdir()
        sb = ExecutionSandbox(ws, "exec-sandbox-3")
        sb._base_dir = tmp_path / "executions"
        sb._root     = sb._base_dir / "exec-sandbox-3"
        paths = sb.create()

        env = sb.npm_env
        assert env["npm_config_cache"] == str(paths.cache)
        assert env["npm_config_logs_dir"] == str(paths.logs)

    def test_cleanup_frees_space(self, tmp_path):
        from app.execution.platform.sandbox import ExecutionSandbox
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "data.txt").write_bytes(b"x" * 1024)

        sb = ExecutionSandbox(ws, "exec-sandbox-4")
        sb._base_dir = tmp_path / "executions"
        sb._root     = sb._base_dir / "exec-sandbox-4"
        paths = sb.create()

        freed = sb.cleanup()
        assert not sb._root.exists()
        # freed should be positive (some data was in the sandbox)


# ─────────────────────────────────────────────────────────────────────────────
# ExecutionMetrics
# ─────────────────────────────────────────────────────────────────────────────

class TestExecutionMetrics:
    def test_start_and_end_phase(self):
        from app.execution.platform.metrics import ExecutionMetrics
        m = ExecutionMetrics(execution_id="test-1")
        pm = m.start_phase("probe")
        assert pm.phase == "probe"
        assert pm.ended_at is None
        m.end_phase(pm, success=True)
        assert pm.ended_at is not None
        assert pm.success is True
        assert m.probe_duration_s is not None

    def test_derived_timing_by_phase_name(self):
        from app.execution.platform.metrics import ExecutionMetrics
        m = ExecutionMetrics(execution_id="test-2")
        for ph in ("install", "build", "launch"):
            pm = m.start_phase(ph)
            m.end_phase(pm, success=True)
        assert m.install_duration_s is not None
        assert m.build_duration_s is not None
        assert m.launch_duration_s is not None

    def test_finish_sets_outcome(self):
        from app.execution.platform.metrics import ExecutionMetrics
        m = ExecutionMetrics(execution_id="test-3")
        m.finish(success=True, exit_code=0)
        assert m.success is True
        assert m.total_duration_s is not None

    def test_to_dict_keys(self):
        from app.execution.platform.metrics import ExecutionMetrics
        m = ExecutionMetrics(execution_id="test-4")
        d = m.to_dict()
        for key in ("execution_id", "runtime", "started_at", "success", "phases"):
            assert key in d


# ─────────────────────────────────────────────────────────────────────────────
# ExecutionReport
# ─────────────────────────────────────────────────────────────────────────────

class TestExecutionReport:
    def test_finish_sets_fields(self):
        from app.execution.platform.report import ExecutionReport
        r = ExecutionReport(execution_id="r1")
        r.finish(success=True)
        assert r.success is True
        assert r.ended_at is not None

    def test_finish_error(self):
        from app.execution.platform.report import ExecutionReport
        r = ExecutionReport(execution_id="r2")
        r.finish(success=False, error_code="ENV_NODE_MISSING",
                 error_message="Node not found")
        assert r.success is False
        assert r.error_code == "ENV_NODE_MISSING"

    def test_to_dict_no_none_required_fields(self):
        from app.execution.platform.report import ExecutionReport
        r = ExecutionReport(execution_id="r3")
        r.finish(success=True)
        d = r.to_dict()
        assert d["execution_id"] == "r3"
        assert d["success"] is True

    def test_to_sse_dict(self):
        from app.execution.platform.report import ExecutionReport
        r = ExecutionReport(execution_id="r4")
        r.finish(success=True)
        d = r.to_sse_dict()
        assert d["type"] == "report"
        assert "report" in d


# ─────────────────────────────────────────────────────────────────────────────
# TypedEvent subclasses
# ─────────────────────────────────────────────────────────────────────────────

class TestTypedEvents:
    def test_execution_started_sse(self):
        from app.execution.platform.events import ExecutionStarted
        e = ExecutionStarted(execution_id="x", runtime="node", workspace="/tmp/ws")
        d = e.to_sse_dict()
        assert d["type"] == "execution_started"
        assert d["runtime"] == "node"

    def test_server_ready_sse(self):
        from app.execution.platform.events import ServerReady
        e = ServerReady(execution_id="x", preview_url="http://localhost:3000", port=3000)
        d = e.to_sse_dict()
        assert d["preview_url"] == "http://localhost:3000"

    def test_heartbeat_sse(self):
        from app.execution.platform.events import Heartbeat
        e = Heartbeat(execution_id="x")
        d = e.to_sse_dict()
        assert d["type"] == "heartbeat"

    def test_log_line_sse(self):
        from app.execution.platform.events import LogLine
        e = LogLine(execution_id="x", line="npm install", phase="install")
        d = e.to_sse_dict()
        assert d["type"] == "log"
        assert d["line"] == "npm install"

    def test_event_registry_complete(self):
        from app.execution.platform.events import EVENT_REGISTRY
        expected = {
            "execution_started", "probe_completed", "validation_passed",
            "validation_failed", "build_plan_generated",
            "install_started", "install_progress", "install_completed", "install_failed",
            "build_started", "build_progress", "build_completed", "build_failed",
            "server_starting", "server_ready", "health_check_passed",
            "artifact_collected", "execution_failed", "execution_finished",
            "cleanup_started", "cleanup_finished",
            "heartbeat", "log", "status", "html", "unsupported", "report",
        }
        assert expected == set(EVENT_REGISTRY.keys())


# ─────────────────────────────────────────────────────────────────────────────
# PlatformError hierarchy
# ─────────────────────────────────────────────────────────────────────────────

class TestPlatformErrors:
    def test_node_missing_factory(self):
        from app.execution.platform.errors import node_missing, ErrorCategory
        e = node_missing()
        assert e.code == "ENV_NODE_MISSING"
        assert e.category == ErrorCategory.ENVIRONMENT
        assert e.recoverable is False

    def test_install_failed_factory(self):
        from app.execution.platform.errors import install_failed
        e = install_failed(1, "npm", ["EACCES error"])
        assert e.code == "DEP_INSTALL_FAILED"
        assert "1" in e.message

    def test_server_timeout_factory(self):
        from app.execution.platform.errors import server_timeout
        e = server_timeout(3000, 30.0)
        assert "3000" in e.message
        assert e.recoverable is True

    def test_internal_factory(self):
        from app.execution.platform.errors import internal
        e = internal("unexpected NoneType")
        assert e.code == "INTERNAL_ERROR"
        assert e.recoverable is False

    def test_to_dict(self):
        from app.execution.platform.errors import pm_missing
        e = pm_missing(["npm", "pnpm"])
        d = e.to_dict()
        for key in ("code", "category", "message", "fix", "recoverable"):
            assert key in d


# ─────────────────────────────────────────────────────────────────────────────
# RuntimeRegistry
# ─────────────────────────────────────────────────────────────────────────────

class TestRuntimeRegistry:
    def test_default_has_four_runtimes(self):
        from app.execution.platform.runtimes.registry import RuntimeRegistry
        reg = RuntimeRegistry.default()
        assert len(reg.all()) == 4

    def test_priority_order(self):
        from app.execution.platform.runtimes.registry import RuntimeRegistry
        reg = RuntimeRegistry.default()
        priorities = [rt.priority for rt in reg.all()]
        assert priorities == sorted(priorities)

    def test_select_node_for_package_json(self, tmp_path):
        from app.execution.platform.runtimes.registry import RuntimeRegistry
        _make_node_project(tmp_path)
        reg = RuntimeRegistry.default()
        rt  = reg.select(tmp_path)
        assert rt is not None
        assert rt.name == "node"

    def test_select_python_for_requirements(self, tmp_path):
        from app.execution.platform.runtimes.registry import RuntimeRegistry
        _make_python_project(tmp_path)
        reg = RuntimeRegistry.default()
        rt  = reg.select(tmp_path)
        assert rt is not None
        assert rt.name == "python"

    def test_select_docker_for_dockerfile(self, tmp_path):
        from app.execution.platform.runtimes.registry import RuntimeRegistry
        _make_docker_project(tmp_path)
        reg = RuntimeRegistry.default()
        rt  = reg.select(tmp_path)
        assert rt is not None
        assert rt.name == "docker"

    def test_select_none_for_empty_dir(self, tmp_path):
        from app.execution.platform.runtimes.registry import RuntimeRegistry
        reg = RuntimeRegistry.default()
        rt  = reg.select(tmp_path)
        assert rt is None

    def test_custom_runtime_registers(self):
        from app.execution.platform.runtimes.registry import RuntimeRegistry
        from app.execution.platform.runtimes.abstract import AbstractRuntime

        class CustomRuntime(AbstractRuntime):
            name     = "custom"
            priority = 5
            def detect(self, ws): return True
            async def probe(self, ctx): pass
            async def install(self, ctx): pass
            async def build(self, ctx): pass
            async def launch(self, ctx): pass
            async def cleanup(self, ctx): pass

        reg = RuntimeRegistry()
        reg.register(CustomRuntime())
        assert len(reg.all()) == 1
        assert reg.all()[0].priority == 5


# ─────────────────────────────────────────────────────────────────────────────
# Runtime detect()
# ─────────────────────────────────────────────────────────────────────────────

class TestNodeRuntimeDetect:
    def test_detects_package_json(self, tmp_path):
        from app.execution.platform.runtimes.node import NodeRuntime
        _make_node_project(tmp_path)
        assert NodeRuntime().detect(tmp_path) is True

    def test_detects_js_files_without_package_json(self, tmp_path):
        from app.execution.platform.runtimes.node import NodeRuntime
        (tmp_path / "index.js").write_text("console.log('hi')")
        assert NodeRuntime().detect(tmp_path) is True

    def test_rejects_empty_dir(self, tmp_path):
        from app.execution.platform.runtimes.node import NodeRuntime
        assert NodeRuntime().detect(tmp_path) is False


class TestPythonRuntimeDetect:
    def test_detects_requirements(self, tmp_path):
        from app.execution.platform.runtimes.python_rt import PythonRuntime
        _make_python_project(tmp_path)
        assert PythonRuntime().detect(tmp_path) is True

    def test_detects_py_files(self, tmp_path):
        from app.execution.platform.runtimes.python_rt import PythonRuntime
        (tmp_path / "script.py").write_text("print('hi')")
        assert PythonRuntime().detect(tmp_path) is True


class TestDockerRuntimeDetect:
    def test_detects_dockerfile(self, tmp_path):
        from app.execution.platform.runtimes.docker_rt import DockerRuntime
        _make_docker_project(tmp_path)
        assert DockerRuntime().detect(tmp_path) is True

    def test_detects_compose_yaml(self, tmp_path):
        from app.execution.platform.runtimes.docker_rt import DockerRuntime
        (tmp_path / "docker-compose.yaml").write_text("services:\n  app:\n    image: nginx\n")
        assert DockerRuntime().detect(tmp_path) is True


class TestElectronRuntimeDetect:
    def test_detects_electron_dep(self, tmp_path):
        from app.execution.platform.runtimes.electron_rt import ElectronRuntime
        _make_electron_project(tmp_path)
        assert ElectronRuntime().detect(tmp_path) is True

    def test_rejects_plain_node_app(self, tmp_path):
        from app.execution.platform.runtimes.electron_rt import ElectronRuntime
        _make_node_project(tmp_path)
        assert ElectronRuntime().detect(tmp_path) is False


# ─────────────────────────────────────────────────────────────────────────────
# UnifiedExecutionEngine
# ─────────────────────────────────────────────────────────────────────────────

class TestUnifiedExecutionEngine:
    def _collect(self, coro) -> list[dict]:
        async def _run():
            events = []
            async for ev in coro:
                events.append(ev.to_sse_dict())
            return events
        return asyncio.run(_run())

    def test_missing_workspace_emits_execution_failed(self, tmp_path):
        from app.execution.platform.engine import UnifiedExecutionEngine
        engine = UnifiedExecutionEngine()
        ws     = tmp_path / "does_not_exist"

        events = self._collect(engine.run(ws))
        types  = [e["type"] for e in events]
        assert "execution_failed" in types
        assert "report" in types

    def test_no_matching_runtime_emits_execution_failed(self, tmp_path):
        from app.execution.platform.engine import UnifiedExecutionEngine
        from app.execution.platform.runtimes.registry import RuntimeRegistry

        empty_registry = RuntimeRegistry()  # no runtimes registered
        engine = UnifiedExecutionEngine(registry=empty_registry)

        ws = tmp_path / "ws"
        ws.mkdir()

        events = self._collect(engine.run(ws))
        types  = [e["type"] for e in events]
        assert "execution_failed" in types

    def test_successful_run_emits_report(self, tmp_path):
        from app.execution.platform.engine import UnifiedExecutionEngine
        from app.execution.platform.runtimes.abstract import AbstractRuntime
        from app.execution.platform.runtimes.registry import RuntimeRegistry
        from app.execution.platform.events import ServerReady

        class SuccessRuntime(AbstractRuntime):
            name     = "success"
            priority = 1
            def detect(self, ws): return True
            async def probe(self, ctx): pass
            async def install(self, ctx): pass
            async def build(self, ctx): pass
            async def launch(self, ctx):
                ctx.emit(ServerReady(
                    execution_id = ctx.execution_id,
                    preview_url  = "http://localhost:3000",
                    port         = 3000,
                ))
            async def cleanup(self, ctx): pass

        registry = RuntimeRegistry()
        registry.register(SuccessRuntime())
        engine = UnifiedExecutionEngine(registry=registry)

        ws = tmp_path / "ws"
        ws.mkdir()

        events = self._collect(engine.run(ws))
        types  = [e["type"] for e in events]
        assert "execution_started" in types
        assert "execution_finished" in types
        assert "report" in types

        report_event = next(e for e in events if e["type"] == "report")
        assert report_event["report"]["success"] is True

    def test_failed_runtime_emits_failed_and_report(self, tmp_path):
        from app.execution.platform.engine import UnifiedExecutionEngine
        from app.execution.platform.runtimes.abstract import AbstractRuntime
        from app.execution.platform.runtimes.registry import RuntimeRegistry
        from app.execution.platform.errors import node_missing

        class FailRuntime(AbstractRuntime):
            name     = "fail"
            priority = 1
            def detect(self, ws): return True
            async def probe(self, ctx): raise node_missing()
            async def install(self, ctx): pass
            async def build(self, ctx): pass
            async def launch(self, ctx): pass
            async def cleanup(self, ctx): pass

        registry = RuntimeRegistry()
        registry.register(FailRuntime())
        engine = UnifiedExecutionEngine(registry=registry)

        ws = tmp_path / "ws"
        ws.mkdir()

        events = self._collect(engine.run(ws))
        types  = [e["type"] for e in events]
        assert "execution_failed" in types
        assert "report" in types

        report_event = next(e for e in events if e["type"] == "report")
        assert report_event["report"]["success"] is False

    def test_cleanup_always_called_even_on_failure(self, tmp_path):
        from app.execution.platform.engine import UnifiedExecutionEngine
        from app.execution.platform.runtimes.abstract import AbstractRuntime
        from app.execution.platform.runtimes.registry import RuntimeRegistry
        from app.execution.platform.errors import node_missing

        cleaned_up = []

        class CleanupRuntime(AbstractRuntime):
            name     = "cleanup"
            priority = 1
            def detect(self, ws): return True
            async def probe(self, ctx): raise node_missing()
            async def install(self, ctx): pass
            async def build(self, ctx): pass
            async def launch(self, ctx): pass
            async def cleanup(self, ctx): cleaned_up.append(True)

        registry = RuntimeRegistry()
        registry.register(CleanupRuntime())
        engine = UnifiedExecutionEngine(registry=registry)

        ws = tmp_path / "ws"
        ws.mkdir()

        self._collect(engine.run(ws))
        assert len(cleaned_up) == 1

    def test_all_events_have_execution_id(self, tmp_path):
        from app.execution.platform.engine import UnifiedExecutionEngine
        from app.execution.platform.runtimes.abstract import AbstractRuntime
        from app.execution.platform.runtimes.registry import RuntimeRegistry

        class QuickRuntime(AbstractRuntime):
            name     = "quick"
            priority = 1
            def detect(self, ws): return True
            async def probe(self, ctx): pass
            async def install(self, ctx): pass
            async def build(self, ctx): pass
            async def launch(self, ctx): pass
            async def cleanup(self, ctx): pass

        registry = RuntimeRegistry()
        registry.register(QuickRuntime())
        engine = UnifiedExecutionEngine(registry=registry)

        ws = tmp_path / "ws"
        ws.mkdir()

        events = self._collect(engine.run(ws, execution_id="custom-exec-id"))
        for e in events:
            assert e.get("execution_id") == "custom-exec-id", \
                f"Event {e['type']} missing execution_id"
