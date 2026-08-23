"""
/api/build/plan — quota enforcement tests.

Phase 2.5 Audit (2026-08-23) found that build_plan() did not call
check_org_quota() before engine.complete(), letting over-quota orgs
trigger real Anthropic calls for free.  This file verifies the fix.

Coverage (P1 audit findings):
  A. Unauthenticated request              → 401, engine never called
  B. Authenticated + no org (None quota)  → AI call proceeds, org_id=None OK
  C. Authenticated + org within quota     → AI call proceeds, org_id propagated
  D. Authenticated + org over quota       → 429 raised BEFORE engine.complete()
  E. engine.complete() call count is 0 on quota exhaustion
  F. org_id propagated correctly to engine (billing path)
  G. rate limit still applied independently of quota check
  H. /api/build (non-streaming) unaffected (quota call order unchanged)
  I. Execution order enforced: Auth → RateLimit → Quota → AI

DB interaction is fully mocked — no live Postgres needed.
"""
from __future__ import annotations

import asyncio
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import HTTPException

# ── Shared fixtures ────────────────────────────────────────────────────────────

def _fake_pool():
    """Pool mock whose acquire() yields a MagicMock conn."""
    conn = MagicMock()
    conn.fetchval = AsyncMock(return_value=uuid.uuid4())
    conn.fetch = AsyncMock(return_value=[])
    conn.execute = AsyncMock(return_value="OK")

    conn_cm = MagicMock()
    conn_cm.__aenter__ = AsyncMock(return_value=conn)
    conn_cm.__aexit__ = AsyncMock(return_value=False)

    pool = MagicMock()
    pool.acquire.return_value = conn_cm
    return pool, conn


def _fake_request():
    """Minimal FastAPI Request-alike for passing to route handlers."""
    req = MagicMock()
    req.headers = {}
    req.client = MagicMock()
    req.client.host = "127.0.0.1"
    return req


def _plan_request(prompt: str = "Build a CRM"):
    """Minimal PlanRequest-alike."""
    req = MagicMock()
    req.prompt = prompt
    return req


def _fake_completion(content: str = (
    '{"name":"Test","description":"d","tech_stack":{},'
    '"pages":[],"database_tables":[],"api_routes":[],'
    '"agents":[],"workflows":[],"integrations":[],'
    '"estimated_files":3,"complexity":"simple"}'
)):
    resp = MagicMock()
    resp.content = content
    resp.usage = MagicMock()
    resp.usage.total_tokens = 200
    return resp


def _run(coro):
    """Run a coroutine in a fresh event loop (Python 3.10+ safe)."""
    return asyncio.run(coro)


# ── Import under test after env is set ────────────────────────────────────────

from app.routers.build import build_plan  # noqa: E402


# ══════════════════════════════════════════════════════════════════════════════
# Case A — Unauthenticated request → 401, engine never called
# ══════════════════════════════════════════════════════════════════════════════

class TestBuildPlanUnauth(unittest.TestCase):
    def test_401_raised_before_engine(self):
        pool, _ = _fake_pool()
        engine_mock = MagicMock()
        engine_mock.complete = AsyncMock()

        with (
            patch("app.routers.build.get_pool", return_value=pool),
            patch("app.routers.build.owner_user_id",
                  new=AsyncMock(side_effect=HTTPException(401, "Not authenticated"))),
            patch("app.routers.build.ai_rate_limit"),
            patch("app.routers.build.check_org_quota", new=AsyncMock(return_value=None)),
            patch("app.routers.build.InferenceEngine", return_value=engine_mock),
        ):
            with self.assertRaises(HTTPException) as ctx:
                _run(build_plan(_plan_request(), _fake_request()))

        self.assertEqual(ctx.exception.status_code, 401)
        engine_mock.complete.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
# Case B — Authenticated, no org (quota returns None) → AI call proceeds
# ══════════════════════════════════════════════════════════════════════════════

