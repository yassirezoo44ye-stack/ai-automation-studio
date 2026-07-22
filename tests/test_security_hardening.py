"""
v1.0 Security Hardening phase — tests for each fix landed this phase.
One test class per fix, named after the finding it closes, so a failing
test names exactly which security property regressed.
"""
from __future__ import annotations

import unittest


# ═══════════════════════════════════════════════════════════════════════════════
# SSRF guard (app/core/ssrf_guard.py) — used by the alert-rule webhook
# ═══════════════════════════════════════════════════════════════════════════════

class TestSsrfGuard(unittest.TestCase):
    def test_public_https_url_allowed(self):
        from app.core.ssrf_guard import assert_public_url
        assert_public_url("https://example.com/webhook")  # must not raise

    def test_public_http_url_allowed(self):
        from app.core.ssrf_guard import assert_public_url
        assert_public_url("http://example.com/webhook")  # must not raise

    def test_loopback_literal_ip_blocked(self):
        from app.core.ssrf_guard import UnsafeUrlError, assert_public_url
        with self.assertRaises(UnsafeUrlError):
            assert_public_url("http://127.0.0.1/steal")

    def test_localhost_hostname_blocked(self):
        from app.core.ssrf_guard import UnsafeUrlError, assert_public_url
        with self.assertRaises(UnsafeUrlError):
            assert_public_url("http://localhost/steal")

    def test_cloud_metadata_endpoint_blocked(self):
        from app.core.ssrf_guard import UnsafeUrlError, assert_public_url
        with self.assertRaises(UnsafeUrlError):
            assert_public_url("http://169.254.169.254/latest/meta-data/")

    def test_private_rfc1918_ranges_blocked(self):
        from app.core.ssrf_guard import UnsafeUrlError, assert_public_url
        for host in ("10.0.0.5", "172.16.0.1", "192.168.1.1"):
            with self.subTest(host=host):
                with self.assertRaises(UnsafeUrlError):
                    assert_public_url(f"http://{host}/x")

    def test_non_http_scheme_blocked(self):
        from app.core.ssrf_guard import UnsafeUrlError, assert_public_url
        for url in ("file:///etc/passwd", "gopher://127.0.0.1:6379/_INFO", "ftp://example.com/x"):
            with self.subTest(url=url):
                with self.assertRaises(UnsafeUrlError):
                    assert_public_url(url)

    def test_url_with_no_hostname_blocked(self):
        from app.core.ssrf_guard import UnsafeUrlError, assert_public_url
        with self.assertRaises(UnsafeUrlError):
            assert_public_url("http:///no-host")


class TestAlertRuleWebhookSsrfRejection(unittest.TestCase):
    """The router-level validator on AlertRuleCreate — this is the actual
    fail-fast enforcement point a client hits (app/routers/diagnostics_api.py)."""

    def test_internal_webhook_url_rejected_at_creation(self):
        from pydantic import ValidationError
        from app.routers.diagnostics_api import AlertRuleCreate
        with self.assertRaises(ValidationError):
            AlertRuleCreate(
                name="evil", rule_type="gauge_above", target="x", threshold=1.0,
                notify_webhook_url="http://169.254.169.254/latest/meta-data/iam/security-credentials/",
            )

    def test_public_webhook_url_accepted_at_creation(self):
        # example.com is IANA's reserved, always-resolvable test domain —
        # a made-up subdomain would fail DNS resolution in this test
        # environment and produce a false failure, not a real one.
        from app.routers.diagnostics_api import AlertRuleCreate
        rule = AlertRuleCreate(
            name="ok", rule_type="gauge_above", target="x", threshold=1.0,
            notify_webhook_url="https://example.com/incoming",
        )
        self.assertEqual(rule.notify_webhook_url, "https://example.com/incoming")

    def test_no_webhook_url_is_fine(self):
        from app.routers.diagnostics_api import AlertRuleCreate
        rule = AlertRuleCreate(name="ok", rule_type="gauge_above", target="x", threshold=1.0)
        self.assertIsNone(rule.notify_webhook_url)


if __name__ == "__main__":
    unittest.main()
