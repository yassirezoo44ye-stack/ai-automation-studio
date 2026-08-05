"""
HotReloader rollback — regression tests for the "Plugin Isolation" fix.

Before this fix, app/kernel/reloader.py's reload_plugin() unregistered a
plugin's commands *before* attempting to re-import/re-register it, with no
try/except around exec_module()/register_fn(). A broken second version of a
plugin file would raise, but the commands were already gone from the
registry with no rollback and self._ownership left stale. reload_builtin()
had the same gap around import_module()/register_fn(), leaving a
half-imported module sitting in sys.modules on failure.

Real temp .py files are used for reload_plugin (matching
tests/test_plugins.py's TestPluginLoaderIsolation convention) because the
bug is specifically about exec_module()/spec.loader failure modes that a
mock can't faithfully reproduce. They're created under the project root
(not the OS temp dir) because _module_name() requires the path to be
relative to _PROJECT_ROOT.
"""
from __future__ import annotations

import sys
import tempfile
import types
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.commands.registry import CommandRegistry
from app.kernel.reloader import HotReloader, ReloadError, _PROJECT_ROOT, _module_name


async def _noop_handler(ctx):
    return None


VALID_PLUGIN = '''
def register(registry):
    async def handler(ctx):
        return "ok"
    registry.register("reloader_test_cmd", handler, description="v1", group="test")
'''

BROKEN_AT_IMPORT = '''
raise RuntimeError("boom at import time")

def register(registry):
    pass
'''

BROKEN_AT_REGISTER = '''
def register(registry):
    raise RuntimeError("boom in register")
'''

MISSING_REGISTER = '''
x = 1
'''


class TestReloadPluginRollback(unittest.TestCase):
    def setUp(self):
        # Nested under the project root (not the OS temp dir) so
        # _module_name()'s path.relative_to(_PROJECT_ROOT) succeeds.
        self._tmpdir = tempfile.TemporaryDirectory(dir=str(_PROJECT_ROOT))
        self.addCleanup(self._tmpdir.cleanup)
        self.plugin_path = Path(self._tmpdir.name) / "reloader_test_plugin.py"
        self.registry = CommandRegistry()
        self.state = unittest.mock.MagicMock()
        self.reloader = HotReloader(self.registry, self.state)

    def _write(self, content: str) -> None:
        self.plugin_path.write_text(content, encoding="utf-8")

    def _load_valid_first(self) -> str:
        self._write(VALID_PLUGIN)
        result = self.reloader.reload_plugin(str(self.plugin_path))
        self.assertEqual(result["status"], "reloaded")
        self.assertIn("reloader_test_cmd", self.registry.names())
        module_name = _module_name(self.plugin_path)
        self.assertEqual(self.reloader._ownership[module_name], ["reloader_test_cmd"])
        return module_name

    def test_broken_exec_module_rolls_back(self):
        module_name = self._load_valid_first()

        self._write(BROKEN_AT_IMPORT)
        with self.assertRaises(ReloadError):
            self.reloader.reload_plugin(str(self.plugin_path))

        # The regression: command must still be registered, not vanished.
        self.assertIn("reloader_test_cmd", self.registry.names())
        self.assertEqual(self.reloader._ownership[module_name], ["reloader_test_cmd"])

    def test_broken_register_fn_rolls_back(self):
        module_name = self._load_valid_first()

        self._write(BROKEN_AT_REGISTER)
        with self.assertRaises(ReloadError):
            self.reloader.reload_plugin(str(self.plugin_path))

        self.assertIn("reloader_test_cmd", self.registry.names())
        self.assertEqual(self.reloader._ownership[module_name], ["reloader_test_cmd"])

    def test_missing_register_function_rolls_back(self):
        module_name = self._load_valid_first()

        self._write(MISSING_REGISTER)
        with self.assertRaises(ReloadError):
            self.reloader.reload_plugin(str(self.plugin_path))

        self.assertIn("reloader_test_cmd", self.registry.names())
        self.assertEqual(self.reloader._ownership[module_name], ["reloader_test_cmd"])

    def test_successful_reload_still_replaces_commands(self):
        """Control test: the happy path must still work after the fix —
        a *good* second version genuinely replaces the first (same command
        name, changed behavior — the realistic "edited a plugin file"
        case; renaming the registered command across a reload exercises a
        separate, pre-existing quirk in the added/removed bookkeeping
        that's out of scope for this rollback fix)."""
        module_name = self._load_valid_first()

        second_version = '''
def register(registry):
    async def handler(ctx):
        return "v2"
    registry.register("reloader_test_cmd", handler, description="v2", group="test")
'''
        self._write(second_version)
        result = self.reloader.reload_plugin(str(self.plugin_path))
        self.assertEqual(result["status"], "reloaded")
        self.assertIn("reloader_test_cmd", self.registry.names())
        self.assertEqual(self.reloader._ownership[module_name], ["reloader_test_cmd"])

    def test_first_load_failure_raises_without_rollback_crash(self):
        """A plugin that's broken on its very first load (nothing owned
        yet) must still raise ReloadError cleanly, not crash the rollback
        path itself (empty snapshot)."""
        self._write(BROKEN_AT_IMPORT)
        with self.assertRaises(ReloadError):
            self.reloader.reload_plugin(str(self.plugin_path))
        self.assertEqual(self.registry.names(), [])


