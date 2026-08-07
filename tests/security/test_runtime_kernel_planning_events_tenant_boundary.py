"""
Security Regression Suite — Runtime/Kernel/Planning/Events tenant boundary.

P0.5 audit (docs/security-tenant-boundary-audit.md): app/routers/runtime_api.py,
planning_api.py and events_api.py had zero server-side ownership check on
any id-based lookup — any authenticated user of ANY org could read/cancel
another org's execution report and artifacts, read another org's cached
plan, or read another org's billing/organization/integration event-bus
history, purely by supplying that org's resource id. app/routers/kernel_api.py
had zero authorization at all beyond "some valid session exists" for a
capability that can rewrite the running application's own source files
(app/kernel/self_modify.py).

Fix, in each case, reuses the project's existing tenant-isolation primitive
(app.tenancy.context.org_context / OrgContext) or its existing cross-org
admin mechanism (app.core.api_keys.require_api_key), never a client-supplied
org id — matching app/routers/jobs_api.py's already-established convention
(404, not 403, on cross-org lookup, so a non-member can't distinguish
"wrong org" from "doesn't exist").

Positive: organization A can reach its own resources.
Negative: organization A gets 404 when supplying organization B's id.
"""
from __future__ import annotations

import asyncio
import inspect
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.tenancy.context import OrgContext


def run(coro):
    return asyncio.run(coro)


ORG_A = OrgContext(org_id="org-A", user_id="user-A", user_email="a@example.com", role="developer")
ORG_B = OrgContext(org_id="org-B", user_id="user-B", user_email="b@example.com", role="developer")


# ═══════════════════════════════════════════════════════════════════════════════
# Runtime API — execution status/report/artifacts/cancel
# ═══════════════════════════════════════════════════════════════════════════════

class TestRuntimeApiTenantBoundary(unittest.TestCase):
    def setUp(self):
        from app.routers import runtime_api
        self.mod = runtime_api
        self.mod._executions.clear()
        self.mod._executions["exec-A"] = {
            "status": "done", "report": {"secret": "org-A-report"}, "org_id": "org-A",
        }
        self.mod._executions["exec-B"] = {
            "status": "done", "report": {"secret": "org-B-report"}, "org_id": "org-B",
        }

    def tearDown(self):
        self.mod._executions.clear()

    # ── Positive: an org can reach its own execution ────────────────────────

    def test_status_positive_own_org(self):
        result = run(self.mod.get_status("exec-A", ctx=ORG_A))
        self.assertEqual(result["status"], "done")

    def test_report_positive_own_org(self):
        result = run(self.mod.get_report("exec-A", ctx=ORG_A))
        self.assertEqual(result, {"secret": "org-A-report"})

    def test_cancel_positive_own_org(self):
        # cancel_execution's own best-effort `except Exception: pass` around
        # the process_mgr kill call means this needs no mock either way —
        # exercising exactly what a real request would hit.
        result = run(self.mod.cancel_execution("exec-A", ctx=ORG_A))
        self.assertEqual(result, {"cancelled": "exec-A"})
        self.assertNotIn("exec-A", self.mod._executions)

    # ── Negative: org A must not reach org B's execution ────────────────────

    def test_status_negative_cross_org_is_404(self):
        with self.assertRaises(HTTPException) as ctx:
            run(self.mod.get_status("exec-B", ctx=ORG_A))
        self.assertEqual(ctx.exception.status_code, 404)

    def test_report_negative_cross_org_is_404_not_leaked(self):
        """The core regression: org A must never see org B's report body."""
        with self.assertRaises(HTTPException) as ctx:
            run(self.mod.get_report("exec-B", ctx=ORG_A))
        self.assertEqual(ctx.exception.status_code, 404)

    def test_cancel_negative_cross_org_is_404_and_does_not_delete(self):
        """Regression-critical: org A must not be able to destroy org B's
        execution record via DELETE, even though the id is guessable/known."""
        with self.assertRaises(HTTPException) as ctx:
            run(self.mod.cancel_execution("exec-B", ctx=ORG_A))
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertIn("exec-B", self.mod._executions, "org A's failed attempt must not cancel org B's execution")

    def test_list_artifacts_negative_cross_org_is_404_before_touching_disk(self):
        with patch.object(self.mod, "ArtifactSystem") as fake_artifacts:
            with self.assertRaises(HTTPException) as ctx:
                run(self.mod.list_artifacts("exec-B", ctx=ORG_A))
            self.assertEqual(ctx.exception.status_code, 404)
            fake_artifacts.load.assert_not_called()

    def test_list_artifacts_positive_own_org_reaches_artifact_system(self):
        with patch.object(self.mod, "ArtifactSystem") as fake_artifacts:
            fake_artifacts.load.return_value.all.return_value = []
            result = run(self.mod.list_artifacts("exec-A", ctx=ORG_A))
        self.assertEqual(result, {"artifacts": []})
        fake_artifacts.load.assert_called_once_with("exec-A")

    def test_download_artifact_negative_cross_org_is_404_before_touching_disk(self):
        with patch.object(self.mod, "ArtifactSystem") as fake_artifacts:
            with self.assertRaises(HTTPException) as ctx:
                run(self.mod.download_artifact("exec-B", "art-1", ctx=ORG_A))
            self.assertEqual(ctx.exception.status_code, 404)
            fake_artifacts.load.assert_not_called()

    def test_execution_not_found_at_all_is_also_404(self):
        """Unknown id must behave identically to a cross-org id (no oracle)."""
        with self.assertRaises(HTTPException) as ctx:
            run(self.mod.get_status("no-such-execution", ctx=ORG_A))
        self.assertEqual(ctx.exception.status_code, 404)

    # ── Every id-based route requires org_context ───────────────────────────

    def test_id_based_routes_all_require_org_context(self):
        from app.tenancy.context import org_context
        for name in ("get_status", "get_report", "list_artifacts",
                     "download_artifact", "cancel_execution", "execute"):
            fn = getattr(self.mod, name)
            sig = inspect.signature(fn)
            deps = [p.default.dependency for p in sig.parameters.values()
                    if hasattr(p.default, "dependency")]
            self.assertIn(org_context, deps, f"{name} must depend on org_context")


