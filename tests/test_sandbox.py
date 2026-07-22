"""
Agent Sandbox & Secure Execution Runtime — pure-logic, source-inspection,
and real-subprocess isolation tests, matching tests/test_plugins.py's
established style. The live-Postgres install/enable/disable/uninstall
flow through the full pipeline is exercised by a throwaway verification
script (same convention as every prior phase in this session).
"""
from __future__ import annotations

import asyncio
import os
import shutil
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


# ── Capability allowlist — additive, backward compatible ───────────────────

class TestCapabilityExtension(unittest.TestCase):
    def test_original_capabilities_still_present(self):
        from app.marketplace.security import ALL_KNOWN_CAPABILITIES
        original = {
            "network", "filesystem", "database", "shell_exec", "credentials_read",
            "clipboard", "camera", "microphone", "location", "notifications",
            "background_tasks", "third_party_api",
        }
        self.assertTrue(original.issubset(ALL_KNOWN_CAPABILITIES))

    def test_new_sandbox_capabilities_added(self):
        from app.marketplace.security import ALL_KNOWN_CAPABILITIES
        new = {"terminal", "environment_variables", "git_access", "docker_access",
               "browser_automation", "filesystem_write"}
        self.assertTrue(new.issubset(ALL_KNOWN_CAPABILITIES))

    def test_check_permission_manifest_still_validates_against_the_same_allowlist(self):
        from app.marketplace.security import check_permission_manifest
        self.assertEqual(check_permission_manifest(["network", "docker_access"]), [])
        self.assertEqual(len(check_permission_manifest(["not_a_real_capability"])), 1)


# ── SandboxLimits derivation ─────────────────────────────────────────────

class TestSandboxLimits(unittest.TestCase):
    def test_no_capabilities_grants_no_network(self):
        from app.sandbox.permissions import limits_from_granted_capabilities
        limits = limits_from_granted_capabilities(set())
        self.assertEqual(limits.network_policy, "none")
        self.assertFalse(limits.filesystem_write)
        self.assertFalse(limits.env_vars_allowed)

    def test_network_capability_widens_policy(self):
        from app.sandbox.permissions import limits_from_granted_capabilities
        limits = limits_from_granted_capabilities({"network"})
        self.assertNotEqual(limits.network_policy, "none")

    def test_unknown_capability_names_are_ignored_defensively(self):
        from app.sandbox.permissions import limits_from_granted_capabilities
        # manifest validation already rejects unknown capabilities at
        # declaration time; this is a second, cheap safety net — must not
        # raise or silently grant anything unexpected.
        limits = limits_from_granted_capabilities({"totally_made_up_capability"})
        self.assertEqual(limits.network_policy, "none")

    def test_filesystem_write_and_env_vars_flags(self):
        from app.sandbox.permissions import limits_from_granted_capabilities
        limits = limits_from_granted_capabilities({"filesystem_write", "environment_variables"})
        self.assertTrue(limits.filesystem_write)
        self.assertTrue(limits.env_vars_allowed)

    def test_docker_access_gets_shell_level_headroom(self):
        from app.sandbox.permissions import limits_from_granted_capabilities
        default = limits_from_granted_capabilities(set())
        limits  = limits_from_granted_capabilities({"docker_access"})
        self.assertGreater(limits.cpu_seconds, default.cpu_seconds)
        self.assertGreater(limits.timeout_s, default.timeout_s)

    def test_git_access_implies_filesystem_write(self):
        from app.sandbox.permissions import limits_from_granted_capabilities
        limits = limits_from_granted_capabilities({"git_access"})
        self.assertTrue(limits.filesystem_write)

    def test_browser_automation_widens_memory_and_timeout(self):
        from app.sandbox.permissions import limits_from_granted_capabilities
        default = limits_from_granted_capabilities(set())
        limits  = limits_from_granted_capabilities({"browser_automation"})
        self.assertGreater(limits.memory_mb, default.memory_mb)
        self.assertGreater(limits.timeout_s, default.timeout_s)


