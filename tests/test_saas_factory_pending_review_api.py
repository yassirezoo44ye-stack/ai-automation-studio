"""
SaaS Factory — GET /api/saas-factory/projects/pending-review (P1 surface test).

Tests cover:
  - Returns only PENDING_REVIEW rows for the caller's org
  - Empty list when none pending
  - Org isolation (query is scoped to ctx.org_id)
  - idea_text truncated at 120 characters
  - Response shape (keys match frontend's SecurityReviewItem type)
  - Ordered oldest-first (ORDER BY updated_at ASC)
  - Route registered before /{project_id} (no shadowing)
  - Source-level permission guard: require_permission("saas_factory", "read")

Pattern: call route function directly with a hand-built OrgContext and mocked pool,
bypassing require_permission dependency (same pattern as tests/test_presence.py).
"""
from __future__ import annotations

import asyncio
import datetime
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _mock_pool_rows(rows: list) -> MagicMock:
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=rows)
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool


def _make_ctx(org_id: str | None = None, user_id: str | None = None):
    from app.tenancy import OrgContext
    return OrgContext(
        org_id=org_id or str(uuid.uuid4()),
        user_id=user_id or str(uuid.uuid4()),
        user_email="tester@example.com",
        role="admin",
    )


def _make_row(project_id: str, idea: str, updated_at: datetime.datetime) -> MagicMock:
    row = MagicMock()
    row.__getitem__ = lambda self, k: {
        "id": uuid.UUID(project_id),
        "idea_text": idea,
        "updated_at": updated_at,
    }[k]
    return row


ORG_A = str(uuid.uuid4())
ORG_B = str(uuid.uuid4())
P1 = str(uuid.uuid4())
P2 = str(uuid.uuid4())

T1 = datetime.datetime(2025, 1, 10, 8, 0, 0, tzinfo=datetime.timezone.utc)
T2 = datetime.datetime(2025, 1, 12, 9, 0, 0, tzinfo=datetime.timezone.utc)