class TestBuildPlanNoOrg(unittest.TestCase):
    def test_no_org_proceeds_with_org_id_none(self):
        pool, _ = _fake_pool()
        engine_mock = MagicMock()
        engine_mock.complete = AsyncMock(return_value=_fake_completion())
        uid = uuid.uuid4()

        with (
            patch("app.routers.build.get_pool", return_value=pool),
            patch("app.routers.build.owner_user_id", new=AsyncMock(return_value=uid)),
            patch("app.routers.build.ai_rate_limit"),
            patch("app.routers.build.check_org_quota", new=AsyncMock(return_value=None)),
            patch("app.routers.build.InferenceEngine", return_value=engine_mock),
        ):
            result = _run(build_plan(_plan_request(), _fake_request()))

        self.assertIn("plan", result)
        engine_mock.complete.assert_called_once()
        _kwargs = engine_mock.complete.call_args.kwargs
        self.assertIsNone(_kwargs.get("org_id"))


# ══════════════════════════════════════════════════════════════════════════════
# Case C — Authenticated + org within quota → AI call proceeds, org_id propagated
# ══════════════════════════════════════════════════════════════════════════════

class TestBuildPlanWithinQuota(unittest.TestCase):
    def test_within_quota_org_id_propagated(self):
        pool, _ = _fake_pool()
        engine_mock = MagicMock()
        engine_mock.complete = AsyncMock(return_value=_fake_completion())
        uid = uuid.uuid4()
        org_id = str(uuid.uuid4())

        with (
            patch("app.routers.build.get_pool", return_value=pool),
            patch("app.routers.build.owner_user_id", new=AsyncMock(return_value=uid)),
            patch("app.routers.build.ai_rate_limit"),
            patch("app.routers.build.check_org_quota", new=AsyncMock(return_value=org_id)),
            patch("app.routers.build.InferenceEngine", return_value=engine_mock),
        ):
            result = _run(build_plan(_plan_request(), _fake_request()))

        self.assertIn("plan", result)
        engine_mock.complete.assert_called_once()
        _kwargs = engine_mock.complete.call_args.kwargs
        self.assertEqual(_kwargs.get("org_id"), org_id)


# ══════════════════════════════════════════════════════════════════════════════
# Case D — Authenticated + over quota → 429 raised BEFORE engine.complete()
# ══════════════════════════════════════════════════════════════════════════════

class TestBuildPlanOverQuota(unittest.TestCase):
    def test_429_raised_before_ai_call(self):
        pool, _ = _fake_pool()
        engine_mock = MagicMock()
        engine_mock.complete = AsyncMock()
        uid = uuid.uuid4()

        with (
            patch("app.routers.build.get_pool", return_value=pool),
            patch("app.routers.build.owner_user_id", new=AsyncMock(return_value=uid)),
            patch("app.routers.build.ai_rate_limit"),
            patch("app.routers.build.check_org_quota",
                  new=AsyncMock(side_effect=HTTPException(429, "Token quota exceeded"))),
            patch("app.routers.build.InferenceEngine", return_value=engine_mock),
        ):
            with self.assertRaises(HTTPException) as ctx:
                _run(build_plan(_plan_request(), _fake_request()))

        self.assertEqual(ctx.exception.status_code, 429)

    # Case E — engine.complete() call count is 0 on quota exhaustion
    def test_engine_not_called_on_quota_exhaustion(self):
        pool, _ = _fake_pool()
        engine_mock = MagicMock()
        engine_mock.complete = AsyncMock()
        uid = uuid.uuid4()

        with (
            patch("app.routers.build.get_pool", return_value=pool),
            patch("app.routers.build.owner_user_id", new=AsyncMock(return_value=uid)),
            patch("app.routers.build.ai_rate_limit"),
            patch("app.routers.build.check_org_quota",
                  new=AsyncMock(side_effect=HTTPException(429, "Token quota exceeded"))),
            patch("app.routers.build.InferenceEngine", return_value=engine_mock),
        ):
            try:
                _run(build_plan(_plan_request(), _fake_request()))
            except HTTPException:
                pass

        # Core invariant: quota guard fires BEFORE the AI call
        engine_mock.complete.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