# ── Protocol wire format ─────────────────────────────────────────────────

class TestProtocol(unittest.TestCase):
    def test_request_json_roundtrip(self):
        from app.sandbox.protocol import SandboxRequest
        req = SandboxRequest(id="abc", call="invoke", method="my_tool", args=[1, "x"], kwargs={"a": 1})
        restored = SandboxRequest.from_json(req.to_json())
        self.assertEqual(restored.id, "abc")
        self.assertEqual(restored.call, "invoke")
        self.assertEqual(restored.method, "my_tool")
        self.assertEqual(restored.args, [1, "x"])
        self.assertEqual(restored.kwargs, {"a": 1})

    def test_response_json_roundtrip_with_error(self):
        from app.sandbox.protocol import SandboxResponse
        resp = SandboxResponse(id="x1", ok=False, error="boom")
        restored = SandboxResponse.from_json(resp.to_json())
        self.assertFalse(restored.ok)
        self.assertEqual(restored.error, "boom")


# ── Source-inspection: reuse, not reimplementation ──────────────────────

class TestSandboxReuse(unittest.TestCase):
    def test_permissions_imports_capabilities_not_redefines_them(self):
        import inspect
        import app.sandbox.permissions as mod
        src = inspect.getsource(mod)
        self.assertIn("from app.marketplace.security import ALL_KNOWN_CAPABILITIES", src)
        # must not hand-roll a second capability frozenset literal
        self.assertNotIn('frozenset({\n    "network"', src)

    def test_workspace_imports_execution_sandbox_not_reimplements_it(self):
        import inspect
        import app.sandbox.workspace as mod
        src = inspect.getsource(mod)
        self.assertIn("from app.execution.platform.sandbox import ExecutionSandbox", src)
        # must not redefine its own resource-limit constants
        self.assertNotIn("RLIMIT_AS", src)

    def test_loader_delegates_to_sandbox_manager_not_reimplements_isolation(self):
        import inspect
        from app.plugins.loader import PluginLoader
        src = inspect.getsource(PluginLoader.load)
        self.assertIn("get_sandbox_manager", src)
        self.assertNotIn("importlib.util.spec_from_file_location", src)


# ── Agent execution timeout enforcement ─────────────────────────────────

class TestAgentTimeoutEnforcement(unittest.TestCase):
    def test_execute_exceeding_max_execution_seconds_is_cut_off(self):
        from app.agents.base import AgentContext, AgentPermissions, AgentResult, EvolvableAgent

        class SlowAgent(EvolvableAgent):
            name = "slow_agent_test"

            @property
            def permissions(self):
                return AgentPermissions(max_execution_seconds=0.05)

            async def execute(self, ctx):
                await asyncio.sleep(5)
                return AgentResult.ok(self.name, "unreachable")

        async def run():
            agent = SlowAgent()
            ctx = AgentContext(input="x", args="", kernel=None, memory=None)
            return await agent.run(ctx)

        result = asyncio.run(run())
        self.assertFalse(result.success)
        self.assertIn("max_execution_seconds", result.error)

    def test_fast_agent_still_succeeds_normally(self):
        """Backward-compat: an agent well within its timeout must be
        completely unaffected by the new asyncio.wait_for wrapper."""
        from app.agents.base import AgentContext, AgentResult, EvolvableAgent

        class FastAgent(EvolvableAgent):
            name = "fast_agent_test"

            async def execute(self, ctx):
                return AgentResult.ok(self.name, "done")

        async def run():
            agent = FastAgent()
            ctx = AgentContext(input="x", args="", kernel=None, memory=None)
            return await agent.run(ctx)

        result = asyncio.run(run())
        self.assertTrue(result.success)
        self.assertEqual(result.output, "done")


# ── ToolPermissions backward compatibility ──────────────────────────────

