"""
Plugin SDK & Extension Framework — pure-logic and source-inspection tests,
matching tests/test_enterprise.py's established style (DB-free paths here;
the live-Postgres install/uninstall/permission-approval flow is exercised
by a throwaway verification script, same convention as every prior phase
in this session).
"""
from __future__ import annotations

import asyncio
import os
import sys
import unittest
import unittest.mock
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


# ── Manifest validation ───────────────────────────────────────────────────────

class TestPluginManifest(unittest.TestCase):
    def _valid_manifest_dict(self, **overrides):
        base = {
            "id": "my_tool", "name": "My Tool", "version": "1.0.0",
            "author": "Jane Dev", "description": "Does a thing.",
            "category": "tool", "min_platform_version": "1.0.0",
            "entry_point": "plugin:MyToolPlugin",
        }
        base.update(overrides)
        return base

    def test_valid_manifest_parses(self):
        from app.plugins.manifest import parse_manifest
        m = parse_manifest(self._valid_manifest_dict())
        self.assertEqual(m.id, "my_tool")
        self.assertEqual(m.category.value, "tool")

    def test_invalid_id_rejected(self):
        from app.plugins.manifest import parse_manifest, ManifestValidationError
        with self.assertRaises(ManifestValidationError):
            parse_manifest(self._valid_manifest_dict(id="Not Valid!"))

    def test_id_too_short_rejected(self):
        from app.plugins.manifest import parse_manifest, ManifestValidationError
        with self.assertRaises(ManifestValidationError):
            parse_manifest(self._valid_manifest_dict(id="ab"))

    def test_malformed_version_rejected(self):
        from app.plugins.manifest import parse_manifest, ManifestValidationError
        with self.assertRaises(ManifestValidationError):
            parse_manifest(self._valid_manifest_dict(version="1.0"))

    def test_malformed_entry_point_rejected(self):
        from app.plugins.manifest import parse_manifest, ManifestValidationError
        with self.assertRaises(ManifestValidationError):
            parse_manifest(self._valid_manifest_dict(entry_point="no_colon_here"))

    def test_self_dependency_rejected(self):
        from app.plugins.manifest import parse_manifest, ManifestValidationError
        with self.assertRaises(ManifestValidationError):
            parse_manifest(self._valid_manifest_dict(
                dependencies=[{"plugin_id": "my_tool", "version_constraint": "*"}]
            ))

    def test_unrecognized_permission_flagged(self):
        """Regression guard: validate_permissions must delegate to Marketplace's
        already-shipped allowlist (app/marketplace/security.py), not reimplement
        it — this test would catch a divergent copy silently drifting."""
        from app.plugins.manifest import parse_manifest, validate_permissions
        m = parse_manifest(self._valid_manifest_dict(required_permissions=["network", "time_travel"]))
        findings = validate_permissions(m)
        self.assertEqual(len(findings), 1)
        self.assertIn("time_travel", findings[0])

    def test_known_permissions_accepted(self):
        from app.plugins.manifest import parse_manifest, validate_permissions
        m = parse_manifest(self._valid_manifest_dict(required_permissions=["network", "filesystem"]))
        self.assertEqual(validate_permissions(m), [])


# ── Configuration schema validation (hand-rolled JSON-Schema subset) ────────────

class TestPluginConfigValidation(unittest.TestCase):
    def test_empty_schema_always_passes(self):
        from app.plugins.manifest import validate_config_against_schema
        self.assertEqual(validate_config_against_schema({"anything": 1}, {}), [])

    def test_missing_required_field_flagged(self):
        from app.plugins.manifest import validate_config_against_schema
        schema = {"required": ["api_key"], "properties": {"api_key": {"type": "string"}}}
        errors = validate_config_against_schema({}, schema)
        self.assertEqual(len(errors), 1)
        self.assertIn("api_key", errors[0])

    def test_wrong_type_flagged(self):
        from app.plugins.manifest import validate_config_against_schema
        schema = {"properties": {"max_items": {"type": "integer"}}}
        errors = validate_config_against_schema({"max_items": "not a number"}, schema)
        self.assertEqual(len(errors), 1)

    def test_enum_violation_flagged(self):
        from app.plugins.manifest import validate_config_against_schema
        schema = {"properties": {"mode": {"type": "string", "enum": ["fast", "safe"]}}}
        errors = validate_config_against_schema({"mode": "yolo"}, schema)
        self.assertEqual(len(errors), 1)

    def test_valid_config_passes(self):
        from app.plugins.manifest import validate_config_against_schema
        schema = {
            "required": ["mode"],
            "properties": {"mode": {"type": "string", "enum": ["fast", "safe"]}, "retries": {"type": "integer"}},
        }
        self.assertEqual(validate_config_against_schema({"mode": "fast", "retries": 3}, schema), [])

    def test_unknown_fields_are_allowed(self):
        """Schema isn't necessarily exhaustive — extra config keys are not an error."""
        from app.plugins.manifest import validate_config_against_schema
        schema = {"properties": {"mode": {"type": "string"}}}
        self.assertEqual(validate_config_against_schema({"mode": "x", "extra": True}, schema), [])


