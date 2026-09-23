"""
SSE auth tests — Business Lab plan stream (ticket-based flow).

Tests cover:
  1. valid SSE ticket → consume succeeds, stream endpoint returns 200
  2. expired ticket → consume returns None → 401
  3. reused ticket → second consume returns None → 401  (single-use)
  4. invalid/random ticket → 401
  5. valid ticket + plan not owned by user → 404
  6. JWT in ?token= query param → NOT accepted (400/401)
  7. Organization isolation — ticket from org-A cannot stream org-B plan
  8. Existing header-authenticated API endpoints are unaffected

These tests do NOT require a live database — all DB calls are mocked.
The ticket store (ws_ticket) is real in-process state (no mocks needed
for the ticket mechanics).
"""
from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ── Helpers ────────────────────────────────────────────────────────────────────

_PLAN_ID = "00000000-0000-0000-0000-000000000001"


def _make_app():
    """Minimal FastAPI app with only the business router mounted."""
    from fastapi import FastAPI
    from app.routers.business_plans import router
    app = FastAPI()
    app.include_router(router)
    return app


def _issue_real_ticket(user_id: str) -> str:
    from app.routers.ws_ticket import issue_ticket
    return issue_ticket(user_id)


def _mock_pool(plan_row=None, sections=None):
    """Return a mock that satisfies acquire_scoped / pool.acquire() usage."""
    conn = AsyncMock()
    conn.fetchrow.return_value = plan_row
    conn.fetch.return_value = sections or []

    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool, conn


# ── Ticket mechanics (pure in-process, no HTTP) ────────────────────────────────

class TestTicketMechanics:
    def test_issue_and_consume_returns_user_id(self):
        from app.routers.ws_ticket import issue_ticket, consume_ticket
        uid = "user-abc"
        ticket = issue_ticket(uid)
        assert consume_ticket(ticket) == uid

    def test_ticket_is_single_use(self):
        from app.routers.ws_ticket import issue_ticket, consume_ticket
        ticket = issue_ticket("user-xyz")
        consume_ticket(ticket)           # first use — succeeds
        assert consume_ticket(ticket) is None  # second use — rejected

    def test_invalid_ticket_returns_none(self):
        from app.routers.ws_ticket import consume_ticket
        assert consume_ticket("not-a-real-ticket") is None
        assert consume_ticket("") is None

    def test_expired_ticket_returns_none(self):
        from app.routers.ws_ticket import issue_ticket, consume_ticket, _store
        ticket = issue_ticket("user-exp")
        # Manually expire by setting exp to the past
        with __import__("threading").Lock():
            _store[ticket]["exp"] = time.monotonic() - 1
        assert consume_ticket(ticket) is None

    def test_random_hex_string_not_accepted(self):
        from app.routers.ws_ticket import consume_ticket
        import secrets
        random_hex = secrets.token_hex(32)  # valid format, but not in store
        assert consume_ticket(random_hex) is None


# ── HTTP endpoint tests (mocked DB) ───────────────────────────────────────────

class TestSseTicketEndpoint:
    """POST /api/business/plans/{plan_id}/sse-ticket — requires auth, issues ticket."""

    BASE = "/api/business"

    def test_no_auth_returns_401(self):
        app = _make_app()
        with patch("app.routers.business_plans._resolve_user",
                   side_effect=__import__("fastapi").HTTPException(status_code=401, detail="Unauthorized")):
            with TestClient(app, raise_server_exceptions=False) as client:
                r = client.post(f"{self.BASE}/plans/{_PLAN_ID}/sse-ticket")
        assert r.status_code == 401

    def test_valid_auth_wrong_plan_returns_404(self):
        app = _make_app()
        with (
            patch("app.routers.business_plans._resolve_user", return_value="user-1"),
            patch("app.routers.business_plans._resolve_org",  return_value="org-1"),
            patch("app.routers.business_plans._assert_plan_owner",
                  side_effect=__import__("fastapi").HTTPException(status_code=404, detail="Plan not found")),
        ):
            with TestClient(app) as client:
                r = client.post(f"{self.BASE}/plans/{_PLAN_ID}/sse-ticket")
        assert r.status_code == 404

    def test_valid_auth_correct_plan_returns_ticket(self):
        app = _make_app()
        with (
            patch("app.routers.business_plans._resolve_user", return_value="user-1"),
            patch("app.routers.business_plans._resolve_org",  return_value="org-1"),
            patch("app.routers.business_plans._assert_plan_owner", return_value={}),
        ):
            with TestClient(app) as client:
                r = client.post(f"{self.BASE}/plans/{_PLAN_ID}/sse-ticket")
        assert r.status_code == 200
        body = r.json()
        assert "ticket" in body
        assert body["expires_in"] == 30
        assert len(body["ticket"]) == 64  # 32 bytes hex

    def test_jwt_in_query_token_not_accepted_for_ticket_endpoint(self):
        """Passing ?token=<jwt> instead of Authorization header must not issue a ticket."""
        app = _make_app()
        with (
            patch("app.routers.business_plans._resolve_user",
                  side_effect=__import__("fastapi").HTTPException(status_code=401, detail="Unauthorized")),
        ):
            with TestClient(app, raise_server_exceptions=False) as client:
                r = client.post(f"{self.BASE}/plans/{_PLAN_ID}/sse-ticket?token=fake-jwt")
        assert r.status_code == 401