class TestToolPermissionsBackwardCompat(unittest.TestCase):
    def test_defaults_preserve_prior_behavior(self):
        from app.core.ai.tools.sandbox import ToolPermissions
        perm = ToolPermissions()
        self.assertEqual(perm.network_policy, "full")
        self.assertEqual(perm.capabilities, frozenset())
        # untouched fields still behave exactly as before
        self.assertEqual(perm.timeout_s, 30.0)
        self.assertEqual(perm.allowed_for, {"*"})


# ── Real subprocess isolation (ProcessBackend) ──────────────────────────

_EXAMPLE_TOOL_CODE = (
    "from app.plugins.base import PluginBase, PluginContext, PluginType\n"
    "class IsoTestPlugin(PluginBase):\n"
    "    plugin_type = PluginType.TOOL\n"
    "    def register(self, ctx: PluginContext) -> None:\n"
    "        from app.plugins.adapters import adapt_tool\n"
    "        schema = {'name': 'iso_reverse', 'description': 'd', 'parameters': {'type': 'object', 'properties': {}}}\n"
    "        def handler(text: str):\n"
    "            import os\n"
    "            return {'reversed': text[::-1], 'pid': os.getpid()}\n"
    "        adapt_tool(schema, handler)\n"
)

_SLEEPY_PLUGIN_CODE = (
    "from app.plugins.base import PluginBase, PluginContext, PluginType\n"
    "import asyncio\n"
    "class SleepyPlugin(PluginBase):\n"
    "    plugin_type = PluginType.TOOL\n"
    "    def register(self, ctx: PluginContext) -> None:\n"
    "        from app.plugins.adapters import adapt_tool\n"
    "        schema = {'name': 'sleepy', 'description': 'd', 'parameters': {'type': 'object', 'properties': {}}}\n"
    "        async def handler():\n"
    "            await asyncio.sleep(30)\n"
    "            return {'done': True}\n"
    "        adapt_tool(schema, handler)\n"
)


