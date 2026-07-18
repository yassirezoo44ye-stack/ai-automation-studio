"""
Unit tests for pure-logic helper functions in main.py.
These tests run without a live database or any network calls.
All tests should be fast (< 1 second each).
"""
import base64
import hashlib
import hmac
import json
import time as _t
import uuid
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

import main  # safe after conftest.py sets DATABASE_URL


# ── Token helpers ──────────────────────────────────────────────────────────────

class TestTokenRoundtrip:
    def test_active_subscription_token(self):
        token = main._make_token("user@example.com", trial=False, days_remaining=0)
        payload = main._verify_token(token)
        assert payload is not None
        assert payload["e"] == "user@example.com"
        assert payload["trial"] is False
        assert payload["dr"] == 0

    def test_trial_token_preserves_days(self):
        token = main._make_token("trial@example.com", trial=True, days_remaining=5)
        payload = main._verify_token(token)
        assert payload is not None
        assert payload["trial"] is True
        assert payload["dr"] == 5

    def test_rejects_tampered_signature(self):
        token = main._make_token("user@example.com", trial=False, days_remaining=0)
        parts = token.rsplit(".", 1)
        tampered = parts[0] + "." + "a" * len(parts[1])
        assert main._verify_token(tampered) is None

    def test_rejects_truncated_token(self):
        assert main._verify_token("notavalidtoken") is None

    def test_rejects_empty_token(self):
        assert main._verify_token("") is None

    def test_rejects_expired_token(self):
        payload = {
            "e": "expired@test.com",
            "exp": int(_t.time()) - 3600,  # 1 hour in the past
            "trial": False,
            "dr": 0,
        }
        data = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
        sig = hmac.new(
            main.SESSION_SECRET.encode(), data.encode(), hashlib.sha256
        ).hexdigest()
        expired_token = f"{data}.{sig}"
        assert main._verify_token(expired_token) is None

    def test_token_has_correct_expiry_window(self):
        before = int(_t.time())
        token = main._make_token("x@x.com", trial=False, days_remaining=0)
        payload = main._verify_token(token)
        assert payload is not None
        expected_min = before + main._TOKEN_TTL - 2
        expected_max = before + main._TOKEN_TTL + 2
        assert expected_min <= payload["exp"] <= expected_max


# ── Project ID resolution ──────────────────────────────────────────────────────