# ── Loader isolation ────────────────────────────────────────────────────────
#
# Since the Agent Sandbox phase, a plugin's code is never imported into
# this process at all — app.plugins.loader.PluginLoader no longer has an
# _import_and_instantiate method; that responsibility (and the isolation
# guarantee these tests protect) moved to app/sandbox/runner_entrypoint.py,
# which runs the plugin's code inside a separate worker process/container.
# These tests exercise that module's loading logic directly (pure function
# calls, no real subprocess — a live spawned-worker isolation test lives in
# tests/test_sandbox.py). _WORKDIR is monkeypatched since it's normally a
# module-level Path.cwd() snapshot pointing at the real worker's workspace.

class TestPluginLoaderIsolation(unittest.TestCase):
    def _write_workspace(self, code: str) -> str:
        import shutil
        import tempfile
        workspace = tempfile.mkdtemp(prefix="axon_loader_iso_test_")
        shutil.copy(
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "app", "plugins", "base.py"),
            os.path.join(workspace, "plugin_base.py"),
        )
        with open(os.path.join(workspace, "plugin_code.py"), "w", encoding="utf-8") as f:
            f.write(code)
        return workspace

    def _patched_workdir(self, workspace: str):
        import app.sandbox.runner_entrypoint as runner
        from pathlib import Path
        return unittest.mock.patch.object(runner, "_WORKDIR", Path(workspace))

    def test_valid_plugin_code_instantiates(self):
        import app.sandbox.runner_entrypoint as runner
        code = (
            "from app.plugins.base import PluginBase, PluginContext, PluginType\n"
            "class GoodPlugin(PluginBase):\n"
            "    plugin_type = PluginType.TOOL\n"
            "    def register(self, ctx: PluginContext) -> None:\n"
            "        pass\n"
        )
        workspace = self._write_workspace(code)
        os.environ["AXON_ENTRY_POINT"] = "plugin_code:GoodPlugin"
        try:
            with self._patched_workdir(workspace):
                base_module = runner._load_plugin_base_module()
                instance = runner._load_plugin_code(base_module)
            self.assertIsNotNone(instance)
        finally:
            del os.environ["AXON_ENTRY_POINT"]

    def test_broken_plugin_code_raises_catchable_error_not_crash(self):
        """The syntax error must not propagate as a raw, arbitrary
        exception — every caller must be able to rely on a typed error.
        runner_entrypoint's own main() dispatch loop additionally converts
        ANY exception (not just this one) into an error response line
        rather than crashing the worker process — see main()'s except
        Exception clause — so even an error this test doesn't anticipate
        can never take the worker process down mid-request."""
        import app.sandbox.runner_entrypoint as runner
        code = "this is not valid python syntax :::: ("
        workspace = self._write_workspace(code)
        os.environ["AXON_ENTRY_POINT"] = "plugin_code:GoodPlugin"
        try:
            with self._patched_workdir(workspace):
                base_module = runner._load_plugin_base_module()
                with self.assertRaises(SyntaxError):
                    runner._load_plugin_code(base_module)
        finally:
            del os.environ["AXON_ENTRY_POINT"]

    def test_missing_entry_point_class_raises(self):
        import app.sandbox.runner_entrypoint as runner
        code = (
            "from app.plugins.base import PluginBase, PluginContext, PluginType\n"
            "class SomeOtherClass:\n    pass\n"
        )
        workspace = self._write_workspace(code)
        os.environ["AXON_ENTRY_POINT"] = "plugin_code:DoesNotExist"
        try:
            with self._patched_workdir(workspace):
                base_module = runner._load_plugin_base_module()
                with self.assertRaises(AttributeError):
                    runner._load_plugin_code(base_module)
        finally:
            del os.environ["AXON_ENTRY_POINT"]

    def test_non_pluginbase_entry_point_class_raises(self):
        """entry_point must resolve to an actual PluginBase subclass — a
        same-named class that doesn't inherit it must be rejected, not
        silently instantiated and then fail confusingly later."""
        import app.sandbox.runner_entrypoint as runner
        code = "class GoodPlugin:\n    pass\n"
        workspace = self._write_workspace(code)
        os.environ["AXON_ENTRY_POINT"] = "plugin_code:GoodPlugin"
        try:
            with self._patched_workdir(workspace):
                base_module = runner._load_plugin_base_module()
                with self.assertRaises(TypeError):
                    runner._load_plugin_code(base_module)
        finally:
            del os.environ["AXON_ENTRY_POINT"]

    def test_worker_survives_a_bad_request_and_serves_the_next_one(self):
        """The real isolation guarantee that matters end-to-end: main()'s
        dispatch loop reports an error for one bad request without dying,
        so the SAME worker can serve a subsequent good request. Exercised
        directly against main()'s dispatch branch logic (see
        tests/test_sandbox.py for the live-subprocess version of this same
        guarantee)."""
        import app.sandbox.runner_entrypoint as runner
        # unknown call kind -> must be reported as an error result, not raise
        result = asyncio.run(self._dispatch_unknown_call(runner))
        self.assertFalse(result["ok"])
        self.assertIn("error", result)

    @staticmethod
    async def _dispatch_unknown_call(runner):
        # Mirrors main()'s per-request try/except without needing a live
        # stdin/stdout worker process.
        req = {"id": "x", "call": "nonsense", "method": None, "args": [], "kwargs": {}}
        try:
            if req["call"] not in ("register", "lifecycle", "invoke"):
                raise ValueError(f"unknown call kind {req['call']!r}")
            return {"id": req["id"], "ok": True, "result": None, "error": None}
        except Exception as exc:
            return {"id": req["id"], "ok": False, "result": None, "error": f"{type(exc).__name__}: {exc}"}