class TestProcessBackendIsolation(unittest.TestCase):
    def _make_workspace(self, code: str) -> Path:
        workspace = Path(tempfile.mkdtemp(prefix="axon_sandbox_test_"))
        shutil.copy(
            Path(__file__).parent.parent / "app" / "plugins" / "base.py",
            workspace / "plugin_base.py",
        )
        (workspace / "plugin_code.py").write_text(code, encoding="utf-8")
        return workspace

    def test_worker_runs_in_a_different_process_than_the_caller(self):
        from app.sandbox.backends import ProcessBackend
        from app.sandbox.permissions import SandboxLimits

        workspace = self._make_workspace(_EXAMPLE_TOOL_CODE)

        async def rpc_handler(method, args, kwargs):
            return None

        async def run():
            backend = ProcessBackend()
            worker = await backend.spawn(
                installation_id=f"test-{uuid.uuid4().hex[:8]}", workspace_dir=workspace,
                entry_point="plugin_code:IsoTestPlugin", plugin_id="iso_test",
                org_id="test-org", config={}, limits=SandboxLimits(),
                secret_env={}, context_rpc_handler=rpc_handler,
            )
            try:
                regs = await worker.call("register", timeout=15)
                self.assertEqual(regs[0]["name"], "iso_reverse")
                result = await worker.call("invoke", method="iso_reverse", kwargs={"text": "hello"}, timeout=15)
                self.assertEqual(result["reversed"], "olleh")
                self.assertNotEqual(result["pid"], os.getpid())
            finally:
                await worker.stop()
                self.assertFalse(worker.is_alive)

        try:
            asyncio.run(run())
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    def test_broken_plugin_code_reports_error_without_crashing_the_manager(self):
        from app.sandbox.backends import ProcessBackend, WorkerCallError
        from app.sandbox.permissions import SandboxLimits

        workspace = self._make_workspace("this is not valid python :::: (")

        async def rpc_handler(method, args, kwargs):
            return None

        async def run():
            backend = ProcessBackend()
            worker = await backend.spawn(
                installation_id=f"test-{uuid.uuid4().hex[:8]}", workspace_dir=workspace,
                entry_point="plugin_code:DoesNotExist", plugin_id="broken",
                org_id="test-org", config={}, limits=SandboxLimits(),
                secret_env={}, context_rpc_handler=rpc_handler,
            )
            try:
                with self.assertRaises(WorkerCallError):
                    await worker.call("register", timeout=15)
            finally:
                await worker.stop()

        try:
            asyncio.run(run())
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    def test_call_timeout_raises_without_hanging(self):
        """A worker that never responds within the caller's timeout must
        raise a typed, catchable error — not hang the caller forever."""
        from app.sandbox.backends import ProcessBackend, WorkerCrashedError
        from app.sandbox.permissions import SandboxLimits

        workspace = self._make_workspace(_SLEEPY_PLUGIN_CODE)

        async def rpc_handler(method, args, kwargs):
            return None

        async def run():
            backend = ProcessBackend()
            worker = await backend.spawn(
                installation_id=f"test-{uuid.uuid4().hex[:8]}", workspace_dir=workspace,
                entry_point="plugin_code:SleepyPlugin", plugin_id="sleepy",
                org_id="test-org", config={}, limits=SandboxLimits(),
                secret_env={}, context_rpc_handler=rpc_handler,
            )
            try:
                await worker.call("register", timeout=15)
                with self.assertRaises(WorkerCrashedError):
                    await worker.call("invoke", method="sleepy", timeout=0.3)
            finally:
                await worker.stop()

        try:
            asyncio.run(run())
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    def test_worker_crash_mid_call_is_reported_not_silently_hung(self):
        """Kill the worker process out from under an in-flight call — the
        caller must get a typed error, matching Step 8's 'no orphaned
        processes / faulty plugins cannot compromise platform stability'
        requirement."""
        from app.sandbox.backends import ProcessBackend, WorkerCrashedError
        from app.sandbox.permissions import SandboxLimits

        workspace = self._make_workspace(_EXAMPLE_TOOL_CODE)

        async def rpc_handler(method, args, kwargs):
            return None

        async def run():
            backend = ProcessBackend()
            worker = await backend.spawn(
                installation_id=f"test-{uuid.uuid4().hex[:8]}", workspace_dir=workspace,
                entry_point="plugin_code:IsoTestPlugin", plugin_id="iso_test",
                org_id="test-org", config={}, limits=SandboxLimits(),
                secret_env={}, context_rpc_handler=rpc_handler,
            )
            await worker.call("register", timeout=15)
            worker._process.kill()
            await worker._process.wait()
            with self.assertRaises(WorkerCrashedError):
                await worker.call("invoke", method="iso_reverse", kwargs={"text": "x"}, timeout=5)

        try:
            asyncio.run(run())
        finally:
            shutil.rmtree(workspace, ignore_errors=True)


# ── get_sandbox_backend() fallback selection ────────────────────────────

class TestBackendSelection(unittest.TestCase):
    def test_forced_process_backend_via_env_var(self):
        from app.sandbox import backends

        async def run():
            backends._backend = None
            backends._backend_name = None
            old = os.environ.get("SANDBOX_BACKEND")
            os.environ["SANDBOX_BACKEND"] = "process"
            try:
                backend = await backends.get_sandbox_backend()
                self.assertIsInstance(backend, backends.ProcessBackend)
                self.assertEqual(backends.get_sandbox_backend_name(), "process")
            finally:
                if old is None:
                    del os.environ["SANDBOX_BACKEND"]
                else:
                    os.environ["SANDBOX_BACKEND"] = old
                backends._backend = None
                backends._backend_name = None


# ── Network allowlist (new gap) ──────────────────────────────────────────

