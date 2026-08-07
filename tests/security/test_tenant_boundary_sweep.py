"""
Security Regression Suite — Tenant Boundary Sweep (P0.5.1).

docs/security-tenant-boundary-sweep.md: a systematic sweep for the same
missing-authorization / missing-ownership-check pattern already found and
fixed in app/routers/{runtime_api,kernel_api,planning_api,events_api}.py.
Confirmed by executing the unmodified code against seeded cross-org data
before any production file was touched (transcripts in the audit doc).

Six additional findings, fixed here with the smallest change per finding,
reusing only mechanisms that already exist elsewhere in the codebase:

- app/routers/orchestrator.py: get_execution()/resume_workflow() had no
  ownership check on a process-wide execution_id -> WorkflowExecution
  dict. Fixed with optional_org_id() (matching this file's own existing
  "org-scoped when verified, platform-wide otherwise" convention, see
  cost_summary()/usage_summary()) + an explicit ownership check.
- app/routers/workflow_api.py + app/core/workflow/engine.py: active()/
  pending_approvals()/approve()/reject() had no org filter at all (a
  previously self-documented "known residual gap"). Fixed with
  org_context + optional organization_id params on the engine methods,
  checked against each WorkflowRun's own context["organization_id"].
- app/routers/diagnostics_api.py: service start/stop, alert rule create/
  toggle, codegen approve/reject had zero role check for a process-wide
  privileged capability (same shape as kernel_api.py). Fixed with
  require_api_key(scopes=["admin"]), same mechanism as kernel_api.py.
- app/routers/commands_api.py: execute_command() reached
  app/commands/builtin/modify_cmd.py's arbitrary-path file write with NO
  PolicyEngine-style restriction (worse than kernel_api's pre-fix state)
  and zero role check. Fixed the same way as kernel_api.py.
- app/routers/ws.py agent_ws(): a generic {"type":"subscribe","topic":X}
  relay let an UNAUTHENTICATED caller join any topic string, bypassing
  chat_ws()/notifications_ws()/system_run_ws()'s own authorization
  entirely. Removed (no legitimate caller exists anywhere in the repo)
  and the endpoint now requires the same auth as its siblings.
- app/routers/ws.py job_ws(): no auth, no ownership check at all --
  bypassed the already-fixed REST GET /api/jobs/{job_id}. Fixed with the
  same JWT + org-membership check chat_ws() already uses, plus the same
  organization_id-match convention as jobs_api.py's get_job/cancel_job.
"""
from __future__ import annotations

import asyncio
import inspect
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient


def run(coro):
    return asyncio.run(coro)


# ═══════════════════════════════════════════════════════════════════════════════
# Orchestrator — GET /api/ai/workflows/{execution_id}, POST .../resume
# ═══════════════════════════════════════════════════════════════════════════════