class TestReloadBuiltinTryExcept(unittest.TestCase):
    def setUp(self):
        self.registry = CommandRegistry()
        self.state = unittest.mock.MagicMock()
        self.reloader = HotReloader(self.registry, self.state)

    def test_import_error_raises_reloaderror(self):
        with unittest.mock.patch(
            "app.kernel.reloader.importlib.import_module",
            side_effect=ImportError("boom"),
        ):
            with self.assertRaises(ReloadError):
                self.reloader.reload_builtin("fake.builtin.does_not_exist")
        self.assertNotIn("fake.builtin.does_not_exist", sys.modules)

    def test_register_failure_does_not_leave_half_broken_module(self):
        """The actual regression: a real import (which puts the module in
        sys.modules as a side effect) followed by a register() failure
        must not leave that half-registered module sitting in
        sys.modules for a later caller to accidentally reuse."""
        module_path = "fake.builtin.reloader_regression_test"

        def bad_register(registry):
            raise RuntimeError("boom in register")

        def fake_import(name):
            mod = types.ModuleType(name)
            mod.register = bad_register
            sys.modules[name] = mod   # mirrors real importlib's side effect
            return mod

        with unittest.mock.patch(
            "app.kernel.reloader.importlib.import_module", side_effect=fake_import,
        ):
            with self.assertRaises(ReloadError):
                self.reloader.reload_builtin(module_path)

        self.assertNotIn(module_path, sys.modules)

    def test_missing_register_function_raises_and_cleans_up(self):
        module_path = "fake.builtin.reloader_missing_register"

        def fake_import(name):
            mod = types.ModuleType(name)  # no .register attribute
            sys.modules[name] = mod
            return mod

        with unittest.mock.patch(
            "app.kernel.reloader.importlib.import_module", side_effect=fake_import,
        ):
            with self.assertRaises(ReloadError):
                self.reloader.reload_builtin(module_path)

        self.assertNotIn(module_path, sys.modules)

    def test_successful_reload_builtin_still_works(self):
        module_path = "fake.builtin.reloader_success"

        def good_register(registry):
            registry.register("reloader_builtin_ok", _noop_handler, group="test")

        def fake_import(name):
            mod = types.ModuleType(name)
            mod.register = good_register
            sys.modules[name] = mod
            return mod

        with unittest.mock.patch(
            "app.kernel.reloader.importlib.import_module", side_effect=fake_import,
        ):
            result = self.reloader.reload_builtin(module_path)

        self.assertEqual(result["status"], "reloaded")
        self.assertIn("reloader_builtin_ok", self.registry.names())
        self.assertIn(module_path, sys.modules)


if __name__ == "__main__":
    unittest.main()
