"""
Settings audit, milestone 2: the "ai" API-key scope, invitation role
ceiling, MFA re-authentication, and admin-only cross-tenant views.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pyotp
import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

import app.core.api_keys as api_keys_mod
from app.core.api_keys import VALID_SCOPES, ApiKeyRecord
from app.core.auth import make_token

USER_ID = str(uuid.uuid4())


# ── Fakes ─────────────────────────────────────────────────────────────────────

class FakeConn:
    def __init__(self, *, rows=None, val=None):
        self.rows = rows or {}
        self.val = val
        self.executed: list[str] = []

    async def fetchrow(self, sql, *args):
        for key, row in self.rows.items():
            if key in sql:
                return row
        return None

    async def fetchval(self, sql, *args):
        return self.val

    async def execute(self, sql, *args):
        self.executed.append(sql)
        return "OK"


class FakePool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        conn = self.conn

        class _Ctx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *exc):
                return False
        return _Ctx()


def _key(scopes, owner=USER_ID, org=None) -> ApiKeyRecord:
    return ApiKeyRecord(
        key_id="k1", key_hash="h", name="k", scopes=scopes,
        owner_id=owner, organization_id=org,
    )


def _req(key=None):
    return SimpleNamespace(state=SimpleNamespace(api_key=key) if key else SimpleNamespace(), headers={})


# ── "ai" scope ────────────────────────────────────────────────────────────────

def test_ai_scope_is_valid():
    assert "ai" in VALID_SCOPES


async def test_ai_key_acts_as_owner(monkeypatch):
    from app.routers import inference
    monkeypatch.setattr(inference, "get_pool", lambda: FakePool(FakeConn(val=uuid.UUID(USER_ID))))
    assert await inference._user_id(_req(_key(["ai"]))) == USER_ID


@pytest.mark.parametrize("scopes", [["read"], ["write"], ["agents"]])
async def test_non_ai_key_rejected_on_ai_routes(scopes):
    from app.routers import inference
    with pytest.raises(HTTPException) as exc:
        await inference._user_id(_req(_key(scopes)))
    assert exc.value.status_code == 403


async def test_ai_key_for_deleted_owner_rejected(monkeypatch):
    from app.routers import inference
    monkeypatch.setattr(inference, "get_pool", lambda: FakePool(FakeConn(val=None)))
    with pytest.raises(HTTPException) as exc:
        await inference._user_id(_req(_key(["ai"])))
    assert exc.value.status_code == 401


async def test_ai_key_bills_its_own_org():
    from app.routers import inference
    org = str(uuid.uuid4())
    assert await inference._org_id(_req(_key(["ai"], org=org))) == org
    assert await inference._org_id(_req(_key(["ai"]))) is None


# ── Invitation role ceiling ───────────────────────────────────────────────────

@pytest.mark.parametrize("actor,role,allowed", [
    ("manager", "admin", False),
    ("manager", "manager", True),
    ("manager", "developer", True),
    ("admin", "admin", True),
])
async def test_invite_cannot_exceed_own_role(monkeypatch, actor, role, allowed):
    from app.tenancy.service import TenancyError, TenancyService
    svc = TenancyService(pool=None)

    async def _role(org_id, user_id):
        return actor

    class _Reached(Exception):
        pass

    async def _seats(org_id):
        raise _Reached()

    monkeypatch.setattr(svc, "get_member_role", _role)
    monkeypatch.setattr(svc, "_check_seat_capacity", _seats)
    with pytest.raises(_Reached if allowed else TenancyError):
        await svc.create_invitation(str(uuid.uuid4()), actor_id=USER_ID, email="x@example.com", role=role)


# ── MFA re-authentication ─────────────────────────────────────────────────────

SECRET = pyotp.random_base32()


def _mfa_conn(password_hash):
    return FakeConn(rows={
        "FROM mfa_secrets": {"secret": SECRET, "enabled": True},
        "FROM users": {"id": uuid.UUID(USER_ID), "password_hash": password_hash},
    })


@pytest.fixture
def auth_users(monkeypatch):
    from app.routers import auth_users as mod

    async def _noop(*a, **k):
        return None
    monkeypatch.setattr(mod, "write_audit", _noop)
    return mod


async def test_backup_codes_require_valid_totp(monkeypatch, auth_users):
    conn = _mfa_conn(None)
    monkeypatch.setattr(auth_users, "get_pool", lambda: FakePool(conn))
    current = {"id": USER_ID, "email": "u@example.com"}
    with pytest.raises(HTTPException):
        await auth_users.mfa_regenerate_backup_codes(auth_users.MfaBackupCodesRequest(code="000000"), current)
    out = await auth_users.mfa_regenerate_backup_codes(
        auth_users.MfaBackupCodesRequest(code=pyotp.TOTP(SECRET).now()), current,
    )
    assert len(out["backup_codes"]) == 10


async def test_mfa_disable_requires_totp_even_with_password(monkeypatch, auth_users):
    pw_hash = auth_users.hash_password("correct horse")
    monkeypatch.setattr(auth_users, "get_pool", lambda: FakePool(_mfa_conn(pw_hash)))
    current = {"id": USER_ID, "email": "u@example.com"}
    with pytest.raises(HTTPException):
        await auth_users.mfa_disable(auth_users.MfaDisableRequest(code="000000", password="correct horse"), current)
    with pytest.raises(HTTPException):
        await auth_users.mfa_disable(
            auth_users.MfaDisableRequest(code=pyotp.TOTP(SECRET).now(), password="wrong"), current,
        )
    out = await auth_users.mfa_disable(
        auth_users.MfaDisableRequest(code=pyotp.TOTP(SECRET).now(), password="correct horse"), current,
    )
    assert out == {"enabled": False}


async def test_oauth_only_account_can_disable_mfa_with_totp(monkeypatch, auth_users):
    monkeypatch.setattr(auth_users, "get_pool", lambda: FakePool(_mfa_conn(None)))
    out = await auth_users.mfa_disable(
        auth_users.MfaDisableRequest(code=pyotp.TOTP(SECRET).now()),
        {"id": USER_ID, "email": "u@example.com"},
    )
    assert out == {"enabled": False}


async def test_revoke_session_bad_id_is_404(auth_users):
    with pytest.raises(HTTPException) as exc:
        await auth_users.revoke_session("not-a-uuid", {"id": USER_ID, "email": "u@example.com"})
    assert exc.value.status_code == 404


# ── Admin-only cross-tenant views ─────────────────────────────────────────────

@pytest.fixture(scope="module")
def app():
    from app.factory import create_app
    return create_app()


@pytest.fixture
async def client(app, monkeypatch):
    monkeypatch.setattr("app.core.config.ADMIN_EMAILS", frozenset({"boss@example.com"}))

    async def _lookup(raw):
        return None
    monkeypatch.setattr(api_keys_mod, "lookup_key", _lookup)
    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False),
                           base_url="http://test") as c:
        yield c


def _session(email):
    return {"X-Sub-Token": make_token(email, trial=False, days_remaining=30)}


@pytest.mark.parametrize("path", ["/api/diagnostics/traces", "/api/diagnostics/traces/active"])
async def test_traces_admin_only(client, path):
    assert (await client.get(path, headers=_session("someone@example.com"))).status_code == 403
    assert (await client.get(path, headers=_session("boss@example.com"))).status_code == 200


async def test_platform_wide_cost_summary_admin_only(client):
    res = await client.get("/api/ai/cost/summary", headers=_session("someone@example.com"))
    assert res.status_code == 403


async def test_no_org_agent_memory_hidden_from_non_admin(client, monkeypatch):
    import app.agents.memory as agent_memory

    def _boom():
        raise AssertionError("shared no-org bucket must not be read")
    monkeypatch.setattr(agent_memory, "get_memory", _boom)
    res = await client.get("/api/agentos/memory", headers=_session("someone@example.com"))
    assert res.status_code == 200
    assert res.json() == {"count": 0, "records": []}


async def test_no_org_layered_memory_hidden_from_non_admin(client, monkeypatch):
    import app.memory.layered as layered

    class _Mem:
        stats = {}

        def recent(self, *a, **k):
            raise AssertionError("shared no-org bucket must not be read")

        def search(self, *a, **k):
            raise AssertionError("shared no-org bucket must not be read")
    monkeypatch.setattr(layered, "get_layered_memory", lambda: _Mem())
    res = await client.get("/api/diagnostics/memory", headers=_session("someone@example.com"))
    assert res.status_code == 200 and res.json()["records"] == []
    res = await client.post("/api/diagnostics/memory/search", json={"query": "x"},
                            headers=_session("someone@example.com"))
    assert res.status_code == 200 and res.json()["results"] == []
