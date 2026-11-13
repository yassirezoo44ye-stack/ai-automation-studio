"""Server-wide routers are platform-admin only.

The kernel (self-modifying code + hot reload), the command runner
(modify file/env, build/deploy with raw paths) and the background-service,
alert-rule, trace and code-generation diagnostics act on the whole server.
They used to sit behind the generic /api authentication only, which every
self-service account passes.
"""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("SESSION_SECRET", "test-secret-for-unit-tests-do-not-use-in-prod")

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _client(*routers):
    app = FastAPI()
    for r in routers:
        app.include_router(r)
    return TestClient(app, raise_server_exceptions=False)


class TestPlatformAdminGate(unittest.TestCase):
    def setUp(self):
        from app.routers import commands_api, diagnostics_api, kernel_api
        self.c = _client(kernel_api.router, commands_api.router, diagnostics_api.router)

    def _as(self, email, admins):
        return patch("app.core.auth.owner_email", return_value=email), \
            patch("app.core.config.ADMIN_EMAILS", frozenset(admins))

    def test_ordinary_user_is_refused_on_server_wide_routes(self):
        a, b = self._as("user@example.com", {"ops@example.com"})
        with a, b:
            for method, path in [
                ("post", "/api/kernel/execute"),
                ("get", "/api/kernel/status"),
                ("post", "/api/kernel/rollback/0"),
                ("post", "/api/commands/execute"),
                ("post", "/api/diagnostics/services/security_monitor/stop"),
                ("get", "/api/diagnostics/alerts/rules"),
                ("get", "/api/diagnostics/traces"),
                ("post", "/api/diagnostics/codegen/x/approve"),
            ]:
                res = getattr(self.c, method)(path, json={"input": "status"})
                self.assertEqual(res.status_code, 403, f"{method} {path}")

    def test_admin_list_empty_fails_closed(self):
        a, b = self._as("anyone@example.com", set())
        with a, b:
            self.assertEqual(self.c.get("/api/kernel/status").status_code, 403)

    def test_platform_admin_is_allowed(self):
        a, b = self._as("Ops@Example.com", {"ops@example.com"})
        with a, b:
            res = self.c.get("/api/kernel/status")
        self.assertNotIn(res.status_code, (401, 403))

    def test_health_and_metrics_stay_available_to_signed_in_users(self):
        a, b = self._as("user@example.com", {"ops@example.com"})
        with a, b:
            for path in ("/api/diagnostics/health", "/api/diagnostics/metrics"):
                self.assertNotIn(self.c.get(path).status_code, (401, 403), path)


if __name__ == "__main__":
    unittest.main()