class TestResolveProjectId:
    """
    resolve_project_id used to map "demo"/None to a single fixed UUID shared
    by every user — any account's default chat/build/design project was the
    same database row, so one user's "New Chat" surfaced every other user's
    conversation history. It now finds-or-creates the CALLER's own demo
    project and verifies ownership of any explicit project_id (H-03).
    """
    USER_A = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
    USER_B = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")

    async def test_demo_string_creates_a_project_owned_by_the_caller(self):
        conn = AsyncMock()
        new_id = uuid.uuid4()
        conn.fetchval = AsyncMock(side_effect=[None, new_id])  # no existing row, then INSERT RETURNING id
        result = await main._resolve_project_id(conn, "demo", self.USER_A)
        assert result == new_id
        insert_sql = conn.fetchval.call_args_list[1].args[0]
        assert "INSERT INTO projects" in insert_sql
        assert self.USER_A in conn.fetchval.call_args_list[1].args

    async def test_demo_string_reuses_the_callers_existing_demo_project(self):
        conn = AsyncMock()
        existing_id = uuid.uuid4()
        conn.fetchval = AsyncMock(return_value=existing_id)
        result = await main._resolve_project_id(conn, "demo", self.USER_A)
        assert result == existing_id
        assert conn.fetchval.call_count == 1  # found on first lookup, no INSERT

    async def test_none_behaves_like_demo(self):
        conn = AsyncMock()
        existing_id = uuid.uuid4()
        conn.fetchval = AsyncMock(return_value=existing_id)
        assert await main._resolve_project_id(conn, None, self.USER_A) == existing_id

    async def test_two_different_users_get_different_demo_projects(self):
        """The old bug: 'demo' resolved to ONE global UUID for everyone."""
        conn_a = AsyncMock()
        id_a = uuid.uuid4()
        conn_a.fetchval = AsyncMock(return_value=id_a)
        conn_b = AsyncMock()
        id_b = uuid.uuid4()
        conn_b.fetchval = AsyncMock(return_value=id_b)

        result_a = await main._resolve_project_id(conn_a, "demo", self.USER_A)
        result_b = await main._resolve_project_id(conn_b, "demo", self.USER_B)
        assert result_a != result_b
        # and each lookup was scoped to its own caller
        assert self.USER_A in conn_a.fetchval.call_args_list[0].args
        assert self.USER_B in conn_b.fetchval.call_args_list[0].args

    async def test_real_uuid_owned_by_caller_is_preserved(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=True)  # ownership check passes
        real = "12345678-1234-1234-1234-123456789abc"
        result = await main._resolve_project_id(conn, real, self.USER_A)
        assert str(result) == real

    async def test_real_uuid_not_owned_by_caller_raises_404(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=None)  # ownership check fails
        real = "12345678-1234-1234-1234-123456789abc"
        with pytest.raises(HTTPException) as exc_info:
            await main._resolve_project_id(conn, real, self.USER_A)
        assert exc_info.value.status_code == 404

    async def test_invalid_uuid_raises(self):
        conn = AsyncMock()
        with pytest.raises((ValueError, Exception)):
            await main._resolve_project_id(conn, "not-a-uuid", self.USER_A)


# ── Rate limiter ───────────────────────────────────────────────────────────────

class TestRateLimit:
    def _fresh_key(self):
        return f"test:{uuid.uuid4()}"

    def test_allows_requests_under_limit(self):
        key = self._fresh_key()
        for _ in range(9):
            assert main._check_rate_limit(key, max_calls=10, window=60) is True

    def test_blocks_exactly_at_limit(self):
        key = self._fresh_key()
        for _ in range(10):
            main._check_rate_limit(key, max_calls=10, window=60)
        assert main._check_rate_limit(key, max_calls=10, window=60) is False

    def test_different_keys_are_independent(self):
        k1, k2 = self._fresh_key(), self._fresh_key()
        for _ in range(10):
            main._check_rate_limit(k1, max_calls=10, window=60)
        # k2 should not be affected by k1 being exhausted
        assert main._check_rate_limit(k2, max_calls=10, window=60) is True

    def test_window_expiry_resets_count(self):
        key = self._fresh_key()
        # Manually inject old timestamps into the rate-limit store
        now = _t.time()
        main._rl_store[key] = [now - 120] * 10  # 10 entries from 2 minutes ago
        # With a 60-second window those entries should be purged, allowing new calls
        assert main._check_rate_limit(key, max_calls=10, window=60) is True


# ── Anthropic error message extraction ────────────────────────────────────────

class TestAnthropicErrorMessage:
    def test_extracts_from_dict_body(self):
        class Err:
            body = {"error": {"message": "Input is too long"}}
        assert main._anthropic_error_message(Err()) == "Input is too long"

    def test_handles_missing_message_key(self):
        class Err:
            body = {"error": {}}
            def __str__(self): return "fallback"
        result = main._anthropic_error_message(Err())
        assert "fallback" in result

    def test_handles_non_dict_body(self):
        class Err:
            body = "raw error string"
            def __str__(self): return "raw error string"
        assert main._anthropic_error_message(Err()) == "raw error string"

    def test_handles_none_body(self):
        class Err:
            body = None
            def __str__(self): return "no body"
        result = main._anthropic_error_message(Err())
        assert "no body" in result

    def test_handles_missing_body_attr(self):
        class Err:
            def __str__(self): return "no attr"
        result = main._anthropic_error_message(Err())
        assert "no attr" in result