class TestListPendingReviewEndpoint:

    def test_returns_pending_review_projects(self):
        from app.routers.saas_factory import list_pending_review
        pool = _mock_pool_rows([_make_row(P1, "Build a CRM", T1)])
        ctx = _make_ctx(org_id=ORG_A)
        with patch("app.routers.saas_factory.get_pool", return_value=pool):
            result = run(list_pending_review(ctx=ctx))
        reviews = result["pending_security_reviews"]
        assert len(reviews) == 1
        assert reviews[0]["project_id"] == P1
        assert reviews[0]["idea_text"] == "Build a CRM"
        assert reviews[0]["waiting_since"] == T1.isoformat()

    def test_empty_list_when_no_pending_review(self):
        from app.routers.saas_factory import list_pending_review
        pool = _mock_pool_rows([])
        ctx = _make_ctx(org_id=ORG_A)
        with patch("app.routers.saas_factory.get_pool", return_value=pool):
            result = run(list_pending_review(ctx=ctx))
        assert result == {"pending_security_reviews": []}

    def test_org_isolation_query_scoped_to_caller_org(self):
        """DB query must use ctx.org_id — not a caller-supplied value."""
        from app.routers.saas_factory import list_pending_review
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])
        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        ctx = _make_ctx(org_id=ORG_A)
        with patch("app.routers.saas_factory.get_pool", return_value=pool):
            run(list_pending_review(ctx=ctx))

        call_args = conn.fetch.call_args
        # Second positional arg must be org_id as UUID — never ORG_B
        assert call_args[0][1] == uuid.UUID(ORG_A)

    def test_org_b_cannot_see_org_a_projects(self):
        """Even with same project ids, ORG_B gets an empty list because the
        SQL uses WHERE org_id=$1 — verified by ensuring fetch receives ORG_B."""
        from app.routers.saas_factory import list_pending_review
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])
        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        ctx_b = _make_ctx(org_id=ORG_B)
        with patch("app.routers.saas_factory.get_pool", return_value=pool):
            result = run(list_pending_review(ctx=ctx_b))

        passed_org = conn.fetch.call_args[0][1]
        assert passed_org == uuid.UUID(ORG_B)
        assert result["pending_security_reviews"] == []

    def test_idea_text_truncated_at_120_chars(self):
        from app.routers.saas_factory import list_pending_review
        long_idea = "A" * 200
        pool = _mock_pool_rows([_make_row(P1, long_idea, T1)])
        ctx = _make_ctx(org_id=ORG_A)
        with patch("app.routers.saas_factory.get_pool", return_value=pool):
            result = run(list_pending_review(ctx=ctx))
        truncated = result["pending_security_reviews"][0]["idea_text"]
        assert len(truncated) == 120
        assert truncated == "A" * 120

    def test_idea_text_short_not_truncated(self):
        from app.routers.saas_factory import list_pending_review
        short_idea = "Short idea"
        pool = _mock_pool_rows([_make_row(P1, short_idea, T1)])
        ctx = _make_ctx(org_id=ORG_A)
        with patch("app.routers.saas_factory.get_pool", return_value=pool):
            result = run(list_pending_review(ctx=ctx))
        assert result["pending_security_reviews"][0]["idea_text"] == short_idea

    def test_response_shape_matches_frontend_type(self):
        """Every item must have exactly project_id, idea_text, waiting_since."""
        from app.routers.saas_factory import list_pending_review
        pool = _mock_pool_rows([_make_row(P1, "Some idea", T1)])
        ctx = _make_ctx(org_id=ORG_A)
        with patch("app.routers.saas_factory.get_pool", return_value=pool):
            result = run(list_pending_review(ctx=ctx))
        item = result["pending_security_reviews"][0]
        assert set(item.keys()) == {"project_id", "idea_text", "waiting_since"}

    def test_oldest_first_ordering_via_query(self):
        """The SQL uses ORDER BY updated_at ASC; verify via returned row order
        (mock returns rows in the order DB would — we return T1 before T2)."""
        from app.routers.saas_factory import list_pending_review
        row1 = _make_row(P1, "Older project", T1)
        row2 = _make_row(P2, "Newer project", T2)
        # DB (mocked) returns oldest first — assert output preserves order
        pool = _mock_pool_rows([row1, row2])
        ctx = _make_ctx(org_id=ORG_A)
        with patch("app.routers.saas_factory.get_pool", return_value=pool):
            result = run(list_pending_review(ctx=ctx))
        reviews = result["pending_security_reviews"]
        assert len(reviews) == 2
        assert reviews[0]["project_id"] == P1
        assert reviews[1]["project_id"] == P2

    def test_route_registered_before_project_id_wildcard(self):
        """pending-review must not be shadowed by /{project_id}."""
        from app.routers.saas_factory import router
        routes = [(r.path, r.methods) for r in router.routes if hasattr(r, "methods")]
        pr_idx = next(
            (i for i, (p, _) in enumerate(routes) if p.endswith("/projects/pending-review")),
            None,
        )
        wildcard_idx = next(
            (i for i, (p, _) in enumerate(routes) if p.endswith("/projects/{project_id}") and "GET" in (_)),
            None,
        )
        assert pr_idx is not None, "/projects/pending-review route missing"
        assert wildcard_idx is not None, "/projects/{project_id} route missing"
        assert pr_idx < wildcard_idx, (
            "/projects/pending-review must be registered before /projects/{project_id} "
            "to avoid FastAPI treating 'pending-review' as a project_id"
        )

    def test_permission_guard_is_read(self):
        """Route source must use require_permission('saas_factory', 'read')."""
        import inspect
        from app.routers import saas_factory as mod
        src = inspect.getsource(mod.list_pending_review)
        assert 'require_permission("saas_factory", "read")' in src

    def test_db_error_propagates_not_swallowed(self):
        """A DB connection failure must raise, not silently return an empty list."""
        from app.routers.saas_factory import list_pending_review
        conn = AsyncMock()
        conn.fetch = AsyncMock(side_effect=RuntimeError("connection refused"))
        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
        ctx = _make_ctx(org_id=ORG_A)
        with patch("app.routers.saas_factory.get_pool", return_value=pool):
            with pytest.raises(RuntimeError, match="connection refused"):
                run(list_pending_review(ctx=ctx))

    def test_waiting_since_is_iso8601_with_timezone(self):
        """waiting_since must be an ISO-8601 string with UTC timezone offset."""
        from app.routers.saas_factory import list_pending_review
        pool = _mock_pool_rows([_make_row(P1, "Build a CRM", T1)])
        ctx = _make_ctx(org_id=ORG_A)
        with patch("app.routers.saas_factory.get_pool", return_value=pool):
            result = run(list_pending_review(ctx=ctx))
        ws = result["pending_security_reviews"][0]["waiting_since"]
        # Must be parseable as ISO-8601 and preserve timezone info.
        parsed = datetime.datetime.fromisoformat(ws)
        assert parsed.tzinfo is not None, "waiting_since must include timezone"
        assert parsed == T1

    def test_multiple_projects_all_returned(self):
        """All PENDING_REVIEW rows are returned, not just the first."""
        from app.routers.saas_factory import list_pending_review
        T3 = datetime.datetime(2025, 1, 14, 10, 0, 0, tzinfo=datetime.timezone.utc)
        P3 = str(uuid.uuid4())
        rows = [_make_row(P1, "Idea one", T1), _make_row(P2, "Idea two", T2), _make_row(P3, "Idea three", T3)]
        pool = _mock_pool_rows(rows)
        ctx = _make_ctx(org_id=ORG_A)
        with patch("app.routers.saas_factory.get_pool", return_value=pool):
            result = run(list_pending_review(ctx=ctx))
        reviews = result["pending_security_reviews"]
        assert len(reviews) == 3
        assert {r["project_id"] for r in reviews} == {P1, P2, P3}

    def test_approve_security_permission_guard_is_update(self):
        """approve-security must require saas_factory:update, not just read."""
        import inspect
        from app.routers import saas_factory as mod
        src = inspect.getsource(mod.approve_security)
        assert 'require_permission("saas_factory", "update")' in src

    def test_reject_security_permission_guard_is_update(self):
        """reject-security must require saas_factory:update, not just read."""
        import inspect
        from app.routers import saas_factory as mod
        src = inspect.getsource(mod.reject_security)
        assert 'require_permission("saas_factory", "update")' in src

    def test_idea_text_truncated_exactly_at_boundary(self):
        """Idea text of exactly 120 chars must not be truncated."""
        from app.routers.saas_factory import list_pending_review
        exact_idea = "B" * 120
        pool = _mock_pool_rows([_make_row(P1, exact_idea, T1)])
        ctx = _make_ctx(org_id=ORG_A)
        with patch("app.routers.saas_factory.get_pool", return_value=pool):
            result = run(list_pending_review(ctx=ctx))
        assert result["pending_security_reviews"][0]["idea_text"] == exact_idea