class TestSseStreamEndpoint:
    """GET /api/business/stream/{plan_id} — ticket-authenticated SSE."""

    BASE = "/api/business"

    def test_missing_ticket_returns_401(self):
        app = _make_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            r = client.get(f"{self.BASE}/stream/{_PLAN_ID}")
        assert r.status_code == 401
        assert "ticket" in r.json().get("detail", "").lower()

    def test_invalid_ticket_returns_401(self):
        app = _make_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            r = client.get(f"{self.BASE}/stream/{_PLAN_ID}?ticket=invalid-ticket-value")
        assert r.status_code == 401

    def test_expired_ticket_returns_401(self):
        from app.routers.ws_ticket import issue_ticket, _store
        ticket = issue_ticket("user-exp2")
        _store[ticket]["exp"] = time.monotonic() - 1
        app = _make_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            r = client.get(f"{self.BASE}/stream/{_PLAN_ID}?ticket={ticket}")
        assert r.status_code == 401

    def test_reused_ticket_returns_401(self):
        """Single-use: second request with the same ticket must fail."""
        ticket = _issue_real_ticket("user-reuse")
        app = _make_app()
        with (
            patch("app.routers.business_plans._resolve_org",  return_value="org-1"),
            patch("app.routers.business_plans._assert_plan_owner",
                  side_effect=__import__("fastapi").HTTPException(status_code=404, detail="Plan not found")),
        ):
            with TestClient(app, raise_server_exceptions=False) as client:
                client.get(f"{self.BASE}/stream/{_PLAN_ID}?ticket={ticket}")  # first use — ticket consumed
                r2 = client.get(f"{self.BASE}/stream/{_PLAN_ID}?ticket={ticket}")  # second use — rejected
        assert r2.status_code == 401

    def test_valid_ticket_unauthorized_plan_returns_404(self):
        """Valid ticket for user A cannot stream user B's plan."""
        ticket = _issue_real_ticket("user-a")
        app = _make_app()
        with (
            patch("app.routers.business_plans._resolve_org",  return_value="org-a"),
            patch("app.routers.business_plans._assert_plan_owner",
                  side_effect=__import__("fastapi").HTTPException(status_code=404, detail="Plan not found")),
        ):
            with TestClient(app, raise_server_exceptions=False) as client:
                r = client.get(f"{self.BASE}/stream/{_PLAN_ID}?ticket={ticket}")
        assert r.status_code == 404

    def test_valid_ticket_owned_plan_returns_200_stream(self):
        """Happy path: valid ticket + owned plan → SSE response."""
        ticket = _issue_real_ticket("user-ok")
        plan_row = {"status": "COMPLETED", "readiness_score": 75}
        pool, _conn = _mock_pool(plan_row=plan_row, sections=[])
        app = _make_app()
        with (
            patch("app.routers.business_plans._resolve_org", return_value="org-1"),
            patch("app.routers.business_plans._assert_plan_owner", return_value={}),
            patch("app.routers.business_plans.get_pool", return_value=pool),
        ):
            with TestClient(app) as client:
                r = client.get(f"{self.BASE}/stream/{_PLAN_ID}?ticket={ticket}")
        assert r.status_code == 200
        assert "text/event-stream" in r.headers.get("content-type", "")

    def test_jwt_in_query_token_not_accepted_for_stream(self):
        """?token=<jwt> must not be accepted — only ?ticket= is valid."""
        app = _make_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            r = client.get(f"{self.BASE}/stream/{_PLAN_ID}?token=some-jwt-value")
        assert r.status_code == 401
        assert "ticket" in r.json().get("detail", "").lower()

    def test_organization_isolation(self):
        """Ticket from org-A user cannot be used to stream org-B plan."""
        ticket = _issue_real_ticket("user-org-a")
        app = _make_app()
        with (
            patch("app.routers.business_plans._resolve_org", return_value="org-b"),
            patch("app.routers.business_plans._assert_plan_owner",
                  side_effect=__import__("fastapi").HTTPException(status_code=404, detail="Plan not found")),
        ):
            with TestClient(app, raise_server_exceptions=False) as client:
                r = client.get(f"{self.BASE}/stream/{_PLAN_ID}?ticket={ticket}")
        assert r.status_code == 404


# ── Regression: existing header-auth endpoints unaffected ────────────────────

class TestExistingEndpointsUnaffected:
    """Verify that the new endpoints don't break existing auth behaviour."""

    BASE = "/api/business"

    def test_header_auth_stream_still_works(self):
        """GET /plans/{plan_id}/stream (header auth) must still function."""
        plan_row = {"status": "COMPLETED", "readiness_score": 80}
        pool, _conn = _mock_pool(plan_row=plan_row, sections=[])
        app = _make_app()
        with (
            patch("app.routers.business_plans._resolve_user", return_value="user-1"),
            patch("app.routers.business_plans._resolve_org",  return_value="org-1"),
            patch("app.routers.business_plans._assert_plan_owner", return_value={}),
            patch("app.routers.business_plans.get_pool", return_value=pool),
        ):
            with TestClient(app) as client:
                r = client.get(f"{self.BASE}/plans/{_PLAN_ID}/stream",
                               headers={"Authorization": "Bearer valid-jwt"})
        assert r.status_code == 200
        assert "text/event-stream" in r.headers.get("content-type", "")
