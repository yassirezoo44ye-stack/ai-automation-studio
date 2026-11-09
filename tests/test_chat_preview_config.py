import copy
import unittest

from scripts.prepare_chat_preview import make_preview_config


class ChatPreviewConfigTests(unittest.TestCase):
    def setUp(self):
        self.source = {
            "buildCommand": "npm run build",
            "rewrites": [
                {"source": "/api/:path*", "destination": "https://production.onrender.com/api/:path*"},
                {"source": "/(.*)", "destination": "/index.html"},
            ],
            "headers": [{"source": "/(.*)", "headers": [
                {"key": "Content-Security-Policy", "value": "default-src 'self'; connect-src 'self' https://production.onrender.com wss://production.onrender.com https://api.stripe.com;"},
                {"key": "X-Frame-Options", "value": "DENY"},
            ]}],
        }
        self.backend = "https://flow-chat-review-api-abc.onrender.com"

    def test_updates_api_and_connect_policy_without_mutating_production(self):
        before = copy.deepcopy(self.source)
        result = make_preview_config(self.source, self.backend)
        self.assertEqual(self.source, before)
        self.assertEqual(result["rewrites"][0]["destination"], self.backend + "/api/:path*")
        csp = result["headers"][0]["headers"][0]["value"]
        self.assertIn(self.backend, csp)
        self.assertIn("wss://flow-chat-review-api-abc.onrender.com", csp)
        self.assertNotIn("production.onrender.com", csp)
        self.assertIn("https://api.stripe.com", csp)

    def test_preserves_spa_and_security_headers(self):
        result = make_preview_config(self.source, self.backend)
        self.assertEqual(result["rewrites"][1], self.source["rewrites"][1])
        self.assertEqual(result["headers"][0]["headers"][1], {"key": "X-Frame-Options", "value": "DENY"})
        self.assertIn("default-src 'self'", result["headers"][0]["headers"][0]["value"])

    def test_rejects_production_other_apps_and_lookalike_hosts(self):
        for value in [
            "https://ai-automation-studio-viio.onrender.com",
            "https://flow-api-pp9r.onrender.com",
            "https://flow-chat-review-api.onrender.com.evil.example",
            "https://unrelated.onrender.com",
        ]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                make_preview_config(self.source, value)

    def test_rejects_credentials_paths_query_and_insecure_scheme(self):
        for value in [
            "http://flow-chat-review-api.onrender.com",
            "https://user:password@flow-chat-review-api.onrender.com",
            self.backend + "/api", self.backend + "?token=x", self.backend + "#fragment",
        ]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                make_preview_config(self.source, value)

    def test_requires_unambiguous_api_rewrite(self):
        self.source["rewrites"].append(copy.deepcopy(self.source["rewrites"][0]))
        with self.assertRaisesRegex(ValueError, "exactly one"):
            make_preview_config(self.source, self.backend)

    def test_requires_connect_policy_instead_of_weakening_csp(self):
        self.source["headers"][0]["headers"][0]["value"] = "default-src 'self';"
        with self.assertRaisesRegex(ValueError, "connect-src"):
            make_preview_config(self.source, self.backend)

    def test_canonicalizes_root_url_and_is_repeatable(self):
        a = make_preview_config(self.source, self.backend + "/")
        self.assertEqual(a, make_preview_config(a, self.backend))


if __name__ == "__main__":
    unittest.main()