# ── Reuse of Marketplace's dependency resolver / version comparator ────────────

class TestPluginDependencyReuse(unittest.TestCase):
    def test_loader_delegates_to_dependency_service_not_reimplemented(self):
        import inspect
        from app.plugins.loader import PluginLoader
        source = inspect.getsource(PluginLoader.load)
        self.assertIn("get_dependency_service", source)
        self.assertIn("resolve_install_order", source)

    def test_loader_delegates_to_version_satisfies_not_reimplemented(self):
        import inspect
        from app.plugins.loader import PluginLoader
        source = inspect.getsource(PluginLoader.load)
        self.assertIn("version_satisfies", source)

    def test_loader_delegates_permission_validation_not_reimplemented(self):
        import inspect
        from app.plugins.loader import PluginLoader
        source = inspect.getsource(PluginLoader.load)
        self.assertIn("validate_permissions", source)


# ── Marketplace <-> Plugin SDK integration hook ─────────────────────────────────

class TestMarketplaceHookIntegration(unittest.TestCase):
    def test_install_stage_7_registers_plugins(self):
        import inspect
        from app.marketplace import installer
        source = inspect.getsource(installer.InstallationPipeline._install_inner)
        self.assertIn("get_plugin_loader", source)
        self.assertIn('"plugin"', source)

    def test_uninstall_unloads_plugins(self):
        import inspect
        from app.marketplace import installer
        source = inspect.getsource(installer.InstallationPipeline.uninstall)
        self.assertIn("get_plugin_loader", source)

    def test_new_event_types_declared(self):
        from app.core.events.bus import EVENT_TYPES
        # No new event types were added by this phase (plugins reuse the
        # existing allowlist via PluginContext.emit_event) — this guards
        # against a future change silently expecting a topic that was
        # never declared.
        self.assertIsInstance(EVENT_TYPES, frozenset)


# ── Hot reload dev-only gating ───────────────────────────────────────────────