class TestNetworkAllowlist(unittest.TestCase):
    def test_network_capability_with_no_domains_still_gets_allowlist_not_full(self):
        """Declaring the capability alone must not grant unrestricted
        access — see limits_from_granted_capabilities' safe-by-default
        fix for the security regression caught mid-development."""
        from app.sandbox.permissions import limits_from_granted_capabilities
        limits = limits_from_granted_capabilities({"network"})
        self.assertEqual(limits.network_policy, "allowlist")
        self.assertEqual(limits.allowed_domains, [])

    def test_declared_domains_populate_allowed_domains(self):
        from app.sandbox.permissions import limits_from_granted_capabilities
        limits = limits_from_granted_capabilities(
            {"network"}, network_domains=["api.example.com", "auth.example.com"],
        )
        self.assertEqual(limits.network_policy, "allowlist")
        self.assertEqual(limits.allowed_domains, ["api.example.com", "auth.example.com"])

    def test_domains_ignored_without_the_network_capability(self):
        from app.sandbox.permissions import limits_from_granted_capabilities
        limits = limits_from_granted_capabilities(set(), network_domains=["api.example.com"])
        self.assertEqual(limits.network_policy, "none")
        self.assertEqual(limits.allowed_domains, [])

    def test_manifest_network_domains_field_exists(self):
        from app.plugins.manifest import PluginManifest
        self.assertIn("network_domains", PluginManifest.model_fields)

    def test_loader_threads_manifest_domains_into_spawn_worker(self):
        import inspect
        from app.plugins.loader import PluginLoader
        source = inspect.getsource(PluginLoader.load)
        self.assertIn("network_domains=manifest.network_domains", source)


class TestDNSAllowlistResolution(unittest.TestCase):
    def test_resolves_a_real_hostname(self):
        from app.sandbox.backends import _resolve_allowed_domains

        async def run():
            return await _resolve_allowed_domains(["localhost"])

        result = asyncio.run(run())
        self.assertIn("localhost", result)

    def test_unresolvable_domain_is_skipped_not_raised(self):
        from app.sandbox.backends import _resolve_allowed_domains

        async def run():
            return await _resolve_allowed_domains(["this-domain-should-not-exist-1234567890.invalid"])

        result = asyncio.run(run())
        self.assertEqual(result, {})

    def test_internal_policy_uses_a_real_docker_network_not_a_none_degrade(self):
        import inspect
        from app.sandbox import backends
        source = inspect.getsource(backends.DockerBackend.spawn)
        self.assertIn("_ensure_internal_network", source)
        self.assertIn("_INTERNAL_NETWORK_NAME", source)


# ── Worker default_timeout (SandboxLimits.timeout_s activation, new gap) ────

class TestWorkerDefaultTimeout(unittest.TestCase):
    def test_spawned_worker_carries_the_derived_timeout(self):
        from app.sandbox.backends import ProcessBackend
        from app.sandbox.permissions import SandboxLimits

        async def rpc_handler(method, args, kwargs):
            return None

        async def run():
            ws = Path(tempfile.mkdtemp(prefix="axon_sandbox_test_"))
            shutil.copy(
                Path(__file__).parent.parent / "app" / "plugins" / "base.py",
                ws / "plugin_base.py",
            )
            (ws / "plugin_code.py").write_text(_EXAMPLE_TOOL_CODE, encoding="utf-8")
            backend = ProcessBackend()
            worker = await backend.spawn(
                installation_id=f"test-{uuid.uuid4().hex[:8]}", workspace_dir=ws,
                entry_point="plugin_code:IsoTestPlugin", plugin_id="iso_test",
                org_id="test-org", config={}, limits=SandboxLimits(timeout_s=42.0),
                secret_env={}, context_rpc_handler=rpc_handler,
            )
            try:
                self.assertEqual(worker.default_timeout, 42.0)
            finally:
                await worker.stop()
            shutil.rmtree(ws, ignore_errors=True)

        asyncio.run(run())

    def test_call_omitting_timeout_falls_back_to_default_not_hardcoded_30(self):
        """A Worker built with a short default_timeout must time out near
        that value on a call with no explicit `timeout=` kwarg — proving
        the fallback is live, not just stored and ignored."""
        from app.sandbox.backends import ProcessBackend, WorkerCrashedError
        from app.sandbox.permissions import SandboxLimits

        async def rpc_handler(method, args, kwargs):
            return None

        async def run():
            ws = Path(tempfile.mkdtemp(prefix="axon_sandbox_test_"))
            shutil.copy(
                Path(__file__).parent.parent / "app" / "plugins" / "base.py",
                ws / "plugin_base.py",
            )
            (ws / "plugin_code.py").write_text(_SLEEPY_PLUGIN_CODE, encoding="utf-8")
            backend = ProcessBackend()
            worker = await backend.spawn(
                installation_id=f"test-{uuid.uuid4().hex[:8]}", workspace_dir=ws,
                entry_point="plugin_code:SleepyPlugin", plugin_id="sleepy",
                org_id="test-org", config={}, limits=SandboxLimits(timeout_s=0.3),
                secret_env={}, context_rpc_handler=rpc_handler,
            )
            try:
                await worker.call("register", timeout=15)
                with self.assertRaises(WorkerCrashedError):
                    await worker.call("invoke", method="sleepy")  # no explicit timeout=
            finally:
                await worker.stop()
            shutil.rmtree(ws, ignore_errors=True)

        asyncio.run(run())