# ═══════════════════════════════════════════════════════════════════════════════
# Kernel API — self-modification surface now requires an admin API key
# ═══════════════════════════════════════════════════════════════════════════════

class TestKernelApiAuthorization(unittest.TestCase):
    def test_every_route_requires_admin_api_key(self):
        from app.routers import kernel_api
        from app.core.api_keys import require_api_key
        target_qualname = require_api_key(scopes=["admin"]).__qualname__
        for name in ("kernel_execute", "kernel_status", "kernel_state",
                     "kernel_modifications", "kernel_rollback", "kernel_agents"):
            fn = getattr(kernel_api, name)
            sig = inspect.signature(fn)
            gated = any(
                hasattr(p.default, "dependency")
                and getattr(p.default.dependency, "__qualname__", "") == target_qualname
                for p in sig.parameters.values()
            )
            self.assertTrue(gated, f"{name} must require require_api_key(scopes=['admin'])")

    def test_kernel_execute_rejects_request_with_no_api_key(self):
        from fastapi import FastAPI
        from app.routers.kernel_api import router
        app = FastAPI()
        app.include_router(router)
        with TestClient(app, raise_server_exceptions=False) as c:
            res = c.post("/api/kernel/execute", json={"input": "status"})
        self.assertEqual(res.status_code, 401)

    def test_kernel_execute_rejects_non_admin_scoped_key(self):
        from fastapi import FastAPI
        from app.routers.kernel_api import router
        from app.core.api_keys import ApiKeyRecord
        app = FastAPI()
        app.include_router(router)

        read_only_key = ApiKeyRecord(
            key_id="k1", key_hash="h1", name="readonly", scopes=["read"],
        )
        with patch("app.core.api_keys.lookup_key", AsyncMock(return_value=read_only_key)):
            with TestClient(app, raise_server_exceptions=False) as c:
                res = c.post(
                    "/api/kernel/execute",
                    json={"input": "status"},
                    headers={"Authorization": "ApiKey axon_faketoken"},
                )
        self.assertEqual(res.status_code, 403)

    def test_kernel_execute_accepts_admin_scoped_key(self):
        from fastapi import FastAPI
        from app.routers.kernel_api import router
        from app.core.api_keys import ApiKeyRecord
        app = FastAPI()
        app.include_router(router)

        admin_key = ApiKeyRecord(
            key_id="k2", key_hash="h2", name="admin", scopes=["admin"],
        )
        fake_result = MagicMock()
        fake_result.to_dict.return_value = {"ok": True}
        fake_kernel = MagicMock()
        fake_kernel.execute = AsyncMock(return_value=fake_result)

        with patch("app.core.api_keys.lookup_key", AsyncMock(return_value=admin_key)), \
             patch("app.kernel.get_kernel", return_value=fake_kernel):
            with TestClient(app, raise_server_exceptions=False) as c:
                res = c.post(
                    "/api/kernel/execute",
                    json={"input": "status"},
                    headers={"Authorization": "ApiKey axon_faketoken"},
                )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"ok": True})


# ═══════════════════════════════════════════════════════════════════════════════
# Planning API — cached plan lookup
# ═══════════════════════════════════════════════════════════════════════════════