class TestOrchestratorExecutionTenantBoundary(unittest.TestCase):
    def setUp(self):
        from app.routers import orchestrator
        from app.core.ai.platform import platform
        self.mod = orchestrator
        self.executions = platform.workflow._executions
        self.executions.clear()
        from app.core.ai.workflow.engine import WorkflowExecution
        self.executions["exec-A"] = WorkflowExecution(
            execution_id="exec-A", workflow_id="wf-A", state="failed",
            error="org A secret error", context={"organization_id": "org-A"},
        )
        self.executions["exec-B"] = WorkflowExecution(
            execution_id="exec-B", workflow_id="wf-B", state="failed",
            error="org B secret error", context={"organization_id": "org-B"},
        )
        self.executions["exec-noorg"] = WorkflowExecution(
            execution_id="exec-noorg", workflow_id="wf-none", state="completed",
            context={},
        )

    def tearDown(self):
        self.executions.clear()

    def test_owned_execution_positive(self):
        rec = self.mod._owned_workflow_execution("exec-A", "org-A")
        self.assertEqual(rec.error, "org A secret error")

    def test_owned_execution_negative_cross_org(self):
        with self.assertRaises(HTTPException) as ctx:
            self.mod._owned_workflow_execution("exec-B", "org-A")
        self.assertEqual(ctx.exception.status_code, 404)

    def test_owned_execution_no_org_caller_cannot_see_org_tagged(self):
        with self.assertRaises(HTTPException) as ctx:
            self.mod._owned_workflow_execution("exec-A", None)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_owned_execution_unknown_id_is_also_404(self):
        with self.assertRaises(HTTPException) as ctx:
            self.mod._owned_workflow_execution("no-such-exec", "org-A")
        self.assertEqual(ctx.exception.status_code, 404)

    def test_get_execution_uses_optional_org_id_and_denies_cross_org(self):
        fake_request = MagicMock()
        with patch("app.tenancy.context.optional_org_id", AsyncMock(return_value="org-A")):
            result = run(self.mod.get_execution("exec-A", fake_request))
            self.assertEqual(result["error"], "org A secret error")
            with self.assertRaises(HTTPException) as ctx:
                run(self.mod.get_execution("exec-B", fake_request))
            self.assertEqual(ctx.exception.status_code, 404)

    def test_resume_workflow_denies_cross_org_before_the_501(self):
        from app.routers.orchestrator import WorkflowResumeIn
        fake_request = MagicMock()
        with patch("app.tenancy.context.optional_org_id", AsyncMock(return_value="org-A")):
            with self.assertRaises(HTTPException) as ctx:
                run(self.mod.resume_workflow("exec-B", WorkflowResumeIn(), fake_request))
            self.assertEqual(ctx.exception.status_code, 404, "must 404, not leak via the 501 branch")

    def test_run_workflow_never_trusts_client_supplied_organization_id(self):
        """Regression: run_context always overwrites organization_id with
        the server-verified value, even if the client's body.context tried
        to claim a different org."""
        from app.routers.orchestrator import WorkflowRunIn
        fake_request = MagicMock()
        body = WorkflowRunIn(
            definition={"id": "wf", "nodes": {}, "start_node_id": ""},
            context={"organization_id": "attacker-claimed-org"},
        )
        with patch("app.tenancy.context.optional_org_id", AsyncMock(return_value="org-real")), \
             patch.object(self.mod.platform, "workflow") as fake_wf:
            fake_exec = MagicMock()
            fake_exec.execution_id = "e1"
            fake_exec.workflow_id = "wf"
            fake_exec.state = "completed"
            fake_exec.completed_nodes = []
            fake_exec.error = None
            fake_exec.context = {"organization_id": "org-real"}
            fake_wf.run = AsyncMock(return_value=fake_exec)
            run(self.mod.run_workflow(body, fake_request))
            _, kwargs = fake_wf.run.await_args
            passed_context = fake_wf.run.await_args.args[2]
            self.assertEqual(passed_context["organization_id"], "org-real")


# ═══════════════════════════════════════════════════════════════════════════════
# Workflow API — /api/workflows/active, approvals/pending, approve, reject
# ═══════════════════════════════════════════════════════════════════════════════

class TestWorkflowEngineTenantBoundary(unittest.TestCase):
    """Engine-level: app/core/workflow/engine.py's active()/approve()/
    reject()/pending_approvals() optional organization_id filtering."""

    def setUp(self):
        from app.core.workflow.engine import WorkflowBuilder, get_workflow_engine
        self.engine = get_workflow_engine()
        self.engine._active.clear()

        async def _gate(_context, _run_id, **_):
            return {"ok": True}

        self._gate = _gate
        self.run_a = (
            WorkflowBuilder("org-a-workflow")
            .step("gate", "needs approval", _gate, requires_approval=True, timeout_s=0.3)
            .build(context={"organization_id": "org-A"})
        )

    def _start(self, run):
        return asyncio.create_task(self.engine.execute(run, saga=False))

    def test_active_unfiltered_default_preserves_existing_callers(self):
        """organization_id=None (the default) must keep returning
        everything -- backward compatible for any caller that doesn't
        pass it."""
        async def scenario():
            task = self._start(self.run_a)
            await asyncio.sleep(0.05)
            result = self.engine.active()
            await task
            return result
        result = run(scenario())
        self.assertEqual(len(result), 1)

    def test_active_filters_by_org(self):
        async def scenario():
            task = self._start(self.run_a)
            await asyncio.sleep(0.05)
            own = self.engine.active(organization_id="org-A")
            other = self.engine.active(organization_id="org-B")
            await task
            return own, other
        own, other = run(scenario())
        self.assertEqual(len(own), 1)
        self.assertEqual(other, [])

    def test_pending_approvals_filters_by_org(self):
        async def scenario():
            task = self._start(self.run_a)
            await asyncio.sleep(0.05)
            own = self.engine.pending_approvals(organization_id="org-A")
            other = self.engine.pending_approvals(organization_id="org-B")
            await task
            return own, other
        own, other = run(scenario())
        self.assertEqual(len(own), 1)
        self.assertEqual(other, [])

    def test_reject_from_other_org_is_denied_and_does_not_affect_the_step(self):
        async def scenario():
            task = self._start(self.run_a)
            await asyncio.sleep(0.05)
            denied = self.engine.reject(self.run_a.run_id, "gate", organization_id="org-B")
            approved = self.engine.approve(self.run_a.run_id, "gate", organization_id="org-A")
            await task
            return denied, approved
        denied, approved = run(scenario())
        self.assertFalse(denied, "a different org must not be able to reject this step")
        self.assertTrue(approved, "the owning org must still be able to approve it")

    def test_approve_unknown_run_with_org_filter_returns_false_not_true(self):
        result = self.engine.approve("no-such-run", "gate", organization_id="org-A")
        self.assertFalse(result)