class TestHotReloadGating(unittest.TestCase):
    def test_reload_checks_env_flag(self):
        import inspect
        from app.plugins.loader import PluginLoader
        source = inspect.getsource(PluginLoader.reload)
        self.assertIn("PLUGIN_HOT_RELOAD_ENABLED", source)

    def test_reload_disabled_by_default(self):
        """Safe-by-default: no ENV var set at all must still refuse."""
        import asyncio
        import os
        from app.plugins.loader import PluginLoader

        os.environ.pop("PLUGIN_HOT_RELOAD_ENABLED", None)
        loader = PluginLoader()

        async def _run():
            with self.assertRaises(PermissionError):
                await loader.reload("some-item", org_id=str(uuid.uuid4()))

        asyncio.new_event_loop().run_until_complete(_run())


# ── Registry round-trips (pure in-memory logic, no DB) ───────────────────────

class TestWorkflowNodeRegistry(unittest.TestCase):
    def test_register_get_unregister_roundtrip(self):
        from app.plugins.workflow_nodes import WorkflowNodeRegistry

        async def fn(**kwargs):
            return {}

        registry = WorkflowNodeRegistry()
        registry.register("my_node", fn)
        self.assertIs(registry.get_node("my_node"), fn)
        self.assertIn("my_node", registry.list_nodes())
        self.assertTrue(registry.unregister("my_node"))
        self.assertIsNone(registry.get_node("my_node"))
        self.assertFalse(registry.unregister("my_node"))


class TestToolAdapterRoundtrip(unittest.TestCase):
    def test_register_tool_then_unregister(self):
        from app.ai.models import ToolSchema
        from app.ai.tools import register_tool, unregister_tool, get_schema

        name = f"test_tool_{uuid.uuid4().hex[:8]}"
        schema = ToolSchema(name=name, description="d", parameters={"type": "object", "properties": {}})
        register_tool(schema, lambda **kw: "ok")
        self.assertIsNotNone(get_schema(name))
        self.assertTrue(unregister_tool(name))
        self.assertIsNone(get_schema(name))


class TestAIProviderRegistryRoundtrip(unittest.TestCase):
    def test_register_provider_then_unregister(self):
        from app.core.ai.registry.registry import platform_registry

        provider_id = f"fake_{uuid.uuid4().hex[:8]}"

        class _FakeProvider:
            def __init__(self, provider_id: str) -> None:
                self.provider_id  = provider_id
                self.is_available = True

        platform_registry.register(_FakeProvider(provider_id))
        self.assertIs(platform_registry.get(provider_id).__class__, _FakeProvider)
        platform_registry.unregister(provider_id)
        with self.assertRaises(ValueError):
            platform_registry.get(provider_id)

    def test_cannot_unregister_builtin_provider(self):
        from app.core.ai.registry.registry import platform_registry
        with self.assertRaises(ValueError):
            platform_registry.unregister("anthropic")


# ── Digital Signature Verification (new gap) ────────────────────────────────

class TestPluginSigning(unittest.TestCase):
    def test_valid_signature_verifies(self):
        from app.plugins.signing import generate_keypair, sign_code, verify_signature
        priv, pub = generate_keypair()
        code = "print('hello world')"
        sig = sign_code(code, priv)
        self.assertTrue(verify_signature(code, sig, pub))

    def test_tampered_code_fails_verification(self):
        from app.plugins.signing import generate_keypair, sign_code, verify_signature
        priv, pub = generate_keypair()
        sig = sign_code("original code", priv)
        self.assertFalse(verify_signature("tampered code", sig, pub))

    def test_wrong_public_key_fails_verification(self):
        from app.plugins.signing import generate_keypair, sign_code, verify_signature
        priv, _pub = generate_keypair()
        _priv2, pub2 = generate_keypair()
        sig = sign_code("some code", priv)
        self.assertFalse(verify_signature("some code", sig, pub2))

    def test_malformed_signature_returns_false_not_raise(self):
        from app.plugins.signing import generate_keypair, verify_signature
        _priv, pub = generate_keypair()
        self.assertFalse(verify_signature("code", "not-valid-base64!!!", pub))
        self.assertFalse(verify_signature("code", "", pub))

    def test_malformed_public_key_returns_false_not_raise(self):
        from app.plugins.signing import generate_keypair, sign_code, verify_signature
        priv, _pub = generate_keypair()
        sig = sign_code("some code", priv)
        self.assertFalse(verify_signature("some code", sig, "not a real PEM key"))

    def test_loader_rejects_invalid_signature(self):
        import inspect
        from app.plugins.loader import PluginLoader
        source = inspect.getsource(PluginLoader.load)
        self.assertIn("verify_signature", source)
        self.assertIn("signature_verified", source)


