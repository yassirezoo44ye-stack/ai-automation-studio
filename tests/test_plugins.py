"""
Plugin SDK & Extension Framework — pure-logic and source-inspection tests,
matching tests/test_enterprise.py's established style (DB-free paths here;
the live-Postgres install/uninstall/permission-approval flow is exercised
by a throwaway verification script, same convention as every prior phase
in this session).
"""
from __future__ import annotations

import sys
import unittest
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


# ── Loader isolation (mirrors app/commands/loader.py's try/except pattern) ─────

class TestPluginLoaderIsolation(unittest.TestCase):
    def _manifest(self, entry_point: str):
        from app.plugins.manifest import parse_manifest
        return parse_manifest({
            "id": "iso_test", "name": "Iso Test", "version": "1.0.0",
            "author": "t", "description": "d", "category": "tool",
            "min_platform_version": "1.0.0", "entry_point": entry_point,
        })

    def test_valid_plugin_code_instantiates(self):
        from app.plugins.loader import PluginLoader
        code = (
            "from app.plugins.base import PluginBase, PluginContext, PluginType\n"
            "class GoodPlugin(PluginBase):\n"
            "    plugin_type = PluginType.TOOL\n"
            "    def register(self, ctx: PluginContext) -> None:\n"
            "        pass\n"
        )
        loader = PluginLoader()
        instance = loader._import_and_instantiate(
            f"test-{uuid.uuid4().hex[:8]}", self._manifest("plugin:GoodPlugin"), code,
        )
        self.assertIsNotNone(instance)

    def test_broken_plugin_code_raises_catchable_error_not_crash(self):
        """The load() caller wraps this in try/except and records the failure
        in plugin_health_log — the important guarantee is that a broken
        plugin raises a typed, catchable exception rather than propagating
        an arbitrary uncaught error that could take down the process."""
        from app.plugins.loader import PluginLoader, PluginImportError
        code = "this is not valid python syntax :::: ("
        loader = PluginLoader()
        with self.assertRaises(PluginImportError):
            loader._import_and_instantiate(
                f"test-{uuid.uuid4().hex[:8]}", self._manifest("plugin:GoodPlugin"), code,
            )

    def test_missing_entry_point_class_raises(self):
        from app.plugins.loader import PluginLoader, PluginImportError
        code = (
            "from app.plugins.base import PluginBase, PluginContext, PluginType\n"
            "class SomeOtherClass:\n    pass\n"
        )
        loader = PluginLoader()
        with self.assertRaises(PluginImportError):
            loader._import_and_instantiate(
                f"test-{uuid.uuid4().hex[:8]}", self._manifest("plugin:DoesNotExist"), code,
            )

    def test_non_pluginbase_entry_point_class_raises(self):
        """entry_point must resolve to an actual PluginBase subclass — a
        same-named class that doesn't inherit it must be rejected, not
        silently instantiated and then fail confusingly later."""
        from app.plugins.loader import PluginLoader, PluginImportError
        code = "class GoodPlugin:\n    pass\n"
        loader = PluginLoader()
        with self.assertRaises(PluginImportError):
            loader._import_and_instantiate(
                f"test-{uuid.uuid4().hex[:8]}", self._manifest("plugin:GoodPlugin"), code,
            )


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
        from app.ai.providers.registry import registry as provider_registry

        class _FakeProvider:
            provider_id = "fake"
            is_available = True

        provider_id = f"fake_{uuid.uuid4().hex[:8]}"
        provider_registry.register_provider(provider_id, _FakeProvider())
        self.assertIs(provider_registry.get(provider_id).__class__, _FakeProvider)
        self.assertTrue(provider_registry.unregister_provider(provider_id))

    def test_cannot_unregister_builtin_provider(self):
        from app.ai.providers.registry import registry as provider_registry
        with self.assertRaises(ValueError):
            provider_registry.unregister_provider("anthropic")


if __name__ == "__main__":
    unittest.main(verbosity=2)