class TestWorkflowApiRouterTenantBoundary(unittest.TestCase):
    def test_all_routes_require_org_context(self):
        from app.routers import workflow_api
        from app.tenancy.context import org_context
        for name in ("list_active", "list_pending_approvals", "approve_step",
                     "reject_step", "run_demo_workflow"):
            fn = getattr(workflow_api, name)
            sig = inspect.signature(fn)
            deps = [p.default.dependency for p in sig.parameters.values()
                    if hasattr(p.default, "dependency")]
            self.assertIn(org_context, deps, f"{name} must depend on org_context")

    def test_approve_step_404s_when_engine_denies(self):
        from app.routers import workflow_api
        from app.tenancy.context import OrgContext
        ctx = OrgContext(org_id="org-B", user_id="u1", user_email="b@x.com", role="member")
        with patch.object(workflow_api, "get_workflow_engine") as fake_get_engine:
            fake_engine = MagicMock()
            fake_engine.approve.return_value = False
            fake_get_engine.return_value = fake_engine
            with self.assertRaises(HTTPException) as exc_ctx:
                workflow_api.approve_step("run-a", "gate", ctx=ctx)
            self.assertEqual(exc_ctx.exception.status_code, 404)
            fake_engine.approve.assert_called_once_with("run-a", "gate", organization_id="org-B")


# ═══════════════════════════════════════════════════════════════════════════════
# Diagnostics API — service start/stop, alert rules, codegen approve/reject
# ═══════════════════════════════════════════════════════════════════════════════

class TestDiagnosticsApiAuthorization(unittest.TestCase):
    def test_privileged_routes_require_admin_api_key(self):
        from app.routers import diagnostics_api
        from app.core.api_keys import require_api_key
        target_qualname = require_api_key(scopes=["admin"]).__qualname__
        for name in ("service_start", "service_stop", "create_alert_rule",
                     "toggle_alert_rule", "codegen_approve", "codegen_reject"):
            fn = getattr(diagnostics_api, name)
            sig = inspect.signature(fn)
            gated = any(
                hasattr(p.default, "dependency")
                and getattr(p.default.dependency, "__qualname__", "") == target_qualname
                for p in sig.parameters.values()
            )
            self.assertTrue(gated, f"{name} must require require_api_key(scopes=['admin'])")

    def test_read_only_routes_remain_unchanged(self):
        """No-tenant-data observability routes must NOT have gained an
        admin-key requirement -- confirms this is a scoped fix, not a
        blanket lockdown."""
        from app.routers import diagnostics_api
        for name in ("diagnostics_health", "diagnostics_metrics",
                     "diagnostics_services", "list_alert_rules"):
            fn = getattr(diagnostics_api, name)
            sig = inspect.signature(fn)
            gated = any(hasattr(p.default, "dependency") for p in sig.parameters.values())
            self.assertFalse(gated, f"{name} should remain ungated (no tenant data)")

    def test_service_start_rejects_request_with_no_api_key(self):
        from fastapi import FastAPI
        from app.routers.diagnostics_api import router
        app = FastAPI()
        app.include_router(router)
        with TestClient(app, raise_server_exceptions=False) as c:
            res = c.post("/api/diagnostics/services/health_monitor/start")
        self.assertEqual(res.status_code, 401)

    def test_service_start_accepts_admin_scoped_key(self):
        from fastapi import FastAPI
        from app.routers.diagnostics_api import router
        from app.core.api_keys import ApiKeyRecord
        app = FastAPI()
        app.include_router(router)
        admin_key = ApiKeyRecord(key_id="k", key_hash="h", name="admin", scopes=["admin"])
        with patch("app.core.api_keys.lookup_key", AsyncMock(return_value=admin_key)), \
             patch("app.services.registry.get_service_registry") as fake_reg:
            fake_reg.return_value.start.return_value = True
            with TestClient(app, raise_server_exceptions=False) as c:
                res = c.post(
                    "/api/diagnostics/services/health_monitor/start",
                    headers={"Authorization": "ApiKey axon_faketoken"},
                )
        self.assertEqual(res.status_code, 200)