# Case F — org_id propagated correctly to inference (billing path)
# ══════════════════════════════════════════════════════════════════════════════

class TestBuildPlanOrgIdPropagation(unittest.TestCase):
    def test_org_id_reaches_inference_engine(self):
        """Verify the exact keyword argument passed to engine.complete()."""
        pool, _ = _fake_pool()
        engine_mock = MagicMock()
        engine_mock.complete = AsyncMock(return_value=_fake_completion())
        uid = uuid.uuid4()
        expected_org = "org-abc-123"

        with (
            patch("app.routers.build.get_pool", return_value=pool),
            patch("app.routers.build.owner_user_id", new=AsyncMock(return_value=uid)),
            patch("app.routers.build.ai_rate_limit"),
            patch("app.routers.build.check_org_quota",
                  new=AsyncMock(return_value=expected_org)),
            patch("app.routers.build.InferenceEngine", return_value=engine_mock),
        ):
            _run(build_plan(_plan_request(), _fake_request()))

        actual_kwargs = engine_mock.complete.call_args.kwargs
        self.assertEqual(actual_kwargs["org_id"], expected_org,
                         "org_id must be passed to engine.complete() for billing attribution")


# ══════════════════════════════════════════════════════════════════════════════
# Case G — rate limit still applied independently of quota check
# ══════════════════════════════════════════════════════════════════════════════

class TestBuildPlanRateLimit(unittest.TestCase):
    def test_execution_order_auth_ratelimit_quota_ai(self):
        """Execution order: Auth → RateLimit → Quota → AI — must hold."""
        pool, _ = _fake_pool()
        engine_mock = MagicMock()
        engine_mock.complete = AsyncMock(return_value=_fake_completion())
        uid = uuid.uuid4()
        call_order: list[str] = []

        async def auth_fn(*a, **kw):
            call_order.append("auth")
            return uid

        def rl_fn(*a, **kw):
            call_order.append("rate_limit")

        async def quota_fn(*a, **kw):
            call_order.append("quota")
            return None  # within quota

        with (
            patch("app.routers.build.get_pool", return_value=pool),
            patch("app.routers.build.owner_user_id", new=auth_fn),
            patch("app.routers.build.ai_rate_limit", side_effect=rl_fn),
            patch("app.routers.build.check_org_quota", new=quota_fn),
            patch("app.routers.build.InferenceEngine", return_value=engine_mock),
        ):
            _run(build_plan(_plan_request(), _fake_request()))

        self.assertEqual(call_order, ["auth", "rate_limit", "quota"],
                         f"Wrong call order: {call_order}")
        engine_mock.complete.assert_called_once()

    def test_rate_limit_raises_429_before_quota_and_ai(self):
        """Rate limit firing blocks quota check and AI call entirely."""
        pool, _ = _fake_pool()
        engine_mock = MagicMock()
        engine_mock.complete = AsyncMock()
        uid = uuid.uuid4()
        quota_mock = AsyncMock(return_value=None)

        with (
            patch("app.routers.build.get_pool", return_value=pool),
            patch("app.routers.build.owner_user_id", new=AsyncMock(return_value=uid)),
            patch("app.routers.build.ai_rate_limit",
                  side_effect=HTTPException(429, "Rate limit exceeded")),
            patch("app.routers.build.check_org_quota", new=quota_mock),
            patch("app.routers.build.InferenceEngine", return_value=engine_mock),
        ):
            with self.assertRaises(HTTPException) as ctx:
                _run(build_plan(_plan_request(), _fake_request()))

        self.assertEqual(ctx.exception.status_code, 429)
        quota_mock.assert_not_called()
        engine_mock.complete.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
# Case H — /api/build (non-streaming) still calls check_org_quota first
# ══════════════════════════════════════════════════════════════════════════════