# ── Approve / reject router endpoints ────────────────────────────────────────

def _mock_pipeline(approve_result=None, reject_result=None, side_effect=None):
    pipeline = MagicMock()
    if side_effect is not None:
        pipeline.approve = AsyncMock(side_effect=side_effect)
        pipeline.reject  = AsyncMock(side_effect=side_effect)
    else:
        pipeline.approve = AsyncMock(return_value=approve_result or {"project_id": P1, "resumed_from": "DEPLOYING"})
        pipeline.reject  = AsyncMock(return_value=reject_result  or {"project_id": P1, "status": "rejected"})
    return pipeline


class TestApproveSecurityEndpoint:

    def test_approve_returns_202_shape(self):
        from app.routers.saas_factory import approve_security
        pipeline = _mock_pipeline()
        ctx = _make_ctx(org_id=ORG_A)
        with patch("app.routers.saas_factory.get_pipeline", return_value=pipeline):
            result = run(approve_security(project_id=P1, ctx=ctx))
        assert result["resumed_from"] == "DEPLOYING"
        pipeline.approve.assert_awaited_once_with(
            project_id=P1, org_id=ORG_A, reviewer_user_id=ctx.user_id
        )

    def test_approve_not_pending_review_raises_400(self):
        from fastapi import HTTPException
        from app.routers.saas_factory import approve_security
        pipeline = _mock_pipeline(side_effect=ValueError("Project is not awaiting security review (phase='LIVE')"))
        ctx = _make_ctx(org_id=ORG_A)
        with patch("app.routers.saas_factory.get_pipeline", return_value=pipeline):
            with pytest.raises(HTTPException) as exc_info:
                run(approve_security(project_id=P1, ctx=ctx))
        assert exc_info.value.status_code == 400
        assert "not awaiting" in exc_info.value.detail

    def test_approve_concurrent_conflict_raises_400(self):
        from fastapi import HTTPException
        from app.routers.saas_factory import approve_security
        pipeline = _mock_pipeline(side_effect=ValueError("Security review decision already recorded (concurrent approval or rejection)"))
        ctx = _make_ctx(org_id=ORG_A)
        with patch("app.routers.saas_factory.get_pipeline", return_value=pipeline):
            with pytest.raises(HTTPException) as exc_info:
                run(approve_security(project_id=P1, ctx=ctx))
        assert exc_info.value.status_code == 400
        assert "already recorded" in exc_info.value.detail

    def test_approve_uses_reviewer_user_id_from_ctx(self):
        """reviewer_user_id must come from OrgContext, never from request body."""
        from app.routers.saas_factory import approve_security
        pipeline = _mock_pipeline()
        ctx = _make_ctx(org_id=ORG_A)
        with patch("app.routers.saas_factory.get_pipeline", return_value=pipeline):
            run(approve_security(project_id=P1, ctx=ctx))
        call_kwargs = pipeline.approve.call_args.kwargs
        assert call_kwargs["reviewer_user_id"] == ctx.user_id
        assert call_kwargs["org_id"] == ORG_A


