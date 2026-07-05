"""
Unit tests for the auth module (app.core.auth).
Runs without a live database.
"""
import time as _time

import pytest

from app.core.auth import make_token, verify_token, owner_email


class TestMakeVerify:
    def test_roundtrip(self):
        tok = make_token("alice@example.com", trial=False, days_remaining=0)
        payload = verify_token(tok)
        assert payload is not None
        assert payload["e"] == "alice@example.com"
        assert payload["trial"] is False

    def test_trial_preserved(self):
        tok = make_token("bob@example.com", trial=True, days_remaining=7)
        payload = verify_token(tok)
        assert payload["trial"] is True
        assert payload["dr"] == 7

    def test_tampered_sig_rejected(self):
        tok = make_token("alice@example.com", trial=False, days_remaining=0)
        data, _ = tok.rsplit(".", 1)
        assert verify_token(data + ".badsig") is None

    def test_expired_token_rejected(self):
        import base64, json, hashlib, hmac
        from app.core.config import SESSION_SECRET
        payload = {"e": "x@x.com", "exp": int(_time.time()) - 1, "trial": False, "dr": 0}
        data = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
        sig  = hmac.new(SESSION_SECRET.encode(), data.encode(), hashlib.sha256).hexdigest()
        assert verify_token(f"{data}.{sig}") is None

    def test_garbage_token_rejected(self):
        assert verify_token("not.a.real.token") is None

    def test_empty_string_rejected(self):
        assert verify_token("") is None


class TestOwnerEmail:
    class _Req:
        def __init__(self, headers, cookies=None):
            self.headers = headers
            self.cookies = cookies or {}
            self.client  = None

    def test_x_sub_token_header(self):
        tok = make_token("a@b.com", False, 0)
        req = self._Req({"X-Sub-Token": tok})
        assert owner_email(req) == "a@b.com"

    def test_bearer_auth_header(self):
        tok = make_token("c@d.com", False, 0)
        req = self._Req({"Authorization": f"Bearer {tok}"})
        assert owner_email(req) == "c@d.com"

    def test_cookie(self):
        tok = make_token("e@f.com", False, 0)
        req = self._Req({}, {"sub_token": tok})
        assert owner_email(req) == "e@f.com"

    def test_no_token_returns_demo(self):
        req = self._Req({})
        assert owner_email(req) == "demo@local"

    def test_invalid_token_returns_demo(self):
        req = self._Req({"X-Sub-Token": "garbage.stuff"})
        assert owner_email(req) == "demo@local"