class TestPlanningApiTenantBoundary(unittest.TestCase):
    def setUp(self):
        from app.routers import planning_api
        self.mod = planning_api
        self.mod._plan_cache.clear()
        self.mod._plan_cache["plan-A"] = {"org_id": "org-A", "plan": {"goal": "org A's plan"}}
        self.mod._plan_cache["plan-B"] = {"org_id": "org-B", "plan": {"goal": "org B's plan"}}

    def tearDown(self):
        self.mod._plan_cache.clear()

    def test_get_plan_positive_own_org(self):
        result = run(self.mod.get_plan("plan-A", ctx=ORG_A))
        self.assertEqual(result, {"goal": "org A's plan"})

    def test_get_plan_negative_cross_org_is_404_not_leaked(self):
        with self.assertRaises(HTTPException) as ctx:
            run(self.mod.get_plan("plan-B", ctx=ORG_A))
        self.assertEqual(ctx.exception.status_code, 404)

    def test_get_plan_unknown_id_is_also_404(self):
        with self.assertRaises(HTTPException) as ctx:
            run(self.mod.get_plan("no-such-plan", ctx=ORG_A))
        self.assertEqual(ctx.exception.status_code, 404)

    def test_all_routes_require_org_context(self):
        from app.tenancy.context import org_context
        for name in ("plan_analyze", "plan_execute", "get_plan", "plan_validate"):
            fn = getattr(self.mod, name)
            sig = inspect.signature(fn)
            deps = [p.default.dependency for p in sig.parameters.values()
                    if hasattr(p.default, "dependency")]
            self.assertIn(org_context, deps, f"{name} must depend on org_context")

    def test_plan_execute_forwards_org_id_into_agent_kernel(self):
        """Regression: plan_and_run() has always accepted organization_id —
        the router was silently dropping it."""
        from app.routers.planning_api import PlanRequest

        fake_plan = MagicMock()
        fake_plan.plan_id = "plan-new"
        fake_plan.to_dict.return_value = {"goal": "do the thing"}
        fake_plan.is_safe = True

        fake_engine = MagicMock()
        fake_engine.plan.return_value = fake_plan

        fake_kernel = MagicMock()
        fake_kernel._agents = {}
        fake_kernel.plan_and_run = AsyncMock(return_value={"success": True})

        with patch("app.planning.engine.get_planning_engine", return_value=fake_engine), \
             patch("app.agents.kernel.get_agent_kernel", return_value=fake_kernel):
            run(self.mod.plan_execute(PlanRequest(goal="do the thing"), ctx=ORG_A))

        fake_kernel.plan_and_run.assert_awaited_once()
        _, kwargs = fake_kernel.plan_and_run.await_args
        self.assertEqual(kwargs.get("organization_id"), "org-A")


# ═══════════════════════════════════════════════════════════════════════════════
# Events API — replay / dead-letter queue
# ═══════════════════════════════════════════════════════════════════════════════

class TestEventsApiTenantBoundary(unittest.TestCase):
    def setUp(self):
        from app.core.events.bus import EventBus
        self.bus = EventBus()

    def test_replay_filters_to_callers_org(self):
        from app.routers import events_api
        run(self.bus.publish("billing.invoice_paid", {"amount": 100}, organization_id="org-A"))
        run(self.bus.publish("billing.payment_failed", {"amount": 900}, organization_id="org-B"))
        run(self.bus.publish("organization.member_added", {"email": "x@org-b"}, organization_id="org-B"))

        with patch.object(events_api, "get_event_bus", return_value=self.bus):
            result = run(events_api.replay(ctx=ORG_A))

        types_seen = [e["type"] for e in result["events"]]
        self.assertEqual(types_seen, ["billing.invoice_paid"])
        self.assertTrue(all(e["organization_id"] == "org-A" for e in result["events"]))

    def test_replay_excludes_events_with_no_organization_id(self):
        """Deny-by-default: an event with no org tag is not tenant data we
        can prove belongs to the caller, so it must not be shown either."""
        from app.routers import events_api
        run(self.bus.publish("deployment.completed", {"ok": True}))  # no organization_id

        with patch.object(events_api, "get_event_bus", return_value=self.bus):
            result = run(events_api.replay(ctx=ORG_A))

        self.assertEqual(result["events"], [])

    def test_dead_letters_filters_to_callers_org(self):
        from app.routers import events_api
        self.bus._dlq = [
            {"event": {"type": "integration.sync_failed", "organization_id": "org-A"}, "error": "x"},
            {"event": {"type": "integration.sync_failed", "organization_id": "org-B"}, "error": "y"},
        ]
        with patch.object(events_api, "get_event_bus", return_value=self.bus):
            result = run(events_api.dead_letters(ctx=ORG_A))

        self.assertEqual(len(result["dead_letters"]), 1)
        self.assertEqual(result["dead_letters"][0]["event"]["organization_id"], "org-A")

    def test_stats_remains_unscoped_no_ctx_required(self):
        """stats() carries no per-event/tenant content — confirm it was
        deliberately left without an org_context requirement."""
        from app.routers import events_api
        sig = inspect.signature(events_api.stats)
        self.assertEqual(list(sig.parameters), [], "stats() should take no ctx — aggregate counts only")

    def test_replay_and_dlq_require_org_context(self):
        from app.routers import events_api
        from app.tenancy.context import org_context
        for name in ("replay", "dead_letters"):
            fn = getattr(events_api, name)
            sig = inspect.signature(fn)
            deps = [p.default.dependency for p in sig.parameters.values()
                    if hasattr(p.default, "dependency")]
            self.assertIn(org_context, deps, f"{name} must depend on org_context")


if __name__ == "__main__":
    unittest.main()