# ── Plugin crash recovery (new gap) ──────────────────────────────────────

class TestCrashRecovery(unittest.TestCase):
    def test_call_worker_respawns_once_on_crash_then_succeeds(self):
        from app.sandbox.backends import WorkerCrashedError
        from app.sandbox.manager import SandboxManager
        from unittest.mock import AsyncMock, patch

        manager = SandboxManager()
        installation_id = "crash-test-1"
        crashed = AsyncMock()
        crashed.is_alive = True
        crashed.call = AsyncMock(side_effect=WorkerCrashedError("dead"))
        healthy = AsyncMock()
        healthy.is_alive = True
        healthy.call = AsyncMock(return_value={"ok": True})
        manager._workers[installation_id] = crashed

        async def fake_respawn(iid):
            manager._workers[iid] = healthy
            return healthy

        async def run():
            with patch.object(manager, "_respawn", side_effect=fake_respawn) as mock_respawn:
                result = await manager.call_worker(installation_id, "invoke", method="m")
                self.assertEqual(result, {"ok": True})
                mock_respawn.assert_called_once()

        asyncio.run(run())

    def test_call_worker_respawns_when_no_worker_yet(self):
        from app.sandbox.manager import SandboxManager
        from unittest.mock import AsyncMock, patch

        manager = SandboxManager()
        installation_id = "no-worker-yet"
        healthy = AsyncMock()
        healthy.is_alive = True
        healthy.call = AsyncMock(return_value="result")

        async def fake_respawn(iid):
            return healthy

        async def run():
            with patch.object(manager, "_respawn", side_effect=fake_respawn) as mock_respawn:
                result = await manager.call_worker(installation_id, "invoke")
                self.assertEqual(result, "result")
                mock_respawn.assert_called_once()

        asyncio.run(run())

    def test_second_consecutive_crash_propagates_not_retried_again(self):
        """Exactly one respawn attempt — a plugin that crashes on every
        call must not respawn in an infinite loop on every proxy call."""
        from app.sandbox.backends import WorkerCrashedError
        from app.sandbox.manager import SandboxManager
        from unittest.mock import AsyncMock, patch

        manager = SandboxManager()
        installation_id = "double-crash"
        crashed1 = AsyncMock()
        crashed1.is_alive = True
        crashed1.call = AsyncMock(side_effect=WorkerCrashedError("first"))
        crashed2 = AsyncMock()
        crashed2.is_alive = True
        crashed2.call = AsyncMock(side_effect=WorkerCrashedError("second"))
        manager._workers[installation_id] = crashed1
        respawn_calls = []

        async def fake_respawn(iid):
            respawn_calls.append(iid)
            manager._workers[iid] = crashed2
            return crashed2

        async def run():
            with patch.object(manager, "_respawn", side_effect=fake_respawn):
                with self.assertRaises(WorkerCrashedError):
                    await manager.call_worker(installation_id, "invoke")

        asyncio.run(run())
        self.assertEqual(len(respawn_calls), 1)

    def test_respawn_raises_when_no_cached_spawn_kwargs(self):
        """A worker that crashed but was never spawned through this
        manager instance (e.g. process restart) can't be silently
        resurrected — it must fail loudly, not hang."""
        from app.sandbox.backends import WorkerCrashedError
        from app.sandbox.manager import SandboxManager

        manager = SandboxManager()

        async def run():
            with self.assertRaises(WorkerCrashedError):
                await manager._respawn("never-spawned-through-this-manager")

        asyncio.run(run())

    def test_proxies_route_through_installation_id_not_a_fixed_worker(self):
        import inspect
        from app.plugins import adapters
        params = inspect.signature(adapters.WorkerProxyCallable.__init__).parameters
        self.assertIn("installation_id", params)
        self.assertNotIn("worker", params)