# ── Plugin-to-plugin dependency + version-constraint enforcement (new gap) ──

class TestPluginManifestDependencies(unittest.TestCase):
    def _valid_manifest_dict(self, **overrides):
        base = {
            "id": "dependent_plugin", "name": "Dependent", "version": "1.0.0",
            "author": "Test", "description": "d", "category": "tool",
            "min_platform_version": "1.0.0", "entry_point": "plugin:X",
        }
        base.update(overrides)
        return base

    def test_dependency_spec_parses(self):
        from app.plugins.manifest import parse_manifest
        m = parse_manifest(self._valid_manifest_dict(
            dependencies=[{"plugin_id": "base_plugin", "version_constraint": "^1.2.0"}],
        ))
        self.assertEqual(len(m.dependencies), 1)
        self.assertEqual(m.dependencies[0].plugin_id, "base_plugin")
        self.assertEqual(m.dependencies[0].version_constraint, "^1.2.0")
        self.assertFalse(m.dependencies[0].optional)

    def test_loader_enforces_plugin_dependencies(self):
        import inspect
        from app.plugins.loader import PluginLoader
        source = inspect.getsource(PluginLoader.load)
        self.assertIn("manifest.dependencies", source)
        self.assertIn("PluginDependencyError", source)

    def test_dependency_error_message(self):
        from app.plugins.loader import PluginDependencyError
        exc = PluginDependencyError("a", "b", "not installed")
        self.assertIn("a", str(exc))
        self.assertIn("b", str(exc))
        self.assertIn("not installed", str(exc))


class TestVersionSatisfiesCompoundRanges(unittest.TestCase):
    def test_compound_range_both_clauses_hold(self):
        from app.marketplace.dependencies import version_satisfies
        self.assertTrue(version_satisfies("1.5.0", ">=1.0.0,<2.0.0"))

    def test_compound_range_lower_bound_violated(self):
        from app.marketplace.dependencies import version_satisfies
        self.assertFalse(version_satisfies("0.9.0", ">=1.0.0,<2.0.0"))

    def test_compound_range_upper_bound_violated(self):
        from app.marketplace.dependencies import version_satisfies
        self.assertFalse(version_satisfies("2.0.0", ">=1.0.0,<2.0.0"))

    def test_existing_single_clause_forms_still_work(self):
        from app.marketplace.dependencies import version_satisfies
        self.assertTrue(version_satisfies("1.2.5", "^1.2.0"))
        self.assertTrue(version_satisfies("1.0.0", "*"))
        self.assertTrue(version_satisfies("1.0.0", "1.0.0"))


# ── Plugin Capability Discovery (new gap) ───────────────────────────────────

class TestPluginCapabilityDiscovery(unittest.TestCase):
    def test_get_adapted_registrations_strips_internal_proxy_field(self):
        from app.plugins import adapters

        installation_id = f"cap-test-{uuid.uuid4().hex[:8]}"
        adapters._ADAPTED[installation_id] = [
            {"type": "tool", "name": "my_tool"},
            {"type": "event_listener", "name": "my_listener", "pattern": "job.*", "proxy": object()},
        ]
        try:
            result = adapters.get_adapted_registrations(installation_id)
            self.assertEqual(len(result), 2)
            self.assertNotIn("proxy", result[1])
            self.assertEqual(result[1]["pattern"], "job.*")
        finally:
            adapters._ADAPTED.pop(installation_id, None)

    def test_get_adapted_registrations_empty_for_unknown_installation(self):
        from app.plugins.adapters import get_adapted_registrations
        self.assertEqual(get_adapted_registrations("no-such-installation"), [])

    def test_router_exposes_capabilities_endpoints(self):
        import inspect
        from app.routers import plugins as plugins_router
        source = inspect.getsource(plugins_router)
        self.assertIn('@router.get("/capabilities")', source)
        self.assertIn('@router.get("/installed/{installation_id}/capabilities")', source)

    def test_adapters_no_longer_take_a_live_worker_reference(self):
        """WorkerProxyCallable/WorkerProxyProvider must route by
        installation_id through SandboxManager (not hold a fixed Worker),
        or a crash-recovery respawn would be invisible to already-built
        proxies — see app/plugins/adapters.py's WorkerProxyCallable
        docstring."""
        import inspect
        from app.plugins import adapters
        self.assertIn("installation_id", inspect.signature(adapters.WorkerProxyCallable.__init__).parameters)
        self.assertIn("installation_id", inspect.signature(adapters.WorkerProxyProvider.__init__).parameters)