class TestRejectSecurityEndpoint:

    def test_reject_returns_202_shape(self):
        from app.routers.saas_factory import reject_security
        from app.routers.saas_factory import SecurityRejectRequest
        pipeline = _mock_pipeline()
        ctx = _make_ctx(org_id=ORG_A)
        body = SecurityRejectRequest(reason="Auth misconfiguration")
        with patch("app.routers.saas_factory.get_pipeline", return_value=pipeline):
            result = run(reject_security(project_id=P1, body=body, ctx=ctx))
        assert result["status"] == "rejected"
        pipeline.reject.assert_awaited_once_with(
            project_id=P1, org_id=ORG_A,
            reviewer_user_id=ctx.user_id, reason="Auth misconfiguration"
        )

    def test_reject_not_pending_review_raises_400(self):
        from fastapi import HTTPException
        from app.routers.saas_factory import reject_security, SecurityRejectRequest
        pipeline = _mock_pipeline(side_effect=ValueError("Project is not awaiting security review (phase='FAILED')"))
        ctx = _make_ctx(org_id=ORG_A)
        body = SecurityRejectRequest(reason="Too risky")
        with patch("app.routers.saas_factory.get_pipeline", return_value=pipeline):
            with pytest.raises(HTTPException) as exc_info:
                run(reject_security(project_id=P1, body=body, ctx=ctx))
        assert exc_info.value.status_code == 400

    def test_reject_concurrent_conflict_raises_400(self):
        from fastapi import HTTPException
        from app.routers.saas_factory import reject_security, SecurityRejectRequest
        pipeline = _mock_pipeline(side_effect=ValueError("Security review decision already recorded (concurrent approval or rejection)"))
        ctx = _make_ctx(org_id=ORG_A)
        body = SecurityRejectRequest(reason="")
        with patch("app.routers.saas_factory.get_pipeline", return_value=pipeline):
            with pytest.raises(HTTPException) as exc_info:
                run(reject_security(project_id=P1, body=body, ctx=ctx))
        assert exc_info.value.status_code == 400
        assert "already recorded" in exc_info.value.detail

    def test_reject_passes_reason_and_reviewer_from_ctx(self):
        """Both reason and reviewer_user_id must come from the correct sources."""
        from app.routers.saas_factory import reject_security, SecurityRejectRequest
        pipeline = _mock_pipeline()
        ctx = _make_ctx(org_id=ORG_A)
        body = SecurityRejectRequest(reason="Missing RBAC on admin routes")
        with patch("app.routers.saas_factory.get_pipeline", return_value=pipeline):
            run(reject_security(project_id=P1, body=body, ctx=ctx))
        call_kwargs = pipeline.reject.call_args.kwargs
        assert call_kwargs["reason"] == "Missing RBAC on admin routes"
        assert call_kwargs["reviewer_user_id"] == ctx.user_id
        assert call_kwargs["org_id"] == ORG_A

    def test_reject_empty_reason_is_accepted(self):
        """Backend allows empty reason — frontend label says optional."""
        from app.routers.saas_factory import reject_security, SecurityRejectRequest
        pipeline = _mock_pipeline()
        ctx = _make_ctx(org_id=ORG_A)
        body = SecurityRejectRequest(reason="")
        with patch("app.routers.saas_factory.get_pipeline", return_value=pipeline):
            result = run(reject_security(project_id=P1, body=body, ctx=ctx))
        assert result["status"] == "rejected"