# ── Plugin Telemetry (real MetricsRegistry wiring, new gap) ─────────────

class TestPluginTelemetry(unittest.TestCase):
    def test_emit_metric_records_into_metrics_registry(self):
        from app.core.observability.metrics import get_metrics
        from app.sandbox.manager import SandboxManager

        manager = SandboxManager()
        installation_id = f"telemetry-test-{uuid.uuid4().hex[:8]}"
        manager._spawn_kwargs[installation_id] = {
            "installation_id": installation_id, "org_id": "o1", "plugin_id": "my_test_plugin",
            "entry_point": "x:Y", "code": "", "config": {}, "network_domains": None,
        }

        async def run():
            await manager._service_context_rpc(installation_id, "emit_metric", ["requests", 42], {})

        asyncio.run(run())
        gauge = get_metrics()._gauges.get("plugin_my_test_plugin_requests")
        self.assertIsNotNone(gauge)
        self.assertEqual(gauge.value, 42.0)

    def test_non_numeric_metric_value_is_skipped_not_raised(self):
        from app.sandbox.manager import SandboxManager

        manager = SandboxManager()
        installation_id = f"telemetry-bad-{uuid.uuid4().hex[:8]}"

        async def run():
            await manager._service_context_rpc(installation_id, "emit_metric", ["bad", "not-a-number"], {})

        asyncio.run(run())  # must not raise

    def test_plugin_context_docstring_documents_the_real_wiring(self):
        # Reads the source file directly rather than importing PluginContext
        # — TestPluginLoaderIsolation (tests/test_plugins.py) exercises
        # runner_entrypoint._load_plugin_code(), which (by design, to make
        # a plugin's own `from app.plugins.base import ...` resolve inside
        # its isolated worker) reassigns sys.modules["app.plugins.base"]
        # for the rest of the pytest process — a fresh import here would
        # pick up that substituted copy instead of the real module.
        source = (Path(__file__).parent.parent / "app" / "plugins" / "base.py").read_text(encoding="utf-8")
        self.assertIn("MetricsRegistry", source)


# ── Dedicated sandbox worker health probe (new gap) ─────────────────────

class TestSandboxHealthProbe(unittest.TestCase):
    def test_registers_a_distinct_probe_name(self):
        import inspect
        from app.sandbox import health as sandbox_health
        source = inspect.getsource(sandbox_health.register_sandbox_health_probe)
        self.assertIn('"sandbox_workers"', source)

    def test_exported_from_sandbox_package(self):
        from app.sandbox import register_sandbox_health_probe
        self.assertTrue(callable(register_sandbox_health_probe))

    def test_wired_into_factory_alongside_but_distinct_from_plugin_loader_probe(self):
        import inspect
        from app import factory
        source = inspect.getsource(factory)
        self.assertIn("register_sandbox_health_probe", source)


if __name__ == "__main__":
    unittest.main()