# ═══════════════════════════════════════════════════════════════════════════════
# Commands API — execute_command reaching modify_cmd's unrestricted file write
# ═══════════════════════════════════════════════════════════════════════════════

class TestCommandsApiAuthorization(unittest.TestCase):
    def test_execute_command_requires_admin_api_key(self):
        from app.routers import commands_api
        from app.core.api_keys import require_api_key
        target_qualname = require_api_key(scopes=["admin"]).__qualname__
        sig = inspect.signature(commands_api.execute_command)
        gated = any(
            hasattr(p.default, "dependency")
            and getattr(p.default.dependency, "__qualname__", "") == target_qualname
            for p in sig.parameters.values()
        )
        self.assertTrue(gated)

    def test_read_only_routes_remain_unchanged(self):
        from app.routers import commands_api
        for name in ("list_commands", "describe_command"):
            fn = getattr(commands_api, name)
            sig = inspect.signature(fn)
            gated = any(hasattr(p.default, "dependency") for p in sig.parameters.values())
            self.assertFalse(gated, f"{name} should remain ungated (no tenant data)")

    def test_execute_command_rejects_request_with_no_api_key(self):
        from fastapi import FastAPI
        from app.routers.commands_api import router
        app = FastAPI()
        app.include_router(router)
        with TestClient(app, raise_server_exceptions=False) as c:
            res = c.post("/api/commands/execute", json={"input": "status"})
        self.assertEqual(res.status_code, 401)

    def test_modify_file_command_still_unrestricted_at_the_command_layer(self):
        """This sweep's fix is authorization at the router boundary, NOT a
        redesign of modify_cmd's file-write logic itself (that would be
        an architecture change out of this gate's scope) -- confirms the
        underlying capability is unchanged, only who can reach it via
        POST /api/commands/execute changed."""
        import inspect as _inspect
        from app.commands.builtin.modify_cmd import _modify_file
        source = _inspect.getsource(_modify_file)
        self.assertNotIn("PolicyEngine", source)


# ═══════════════════════════════════════════════════════════════════════════════
# WebSocket — agent_ws topic-bypass, job_ws auth/ownership
# ═══════════════════════════════════════════════════════════════════════════════

class TestAgentWsNoLongerBypassesOtherTopics(unittest.TestCase):
    def _app(self):
        from fastapi import FastAPI
        from app.routers.ws import router
        app = FastAPI()
        app.include_router(router)
        return app

    def test_unauthenticated_connect_is_rejected(self):
        with TestClient(self._app()) as c:
            with self.assertRaises(Exception):
                with c.websocket_connect("/ws/agent/anything"):
                    pass

    def test_authenticated_connect_still_works(self):
        with patch("app.routers.ws._user_id_from_ws_token", return_value="user-1"):
            with TestClient(self._app()) as c:
                with c.websocket_connect("/ws/agent/sess-1?token=x") as ws:
                    hello = ws.receive_json()
                    self.assertEqual(hello["type"], "connected")
                    ws.send_json({"type": "ping"})
                    self.assertEqual(ws.receive_json(), {"type": "pong"})

    def test_subscribe_to_foreign_topic_no_longer_relays_other_tenants_data(self):
        """The core regression for this finding: an attacker on
        /ws/agent/{anything} sending {"type":"subscribe","topic":"notifications:victim"}
        must NOT start receiving frames broadcast to that topic."""
        from app.routers.ws import manager
        with patch("app.routers.ws._user_id_from_ws_token", return_value="user-1"):
            with TestClient(self._app()) as c:
                with c.websocket_connect("/ws/agent/sess-1?token=x") as ws:
                    ws.receive_json()  # connected frame
                    ws.send_json({"type": "subscribe", "topic": "notifications:victim-user"})
                    # No "subscribed" ack -- the handler for this message
                    # type no longer exists.
                    ws.send_json({"type": "ping"})
                    self.assertEqual(ws.receive_json(), {"type": "pong"},
                                     "next frame must be the pong, not a 'subscribed' ack")

                    async def _broadcast():
                        await manager.broadcast("notifications:victim-user", {"secret": "victim data"})
                    run(_broadcast())

                    # Nothing further should arrive for this socket from
                    # that topic -- send one more ping/pong round-trip and
                    # confirm it's still just a pong, not the victim frame.
                    ws.send_json({"type": "ping"})
                    self.assertEqual(ws.receive_json(), {"type": "pong"})