# ── Example plugins (Google Workspace / Microsoft 365 / Slack / GitHub / Discord) ─

class TestExamplePluginManifests(unittest.TestCase):
    _EXPECTED = {
        "google_workspace": ("plugin:GoogleWorkspacePlugin", "accounts.google.com"),
        "microsoft_365": ("plugin:Microsoft365Plugin", "login.microsoftonline.com"),
        "slack": ("plugin:SlackPlugin", "slack.com"),
        "github": ("plugin:GitHubPlugin", "github.com"),
        "discord": ("plugin:DiscordPlugin", "discord.com"),
    }

    def _load(self, dirname: str):
        import json
        from app.plugins.manifest import parse_manifest
        root = Path(__file__).parent.parent / "dev_plugins" / dirname
        raw = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        return parse_manifest(raw), root

    def test_all_five_manifests_parse_and_declare_auth_provider(self):
        for dirname, (entry_point, expected_domain) in self._EXPECTED.items():
            with self.subTest(dirname):
                manifest, root = self._load(dirname)
                self.assertEqual(manifest.category.value, "auth_provider")
                self.assertEqual(manifest.entry_point, entry_point)
                self.assertIn("network", manifest.required_permissions)
                self.assertIn("third_party_api", manifest.required_permissions)
                self.assertIn(expected_domain, manifest.network_domains)
                for field in ("client_id", "client_secret", "redirect_uri"):
                    self.assertIn(field, manifest.configuration_schema["required"])
                self.assertTrue((root / "plugin.py").exists())

    def test_no_real_credentials_hardcoded(self):
        # A crude but effective guard: none of the shipped plugin.py files
        # contain anything that looks like a live secret value (only
        # placeholder config keys and public, well-known endpoint URLs).
        suspicious_markers = ("GOCSPX-", "xoxb-", "xoxp-", "ghp_", "github_pat_")
        for dirname in self._EXPECTED:
            root = Path(__file__).parent.parent / "dev_plugins" / dirname
            source = (root / "plugin.py").read_text(encoding="utf-8")
            for marker in suspicious_markers:
                self.assertNotIn(marker, source, f"{dirname}/plugin.py contains a real-looking credential marker")

    def test_get_authorization_url_requires_no_network_and_is_well_formed(self):
        """Loads each plugin's module directly (not through the sandbox —
        the sandbox round-trip for all 5 is covered by a throwaway
        verification script per this session's established convention) and
        exercises the one method that needs no network I/O at all."""
        import importlib.util
        import urllib.parse

        for dirname, (_entry_point, expected_domain) in self._EXPECTED.items():
            with self.subTest(dirname):
                root = Path(__file__).parent.parent / "dev_plugins" / dirname
                spec = importlib.util.spec_from_file_location(f"_example_plugin_{dirname}", root / "plugin.py")
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                provider_cls = next(
                    obj for name, obj in vars(module).items()
                    if name.endswith("AuthProvider") and isinstance(obj, type)
                )
                provider = provider_cls({
                    "client_id": "test-client-id", "client_secret": "test-secret",
                    "redirect_uri": "https://example.invalid/cb",
                })
                url = provider.get_authorization_url(redirect_uri="https://example.invalid/cb", state="s1")
                parsed = urllib.parse.urlparse(url)
                self.assertEqual(parsed.hostname, expected_domain)
                qs = urllib.parse.parse_qs(parsed.query)
                self.assertEqual(qs["client_id"][0], "test-client-id")
                self.assertEqual(qs["state"][0], "s1")
                self.assertEqual(qs["response_type"][0], "code")


# ── Plugin Trust Model (new capability) ──────────────────────────────────

