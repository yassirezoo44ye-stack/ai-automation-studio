"""
Regression tests for startup configuration enforcement (C-02).

Verifies that the application refuses to start when SESSION_SECRET is absent
and starts correctly when all required env vars are present.
"""
from __future__ import annotations

import importlib
import os
import sys
from unittest.mock import patch


def _reload_config(env: dict):
    """Import app.core.config in a subprocess-like isolation using patched env."""
    # Remove cached module so it re-evaluates os.getenv at import time
    for mod in list(sys.modules):
        if "app.core.config" in mod:
            del sys.modules[mod]

    with patch.dict(os.environ, env, clear=True):
        import importlib
        try:
            import app.core.config as cfg
            importlib.reload(cfg)
            return cfg
        except SystemExit as e:
            raise


class TestSessionSecretRequired:
    def test_missing_session_secret_exits(self, capsys):
        """app.core.config must call sys.exit(1) when SESSION_SECRET is missing."""
        env = {
            "DATABASE_URL": "postgresql://u:p@localhost/db",
            # SESSION_SECRET deliberately absent
        }
        for mod in list(sys.modules):
            if "app.core.config" in mod or "stripe" in mod:
                del sys.modules[mod]

        with patch.dict(os.environ, env, clear=True), \
             patch("stripe.api_key", "", create=True):
            with patch("sys.exit") as mock_exit:
                try:
                    import app.core.config  # noqa
                    importlib.reload(app.core.config)
                except Exception:
                    pass
                # sys.exit(1) must have been called
                calls = [str(c) for c in mock_exit.call_args_list]
                assert any("1" in c for c in calls), (
                    f"sys.exit(1) not called — calls were: {calls}"
                )

    def test_present_session_secret_does_not_exit(self):
        """When SESSION_SECRET is set, config loads without calling sys.exit."""
        env = {
            "DATABASE_URL": "postgresql://u:p@localhost/db",
            "SESSION_SECRET": "a" * 64,
        }
        for mod in list(sys.modules):
            if "app.core.config" in mod:
                del sys.modules[mod]

        with patch.dict(os.environ, env, clear=True), \
             patch("sys.exit") as mock_exit, \
             patch("stripe.api_key", "", create=True):
            try:
                import app.core.config
                importlib.reload(app.core.config)
            except Exception:
                pass

            # exit must not have been called with 1
            calls = [str(c) for c in mock_exit.call_args_list]
            fatal_exits = [c for c in calls if "1" in c]
            assert len(fatal_exits) == 0, f"sys.exit(1) called unexpectedly: {fatal_exits}"

    def test_session_secret_not_fallback_random(self):
        """SESSION_SECRET must be the env var value, not a random fallback."""
        import os
        os.environ.setdefault("DATABASE_URL", "postgresql://u:p@localhost/db")
        os.environ.setdefault("SESSION_SECRET", "known-stable-secret-value")

        for mod in list(sys.modules):
            if "app.core.config" in mod:
                del sys.modules[mod]

        with patch.dict(os.environ, {
            "DATABASE_URL": "postgresql://u:p@localhost/db",
            "SESSION_SECRET": "known-stable-secret-value",
        }, clear=True), patch("stripe.api_key", "", create=True):
            import app.core.config
            importlib.reload(app.core.config)
            assert app.core.config.SESSION_SECRET == "known-stable-secret-value"
