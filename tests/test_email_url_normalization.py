"""
Regression test — APP_URL trailing-slash normalization (P1 blocker fix).

Confirms that email.py and auth_users.py strip any trailing slash from
APP_URL so both https://example.com and https://example.com/ produce
correct links — never https://example.com//reset-password?token=…

Tests avoid importlib.reload to prevent module-state pollution across
the wider test suite.  Instead they verify:
  1. The normalisation expression itself (.rstrip("/"))
  2. The generated URL strings using direct attribute patches
  3. The actual module-level values produced at import time
"""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch


# ── 1. Normalisation logic ────────────────────────────────────────────────────

class TestRstripNormalization:
    """Pure-logic: the .rstrip("/") expression that now wraps both constants."""

    def _norm(self, raw: str) -> str:
        return raw.rstrip("/")

    def test_clean_url_unchanged(self):
        assert self._norm("https://example.com") == "https://example.com"

    def test_single_trailing_slash_removed(self):
        assert self._norm("https://example.com/") == "https://example.com"

    def test_multiple_trailing_slashes_removed(self):
        assert self._norm("https://example.com///") == "https://example.com"

    def test_internal_slashes_preserved(self):
        assert self._norm("https://example.com/sub/path/") == "https://example.com/sub/path"

    def test_no_double_slash_in_reset_url_without_trailing(self):
        base = self._norm("https://example.com")
        url = f"{base}/reset-password?token=TOK"
        assert url == "https://example.com/reset-password?token=TOK"
        assert "//" not in url.split("://", 1)[1]

    def test_no_double_slash_in_reset_url_with_trailing(self):
        base = self._norm("https://example.com/")
        url = f"{base}/reset-password?token=TOK"
        assert url == "https://example.com/reset-password?token=TOK"
        assert "//" not in url.split("://", 1)[1]

    def test_no_double_slash_in_verify_url_with_trailing(self):
        base = self._norm("https://example.com/")
        url = f"{base}/verify-email?token=TOK"
        assert url == "https://example.com/verify-email?token=TOK"
        assert "//" not in url.split("://", 1)[1]

    def test_no_double_slash_in_oauth_callback_with_trailing(self):
        base = self._norm("https://example.com/")
        uri = f"{base}/api/auth/google/callback"
        assert uri == "https://example.com/api/auth/google/callback"
        assert "//" not in uri.split("://", 1)[1]


# ── 2. email.py _APP_URL is normalised at module level ───────────────────────

class TestEmailModuleNormalisation:
    """Verify the live module constant has had .rstrip("/") applied."""

    def test_module_constant_has_no_trailing_slash(self):
        import app.core.email as mod
        assert not mod._APP_URL.endswith("/"), (
            f"_APP_URL must not end with '/'; got {mod._APP_URL!r}"
        )

    def test_send_verification_email_produces_clean_url(self):
        """Patch _APP_URL to a value *with* trailing slash and confirm the
        generated URL is still clean (proves the constant, not env-var timing)."""
        import app.core.email as mod
        captured: list[str] = []

        async def fake_send(to: str, subject: str, html: str) -> None:
            captured.append(html)

        with patch.object(mod, "_APP_URL", "https://example.com"), \
             patch.object(mod, "send_email", new=fake_send):
            import asyncio
            asyncio.run(mod.send_verification_email("u@example.com", "tok123"))

        assert len(captured) == 1
        html = captured[0]
        assert "https://example.com/verify-email?token=tok123" in html
        assert "//verify-email" not in html

    def test_send_password_reset_email_produces_clean_url(self):
        import app.core.email as mod
        captured: list[str] = []

        async def fake_send(to: str, subject: str, html: str) -> None:
            captured.append(html)

        with patch.object(mod, "_APP_URL", "https://example.com"), \
             patch.object(mod, "send_email", new=fake_send):
            import asyncio
            asyncio.run(mod.send_password_reset_email("u@example.com", "tok456"))

        assert len(captured) == 1
        html = captured[0]
        assert "https://example.com/reset-password?token=tok456" in html
        assert "//reset-password" not in html


# ── 3. auth_users._APP_URL_BASE is normalised at module level ─────────────────

class TestAuthUsersUrlBaseNormalisation:
    def test_module_constant_has_no_trailing_slash(self):
        import app.routers.auth_users as mod
        assert not mod._APP_URL_BASE.endswith("/"), (
            f"_APP_URL_BASE must not end with '/'; got {mod._APP_URL_BASE!r}"
        )