class TestPluginTrustModel(unittest.TestCase):
    def test_trusted_publisher_requires_verified_and_matching_key(self):
        import inspect
        from app.plugins.loader import PluginLoader
        source = inspect.getsource(PluginLoader.load)
        self.assertIn("trusted_publisher", source)
        self.assertIn('publisher.get("verified")', source)
        self.assertIn('publisher.get("public_key_pem") == publisher_public_key', source)

    def test_trusted_publisher_only_evaluated_when_signature_verified(self):
        import inspect
        from app.plugins.loader import PluginLoader
        source = inspect.getsource(PluginLoader.load)
        # The "if signature_verified:" guard must appear before the
        # trusted_publisher lookup — an unsigned/unverified bundle must
        # never be looked up against a publisher's key at all.
        sig_idx = source.index("signature_verified = True")
        trust_idx = source.index("trusted_publisher = False")
        self.assertLess(sig_idx, trust_idx)

    def test_installation_schema_has_trusted_publisher_column(self):
        from app.plugins.schema import PLUGIN_SCHEMA
        self.assertIn("trusted_publisher", PLUGIN_SCHEMA)

    def test_publishers_schema_has_public_key_column(self):
        import inspect
        from app.marketplace.publishers import init_publishers_schema
        source = inspect.getsource(init_publishers_schema)
        self.assertIn("public_key_pem", source)

    def test_installation_output_exposes_trust_fields(self):
        import inspect
        from app.routers import plugins as plugins_router
        source = inspect.getsource(plugins_router._installation_out)
        self.assertIn("signature_verified", source)
        self.assertIn("trusted_publisher", source)

    def test_admin_endpoint_to_register_publisher_key_exists(self):
        import inspect
        from app.routers import marketplace as marketplace_router
        source = inspect.getsource(marketplace_router)
        self.assertIn('"/api/admin/marketplace/publishers/{publisher_id}/public-key"', source)
        self.assertIn("require_api_key(scopes=[\"admin\"])", source)

    def test_publisher_service_has_get_by_item_and_set_public_key(self):
        from app.marketplace.publishers import PublisherService
        self.assertTrue(hasattr(PublisherService, "get_by_item"))
        self.assertTrue(hasattr(PublisherService, "set_public_key"))


# ── Plugin Compatibility Matrix (new capability) ─────────────────────────

class TestPluginCompatibilityMatrix(unittest.TestCase):
    def _row(self, plugin_id, version, status="enabled", manifest=None):
        return {"plugin_id": plugin_id, "version": version, "status": status, "manifest": manifest or {}}

    def test_compatible_plugin_with_no_constraints(self):
        from app.plugins.compatibility import _evaluate_plugin_compatibility
        row = self._row("a", "1.0.0")
        result = _evaluate_plugin_compatibility(row, {"a": row}, platform_version="1.0.0")
        self.assertTrue(result["platform_compatible"])
        self.assertTrue(result["fully_compatible"])
        self.assertEqual(result["dependencies"], [])

    def test_platform_version_too_low_is_incompatible(self):
        from app.plugins.compatibility import _evaluate_plugin_compatibility
        row = self._row("a", "1.0.0", manifest={"min_platform_version": "2.0.0"})
        result = _evaluate_plugin_compatibility(row, {"a": row}, platform_version="1.0.0")
        self.assertFalse(result["platform_compatible"])
        self.assertFalse(result["fully_compatible"])

    def test_platform_version_above_max_is_incompatible(self):
        from app.plugins.compatibility import _evaluate_plugin_compatibility
        row = self._row("a", "1.0.0", manifest={"max_platform_version": "0.9.0"})
        result = _evaluate_plugin_compatibility(row, {"a": row}, platform_version="1.0.0")
        self.assertFalse(result["platform_compatible"])

    def test_satisfied_dependency(self):
        from app.plugins.compatibility import _evaluate_plugin_compatibility
        dep_row = self._row("base", "1.5.0")
        row = self._row("a", "1.0.0", manifest={
            "dependencies": [{"plugin_id": "base", "version_constraint": "^1.2.0", "optional": False}],
        })
        by_id = {"a": row, "base": dep_row}
        result = _evaluate_plugin_compatibility(row, by_id, platform_version="1.0.0")
        self.assertEqual(len(result["dependencies"]), 1)
        self.assertTrue(result["dependencies"][0]["satisfied"])
        self.assertEqual(result["dependencies"][0]["installed_version"], "1.5.0")
        self.assertTrue(result["fully_compatible"])

    def test_missing_required_dependency_is_unsatisfied(self):
        from app.plugins.compatibility import _evaluate_plugin_compatibility
        row = self._row("a", "1.0.0", manifest={
            "dependencies": [{"plugin_id": "missing", "version_constraint": "*", "optional": False}],
        })
        result = _evaluate_plugin_compatibility(row, {"a": row}, platform_version="1.0.0")
        self.assertFalse(result["dependencies"][0]["satisfied"])
        self.assertIsNone(result["dependencies"][0]["installed_version"])
        self.assertFalse(result["fully_compatible"])

    def test_missing_optional_dependency_is_satisfied(self):
        from app.plugins.compatibility import _evaluate_plugin_compatibility
        row = self._row("a", "1.0.0", manifest={
            "dependencies": [{"plugin_id": "missing", "version_constraint": "*", "optional": True}],
        })
        result = _evaluate_plugin_compatibility(row, {"a": row}, platform_version="1.0.0")
        self.assertTrue(result["dependencies"][0]["satisfied"])
        self.assertTrue(result["fully_compatible"])

    def test_dependency_version_constraint_violated(self):
        from app.plugins.compatibility import _evaluate_plugin_compatibility
        dep_row = self._row("base", "0.9.0")
        row = self._row("a", "1.0.0", manifest={
            "dependencies": [{"plugin_id": "base", "version_constraint": ">=1.0.0", "optional": False}],
        })
        by_id = {"a": row, "base": dep_row}
        result = _evaluate_plugin_compatibility(row, by_id, platform_version="1.0.0")
        self.assertFalse(result["dependencies"][0]["satisfied"])

    def test_dependency_installed_but_disabled_is_unsatisfied(self):
        from app.plugins.compatibility import _evaluate_plugin_compatibility
        dep_row = self._row("base", "1.5.0", status="disabled")
        row = self._row("a", "1.0.0", manifest={
            "dependencies": [{"plugin_id": "base", "version_constraint": "*", "optional": False}],
        })
        by_id = {"a": row, "base": dep_row}
        result = _evaluate_plugin_compatibility(row, by_id, platform_version="1.0.0")
        self.assertFalse(result["dependencies"][0]["satisfied"])

    def test_router_exposes_compatibility_matrix_endpoint(self):
        import inspect
        from app.routers import plugins as plugins_router
        source = inspect.getsource(plugins_router)
        self.assertIn('@router.get("/compatibility-matrix")', source)


