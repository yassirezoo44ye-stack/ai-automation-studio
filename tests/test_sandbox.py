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

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