class TestJobWsTenantBoundary(unittest.TestCase):
    def _app(self):
        from fastapi import FastAPI
        from app.routers.ws import router
        app = FastAPI()
        app.include_router(router)
        return app

    def _fake_job(self, org_id: str):
        job = MagicMock()
        job.to_dict.return_value = {"id": "job-1", "organization_id": org_id}
        job.status.value = "completed"
        job.payload = {"organization_id": org_id}
        return job

    def test_unauthenticated_connect_is_rejected(self):
        with TestClient(self._app()) as c:
            with self.assertRaises(Exception):
                with c.websocket_connect("/ws/job/job-1"):
                    pass

    def test_missing_org_id_is_rejected(self):
        with patch("app.routers.ws._user_id_from_ws_token", return_value="user-A"):
            with TestClient(self._app()) as c:
                with self.assertRaises(Exception):
                    with c.websocket_connect("/ws/job/job-1?token=x"):
                        pass

    def test_own_org_job_positive(self):
        fake_queue = MagicMock()
        fake_queue.get = AsyncMock(return_value=self._fake_job("org-A"))
        with patch("app.routers.ws._user_id_from_ws_token", return_value="user-A"), \
             patch("app.core.jobs.get_job_queue", return_value=fake_queue), \
             patch("app.tenancy.get_tenancy_service") as gts:
            gts.return_value.get_member_role = AsyncMock(
                side_effect=lambda org_id, user_id: "member" if org_id == "org-A" else None)
            with TestClient(self._app()) as c:
                with c.websocket_connect("/ws/job/job-1?token=x&org_id=org-A") as ws:
                    frame = ws.receive_json()
                    self.assertEqual(frame["type"], "snapshot")
                    self.assertEqual(frame["job"]["organization_id"], "org-A")

    def test_cross_org_job_is_denied_not_leaked(self):
        """org-B is a real, verified member of org-B, but the job belongs
        to org-A -- must get the same not-found message as a bogus id,
        never the job's real content."""
        fake_queue = MagicMock()
        fake_queue.get = AsyncMock(return_value=self._fake_job("org-A"))
        with patch("app.routers.ws._user_id_from_ws_token", return_value="user-B"), \
             patch("app.core.jobs.get_job_queue", return_value=fake_queue), \
             patch("app.tenancy.get_tenancy_service") as gts:
            gts.return_value.get_member_role = AsyncMock(
                side_effect=lambda org_id, user_id: "member" if org_id == "org-B" else None)
            with TestClient(self._app()) as c:
                with c.websocket_connect("/ws/job/job-1?token=x&org_id=org-B") as ws:
                    frame = ws.receive_json()
                    self.assertEqual(frame["type"], "error")
                    self.assertNotIn("organization_id", frame)

    def test_non_member_org_id_is_denied(self):
        """Caller supplies an org_id they're not actually a member of --
        must be rejected before ever touching the job queue."""
        fake_queue = MagicMock()
        fake_queue.get = AsyncMock(return_value=self._fake_job("org-A"))
        with patch("app.routers.ws._user_id_from_ws_token", return_value="user-X"), \
             patch("app.core.jobs.get_job_queue", return_value=fake_queue), \
             patch("app.tenancy.get_tenancy_service") as gts:
            gts.return_value.get_member_role = AsyncMock(return_value=None)
            with TestClient(self._app()) as c:
                with self.assertRaises(Exception):
                    with c.websocket_connect("/ws/job/job-1?token=x&org_id=org-A"):
                        pass
        fake_queue.get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