class TestBuildEndpointUnaffected(unittest.TestCase):
    """Verify the non-streaming /api/build still calls check_org_quota
    and that the fix to build_plan did not disturb it."""

    def test_build_still_calls_check_org_quota(self):
        import tempfile, pathlib
        from app.routers.build import build_program

        pool, conn = _fake_pool()
        project_uuid = uuid.uuid4()
        conn.fetchval = AsyncMock(return_value=project_uuid)

        uid = uuid.uuid4()
        org_id = str(uuid.uuid4())
        quota_mock = AsyncMock(return_value=org_id)

        resp_mock = MagicMock()
        resp_mock.content = (
            '{"description":"d",'
            '"files":[{"path":"main.py","content":"print(1)"}],'
            '"run_command":"python main.py","language":"python"}'
        )
        resp_mock.usage = MagicMock()
        resp_mock.usage.total_tokens = 100

        engine_mock = MagicMock()
        engine_mock.complete = AsyncMock(return_value=resp_mock)

        req = MagicMock()
        req.project_id = str(project_uuid)
        req.prompt = "Build a script"

        ws = pathlib.Path(tempfile.mkdtemp())

        # get_bulkhead is imported locally in build_program — patch at source
        bulkhead_cm = MagicMock()
        bulkhead_cm.__aenter__ = AsyncMock(return_value=None)
        bulkhead_cm.__aexit__ = AsyncMock(return_value=False)
        bulkhead_obj = MagicMock()
        bulkhead_obj.acquire.return_value = bulkhead_cm

        with (
            patch("app.routers.build.get_pool", return_value=pool),
            patch("app.routers.build.owner_user_id", new=AsyncMock(return_value=uid)),
            patch("app.routers.build.ai_rate_limit"),
            patch("app.routers.build.check_org_quota", new=quota_mock),
            patch("app.routers.build.InferenceEngine", return_value=engine_mock),
            patch("app.routers.build.resolve_project_id",
                  new=AsyncMock(return_value=str(project_uuid))),
            patch("app.routers.build.workspace", return_value=ws),
            patch("app.routers.build.record_org_tokens", new=AsyncMock()),
            patch("app.core.reliability.get_bulkhead", return_value=bulkhead_obj),
        ):
            _run(build_program(req, _fake_request()))

        quota_mock.assert_called_once()

    # Case I — Execution order on /api/build: quota must come before AI call
    def test_build_quota_before_ai(self):
        import tempfile, pathlib
        from app.routers.build import build_program

        pool, conn = _fake_pool()
        project_uuid = uuid.uuid4()
        conn.fetchval = AsyncMock(return_value=project_uuid)

        uid = uuid.uuid4()
        engine_mock = MagicMock()
        engine_mock.complete = AsyncMock()
        ws = pathlib.Path(tempfile.mkdtemp())
        req = MagicMock()
        req.project_id = str(project_uuid)
        req.prompt = "Build a script"

        bulkhead_cm = MagicMock()
        bulkhead_cm.__aenter__ = AsyncMock(return_value=None)
        bulkhead_cm.__aexit__ = AsyncMock(return_value=False)
        bulkhead_obj = MagicMock()
        bulkhead_obj.acquire.return_value = bulkhead_cm

        with (
            patch("app.routers.build.get_pool", return_value=pool),
            patch("app.routers.build.owner_user_id", new=AsyncMock(return_value=uid)),
            patch("app.routers.build.ai_rate_limit"),
            patch("app.routers.build.check_org_quota",
                  new=AsyncMock(side_effect=HTTPException(429, "quota exceeded"))),
            patch("app.routers.build.InferenceEngine", return_value=engine_mock),
            patch("app.routers.build.resolve_project_id",
                  new=AsyncMock(return_value=str(project_uuid))),
            patch("app.routers.build.workspace", return_value=ws),
            patch("app.core.reliability.get_bulkhead", return_value=bulkhead_obj),
        ):
            with self.assertRaises(HTTPException) as ctx:
                _run(build_program(req, _fake_request()))

        self.assertEqual(ctx.exception.status_code, 429)
        engine_mock.complete.assert_not_called()


# ── Runner ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    unittest.main()