# ── App name sanitizer ─────────────────────────────────────────────────────────

class TestSanitize:
    def test_strips_special_characters(self):
        assert main._sanitize("My App 2.0!") == "My_App_2_0_"

    def test_allows_alphanumeric_hyphen_underscore(self):
        assert main._sanitize("MyApp_1-0") == "MyApp_1-0"

    def test_empty_string_returns_fallback(self):
        assert main._sanitize("") == "App"

    def test_all_special_chars_become_underscores(self):
        # Special chars are replaced with _, not empty — "App" fallback is for truly empty input
        assert main._sanitize("!@#$%") == "_____"

    def test_empty_after_strip_returns_fallback(self):
        # The regex replaces everything, so only a genuinely empty input hits the fallback
        assert main._sanitize("") == "App"


# ── next_due_date (recurring task scheduling) ──────────────────────────────────

class TestNextDueDate:
    from datetime import datetime, timezone

    def _dt(self, iso: str):
        from datetime import datetime
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))

    def test_daily_adds_one_day(self):
        due = self._dt("2026-07-01T09:00:00Z")
        nxt = main._next_due_date(due, "daily")
        assert nxt is not None
        assert nxt.day == 2 and nxt.month == 7

    def test_weekly_adds_seven_days(self):
        due = self._dt("2026-07-01T09:00:00Z")
        nxt = main._next_due_date(due, "weekly")
        assert nxt is not None
        assert nxt.day == 8 and nxt.month == 7

    def test_monthly_advances_month(self):
        due = self._dt("2026-07-15T09:00:00Z")
        nxt = main._next_due_date(due, "monthly")
        assert nxt is not None
        assert nxt.month == 8 and nxt.day == 15

    def test_monthly_caps_day_at_28_for_safety(self):
        # Day 31 in July → day 28 in Feb (28 is the safe cap)
        due = self._dt("2026-07-31T09:00:00Z")
        nxt = main._next_due_date(due, "monthly")
        assert nxt is not None
        assert nxt.day == 28

    def test_monthly_wraps_december_to_january(self):
        due = self._dt("2026-12-01T09:00:00Z")
        nxt = main._next_due_date(due, "monthly")
        assert nxt is not None
        assert nxt.month == 1 and nxt.year == 2027

    def test_none_recurrence_returns_none(self):
        due = self._dt("2026-07-01T09:00:00Z")
        assert main._next_due_date(due, "none") is None

    def test_none_due_date_returns_none(self):
        assert main._next_due_date(None, "weekly") is None


# ── owner_email helper ─────────────────────────────────────────────────────────

class TestOwnerEmail:
    def _make_request(self, headers: dict, cookies: dict = None):
        """Minimal request mock — only attributes _owner_email uses."""
        class FakeRequest:
            def __init__(self):
                self.headers = headers
                self.cookies = cookies or {}
                self.client = None
        return FakeRequest()

    def test_extracts_from_x_sub_token_header(self):
        token = main._make_token("header@test.com", False, 0)
        req = self._make_request({"X-Sub-Token": token})
        assert main._owner_email(req) == "header@test.com"

    def test_extracts_from_bearer_authorization(self):
        token = main._make_token("bearer@test.com", False, 0)
        req = self._make_request({"Authorization": f"Bearer {token}"})
        assert main._owner_email(req) == "bearer@test.com"

    def test_extracts_from_cookie(self):
        token = main._make_token("cookie@test.com", False, 0)
        req = self._make_request({}, {"sub_token": token})
        assert main._owner_email(req) == "cookie@test.com"

    def test_falls_back_to_demo_when_no_token(self):
        req = self._make_request({})
        assert main._owner_email(req) == "demo@local"

    def test_falls_back_to_demo_on_invalid_token(self):
        req = self._make_request({"X-Sub-Token": "garbage.token"})
        assert main._owner_email(req) == "demo@local"