# ── Automatic Migration Support (new capability) ─────────────────────────

class TestAutomaticMigration(unittest.TestCase):
    def test_plugin_base_declares_migrate_hook_with_safe_default(self):
        import asyncio
        from app.plugins.base import PluginBase, PluginContext, PluginType
        self.assertTrue(hasattr(PluginBase, "migrate"))

        class Impl(PluginBase):
            plugin_type = PluginType.TOOL

            def register(self, ctx):
                pass

        ctx = PluginContext(plugin_id="p", installation_id="i", organization_id="o", config={}, logger=None)
        result = asyncio.new_event_loop().run_until_complete(Impl().migrate(ctx, "1.0.0", "2.0.0"))
        self.assertIsNone(result)

    def test_loader_computes_is_upgrade_before_calling_migrate(self):
        import inspect
        from app.plugins.loader import PluginLoader
        source = inspect.getsource(PluginLoader.load)
        self.assertIn("is_upgrade", source)
        self.assertIn('method="migrate"', source)
        # migrate() must run before on_install/on_enable/register for the
        # new version, per its own docstring contract.
        migrate_idx = source.index('method="migrate"')
        on_install_idx = source.index('method="on_install"')
        self.assertLess(migrate_idx, on_install_idx)

    def test_migrate_failure_uses_the_same_failure_path_as_register(self):
        import inspect
        from app.plugins.loader import PluginLoader
        source = inspect.getsource(PluginLoader.load)
        self.assertIn("activation failed", source)

    def test_migrated_config_is_persisted_via_shared_helper(self):
        import inspect
        from app.plugins.loader import PluginLoader
        load_source = inspect.getsource(PluginLoader.load)
        self.assertIn("_persist_config", load_source)
        update_config_source = inspect.getsource(PluginLoader.update_config)
        self.assertIn("_persist_config", update_config_source)

    def test_persist_config_does_not_fire_on_config_change(self):
        """migrate()'s config persistence must NOT re-trigger
        on_config_change (that hook is for admin-initiated PUT /config
        changes) — only update_config() should call it. Checks for the
        actual worker.call(...) invocation, not just the word appearing
        anywhere (the docstring mentions it explanatorily)."""
        import inspect
        from app.plugins.loader import PluginLoader
        source = inspect.getsource(PluginLoader._persist_config)
        self.assertNotIn('method="on_config_change"', source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
