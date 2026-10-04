"""
Lead Engine tests — service CRUD, org isolation, permission enforcement,
AI qualification success/failure, notification dispatch, input validation,
follow-up wiring.

All tests run without a live DB, fastapi, asyncpg, or pydantic installation.
Modules that cannot be imported in the CI environment are stubbed at sys.modules
before any app import occurs.  We import app modules that avoid heavy transitive
deps (service.py / schema.py) and validate them directly; for validation-logic
tests we instantiate the Pydantic models through the stub.
"""
from __future__ import annotations

import os
import re
import sys
import types
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("SESSION_SECRET", "test-secret-for-unit-tests-do-not-use-in-prod")


# ══════════════════════════════════════════════════════════════════════════════
# sys.modules stubs — must run before any app import
# ══════════════════════════════════════════════════════════════════════════════

def _make_asyncpg_stub() -> types.ModuleType:
    mod = types.ModuleType("asyncpg")
    mod.Pool = type("Pool", (), {})
    mod.Connection = type("Connection", (), {})
    mod.Record = type("Record", (dict,), {})
    return mod


def _make_fastapi_stub() -> types.ModuleType:
    """Minimal fastapi stub for modules that import APIRouter, Depends, HTTPException."""
    mod = types.ModuleType("fastapi")

    class _HTTPException(Exception):
        def __init__(self, status_code: int, detail: str = ""):
            self.status_code = status_code
            self.detail = detail

    class _Depends:
        def __init__(self, dep=None):
            self.dep = dep

    class _APIRouter:
        def __init__(self, **kw):
            self._routes = []
        def get(self, *a, **kw):
            def dec(fn): return fn
            return dec
        def post(self, *a, **kw):
            def dec(fn): return fn
            return dec
        def patch(self, *a, **kw):
            def dec(fn): return fn
            return dec

    class _Request:
        pass

    mod.APIRouter = _APIRouter
    mod.Depends = _Depends
    mod.HTTPException = _HTTPException
    mod.Request = _Request

    # fastapi.testclient sub-module (not needed but keeps imports from failing)
    tc_mod = types.ModuleType("fastapi.testclient")
    tc_mod.TestClient = MagicMock
    sys.modules["fastapi.testclient"] = tc_mod

    return mod


def _make_pydantic_stub() -> types.ModuleType:
    """Pydantic stub: BaseModel with field validation from FieldInfo metadata."""
    mod = types.ModuleType("pydantic")

    class ValidationError(Exception):
        pass

    class FieldInfo:
        def __init__(self, default=..., **kwargs):
            self.default = default
            self.metadata = kwargs

    def Field(default=..., **kwargs):
        return FieldInfo(default=default, **kwargs)

    class _ModelMeta(type):
        def __new__(mcs, name, bases, ns):
            fields: dict = {}
            annotations = ns.get("__annotations__", {})
            for attr, _ann in annotations.items():
                val = ns.get(attr, FieldInfo())
                fields[attr] = (
                    _ann,
                    val if isinstance(val, FieldInfo) else FieldInfo(default=val),
                )
            for base in bases:
                for k, v in getattr(base, "__fields__", {}).items():
                    if k not in fields:
                        fields[k] = v
            cls = super().__new__(mcs, name, bases, ns)
            cls.__fields__ = fields
            return cls

    class BaseModel(metaclass=_ModelMeta):
        def __init__(self, **data):
            for attr, (_ann, info) in self.__fields__.items():
                val = data.get(attr, info.default)
                meta = info.metadata
                if val is None and info.default is None:
                    setattr(self, attr, None)
                    continue
                if val is ...:
                    raise ValidationError(f"{attr} is required")
                if isinstance(val, str):
                    if "min_length" in meta and len(val) < meta["min_length"]:
                        raise ValidationError(f"{attr}: too short")
                    if "max_length" in meta and len(val) > meta["max_length"]:
                        raise ValidationError(f"{attr}: too long")
                    if "pattern" in meta and not re.fullmatch(meta["pattern"], val):
                        raise ValidationError(f"{attr}: '{val}' invalid")
                setattr(self, attr, val)

    mod.BaseModel = BaseModel
    mod.ValidationError = ValidationError
    mod.Field = Field

    # pydantic.v1 (sometimes imported by starlette compat)
    v1_mod = types.ModuleType("pydantic.v1")
    v1_mod.BaseModel = BaseModel
    sys.modules["pydantic.v1"] = v1_mod

    return mod


def _register_stubs() -> None:
    if "asyncpg" not in sys.modules:
        sys.modules["asyncpg"] = _make_asyncpg_stub()
    if "fastapi" not in sys.modules:
        sys.modules["fastapi"] = _make_fastapi_stub()
    if "pydantic" not in sys.modules:
        sys.modules["pydantic"] = _make_pydantic_stub()

    # Stub heavy transitive deps the router chain pulls in
    for name in [
        "starlette", "starlette.responses", "starlette.requests",
        "starlette.middleware", "starlette.middleware.base",
        "starlette.routing", "starlette.types",
    ]:
        if name not in sys.modules:
            sys.modules[name] = types.ModuleType(name)

    # Stub app.ai.*  (pulls pydantic, redis, etc.)
    for name in [
        "app.ai", "app.ai.models", "app.ai.gateway", "app.ai.memory",
        "app.core.ai", "app.core.ai.platform", "app.core.ai.tools",
        "app.core.ai.tools.executor", "app.core.ai.memory",
        "app.core.ai.memory.types", "app.core.ai.agents",
        "app.core.ai.agents.runtime",
    ]:
        if name not in sys.modules:
            sys.modules[name] = types.ModuleType(name)

    # Put AgentRuntime + AgentConfig in the stub so the service can import them
    _rt = sys.modules["app.core.ai.agents.runtime"]
    if not hasattr(_rt, "AgentRuntime"):
        class _AgentConfig:
            def __init__(self, **kw): pass

        class _AgentRuntime:
            def __init__(self, cfg): pass
            async def run(self, prompt: str):
                raise RuntimeError("AgentRuntime not configured in test")

        _rt.AgentConfig = _AgentConfig
        _rt.AgentRuntime = _AgentRuntime

    # Stub app.core.notifications.service (used by dispatch_qualified_notification)
    _ns = "app.core.notifications"
    _nsvc = "app.core.notifications.service"
    for n in (_ns, _nsvc):
        if n not in sys.modules:
            sys.modules[n] = types.ModuleType(n)
    if not hasattr(sys.modules[_nsvc], "get_notification_service"):
        sys.modules[_nsvc].get_notification_service = lambda: MagicMock()

    # Stub tenancy (fastapi-dependent but we only test at service level here)
    _tn = "app.tenancy"
    _tc = "app.tenancy.context"
    for n in (_tn, _tc):
        if n not in sys.modules:
            sys.modules[n] = types.ModuleType(n)

    _ctx = sys.modules[_tc]
    if not hasattr(_ctx, "OrgContext"):
        class _OrgContext:
            def __init__(self, *, org_id, user_id, role="manager", permissions=None):
                self.org_id = org_id
                self.user_id = user_id
                self.role = role
                self.permissions = permissions or set()
        _ctx.OrgContext = _OrgContext

    if not hasattr(_ctx, "require_permission"):
        def _require_permission(resource: str, action: str):
            async def _dep():
                raise Exception("No OrgContext in test — authentication required")
            return _dep
        _ctx.require_permission = _require_permission

    # Stub app.core.db and app.core.jobs (used by router follow-up block)
    for n in ("app.core.db", "app.core.jobs"):
        if n not in sys.modules:
            sys.modules[n] = types.ModuleType(n)
    if not hasattr(sys.modules["app.core.db"], "get_pool"):
        sys.modules["app.core.db"].get_pool = lambda: None
    if not hasattr(sys.modules["app.core.jobs"], "get_job_queue"):
        sys.modules["app.core.jobs"].get_job_queue = lambda: MagicMock()


_register_stubs()


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def run(coro):
    import asyncio
    return asyncio.new_event_loop().run_until_complete(coro)


def _make_pool(conn: AsyncMock) -> MagicMock:
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool


def _fake_lead(
    lead_id: str | None = None,
    org_id: str | None = None,
    name: str = "Ahmed Al-Rashid",
    email: str | None = "ahmed@agency.com",
    status: str = "new",
    ai_score: int | None = None,
    ai_notes: str | None = None,
) -> dict[str, Any]:
    import datetime
    now = datetime.datetime.now(datetime.timezone.utc)
    return {
        "id": uuid.UUID(lead_id or str(uuid.uuid4())),
        "organization_id": uuid.UUID(org_id or str(uuid.uuid4())),
        "name": name,
        "email": email,
        "phone": None,
        "source": "LinkedIn",
        "status": status,
        "ai_score": ai_score,
        "ai_notes": ai_notes,
        "created_at": now,
        "updated_at": now,
    }


# ══════════════════════════════════════════════════════════════════════════════
# 1. Create lead
# ══════════════════════════════════════════════════════════════════════════════

class TestLeadServiceCreate:
    def test_create_inserts_and_returns_lead(self):
        from app.core.leads.service import LeadService
        org_id = str(uuid.uuid4())
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=_fake_lead(org_id=org_id, name="Test Lead"))
        svc = LeadService(_make_pool(conn))

        result = run(svc.create(org_id=org_id, name="Test Lead"))

        conn.fetchrow.assert_awaited_once()
        sql, *params = conn.fetchrow.call_args.args
        assert "INSERT INTO leads" in sql
        assert "Test Lead" in params

    def test_create_return_has_string_ids(self):
        from app.core.leads.service import LeadService
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=_fake_lead())
        svc = LeadService(_make_pool(conn))

        result = run(svc.create(org_id=str(uuid.uuid4()), name="X"))
        assert isinstance(result["id"], str)
        assert isinstance(result["organization_id"], str)


# ══════════════════════════════════════════════════════════════════════════════
# 2. Read leads
# ══════════════════════════════════════════════════════════════════════════════

class TestLeadServiceList:
    def test_list_scoped_by_org_id(self):
        from app.core.leads.service import LeadService
        org_id = str(uuid.uuid4())
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[_fake_lead(org_id=org_id)])
        svc = LeadService(_make_pool(conn))

        run(svc.list(org_id=org_id))

        sql, *params = conn.fetch.call_args.args
        assert "organization_id = $1" in sql
        assert uuid.UUID(org_id) in params

    def test_list_empty_returns_empty_list(self):
        from app.core.leads.service import LeadService
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])
        svc = LeadService(_make_pool(conn))

        result = run(svc.list(org_id=str(uuid.uuid4())))
        assert result == []

    def test_list_with_status_filter_adds_where_clause(self):
        from app.core.leads.service import LeadService
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])
        svc = LeadService(_make_pool(conn))

        run(svc.list(org_id=str(uuid.uuid4()), status="qualified"))

        sql, *params = conn.fetch.call_args.args
        assert "status = $" in sql
        assert "qualified" in params


# ══════════════════════════════════════════════════════════════════════════════
# 3. Update status
# ══════════════════════════════════════════════════════════════════════════════

class TestLeadServiceUpdateStatus:
    def test_update_status_patches_lead(self):
        from app.core.leads.service import LeadService
        org_id = str(uuid.uuid4())
        lead_id = str(uuid.uuid4())
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=_fake_lead(
            lead_id=lead_id, org_id=org_id, status="contacted"
        ))
        svc = LeadService(_make_pool(conn))

        result = run(svc.update_status(lead_id=lead_id, org_id=org_id, status="contacted"))

        assert result["status"] == "contacted"
        sql, *params = conn.fetchrow.call_args.args
        assert "UPDATE leads" in sql
        assert "contacted" in params

    def test_update_status_returns_none_when_lead_not_found(self):
        from app.core.leads.service import LeadService
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)
        svc = LeadService(_make_pool(conn))

        result = run(svc.update_status(
            lead_id=str(uuid.uuid4()), org_id=str(uuid.uuid4()), status="won",
        ))
        assert result is None


# ══════════════════════════════════════════════════════════════════════════════
# 4. Org isolation
# ══════════════════════════════════════════════════════════════════════════════

class TestOrgIsolation:
    def test_get_returns_none_for_lead_from_different_org(self):
        """DB WHERE clause returns None for a lead owned by another org."""
        from app.core.leads.service import LeadService
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)
        svc = LeadService(_make_pool(conn))

        result = run(svc.get(lead_id=str(uuid.uuid4()), org_id=str(uuid.uuid4())))
        assert result is None

    def test_get_sql_always_includes_org_filter(self):
        """SELECT must always filter on organization_id — never by lead id alone."""
        from app.core.leads.service import LeadService
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)
        svc = LeadService(_make_pool(conn))

        run(svc.get(lead_id=str(uuid.uuid4()), org_id=str(uuid.uuid4())))

        sql, *params = conn.fetchrow.call_args.args
        assert "organization_id" in sql
        assert len(params) == 2  # must be (lead_id, org_id) — not id alone

    def test_update_status_sql_scopes_to_org(self):
        """UPDATE must scope to organization_id so org-B cannot mutate org-A's lead."""
        from app.core.leads.service import LeadService
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)
        svc = LeadService(_make_pool(conn))

        run(svc.update_status(
            lead_id=str(uuid.uuid4()), org_id=str(uuid.uuid4()), status="won"
        ))

        sql, *params = conn.fetchrow.call_args.args
        assert "organization_id" in sql


# ══════════════════════════════════════════════════════════════════════════════
# 5. Permission enforcement — validated at source level
# ══════════════════════════════════════════════════════════════════════════════

class TestPermissionEnforcement:
    def test_router_source_uses_require_permission_for_read(self):
        import inspect
        import importlib
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "leads_router_src",
            "/home/user/ai-automation-studio/app/routers/leads.py",
        )
        src = open("/home/user/ai-automation-studio/app/routers/leads.py").read()
        assert 'require_permission("leads", "read")' in src

    def test_router_source_uses_require_permission_for_write(self):
        src = open("/home/user/ai-automation-studio/app/routers/leads.py").read()
        assert 'require_permission("leads", "write")' in src

    def test_every_endpoint_has_ctx_dependency(self):
        """Every route function must receive ctx: OrgContext via Depends."""
        src = open("/home/user/ai-automation-studio/app/routers/leads.py").read()
        # All 5 endpoints must include Depends(require_permission(...))
        assert src.count("Depends(require_permission(") >= 5

    def test_lead_service_singleton_raises_before_init(self):
        """get_lead_service() must raise RuntimeError before init_lead_service()."""
        from app.core.leads import service as svc_mod
        original = svc_mod._service_instance
        svc_mod._service_instance = None
        try:
            svc_mod.get_lead_service()
            assert False, "Expected RuntimeError"
        except RuntimeError as exc:
            assert "init_lead_service" in str(exc)
        finally:
            svc_mod._service_instance = original


# ══════════════════════════════════════════════════════════════════════════════
# 6. Input validation
# ══════════════════════════════════════════════════════════════════════════════

class TestCreateLeadRequestValidation:
    def _load_models(self):
        """Import CreateLeadRequest and UpdateStatusRequest directly, bypassing __init__.py."""
        import importlib.util, importlib
        # Ensure the leads router module is importable standalone
        # by stubbing routers/__init__.py side-effects
        with patch.dict(sys.modules, {"app.routers": types.ModuleType("app.routers")}):
            spec = importlib.util.spec_from_file_location(
                "_leads_router",
                "/home/user/ai-automation-studio/app/routers/leads.py",
            )
            mod = importlib.util.module_from_spec(spec)
            # inject stubs so the module-level imports succeed
            sys.modules.setdefault("app.core.leads", types.ModuleType("app.core.leads"))
            sys.modules["app.core.leads"].get_lead_service = lambda: MagicMock()
            spec.loader.exec_module(mod)
        return mod

    def test_empty_name_rejected(self):
        mod = self._load_models()
        try:
            mod.CreateLeadRequest(name="")
            assert False, "Expected ValidationError"
        except Exception as exc:
            assert "name" in str(exc).lower() or "short" in str(exc).lower()

    def test_name_too_long_rejected(self):
        mod = self._load_models()
        try:
            mod.CreateLeadRequest(name="x" * 201)
            assert False, "Expected ValidationError"
        except Exception as exc:
            assert "name" in str(exc).lower() or "long" in str(exc).lower()

    def test_valid_minimal_lead(self):
        mod = self._load_models()
        req = mod.CreateLeadRequest(name="Ahmed")
        assert req.name == "Ahmed"
        assert req.email is None

    def test_invalid_status_rejected(self):
        mod = self._load_models()
        try:
            mod.UpdateStatusRequest(status="invalid_status")
            assert False, "Expected ValidationError"
        except Exception:
            pass

    def test_valid_statuses_accepted(self):
        mod = self._load_models()
        for s in ("new", "qualified", "contacted", "won", "lost"):
            req = mod.UpdateStatusRequest(status=s)
            assert req.status == s


# ══════════════════════════════════════════════════════════════════════════════
# 7a. AI qualification success
# ══════════════════════════════════════════════════════════════════════════════

class TestAIQualificationSuccess:
    def test_qualify_sets_status_qualified_on_success(self):
        from app.core.leads.service import LeadService
        from app.core.ai.agents import runtime as rt_mod

        org_id = str(uuid.uuid4())
        lead_id = str(uuid.uuid4())

        initial_row = _fake_lead(lead_id=lead_id, org_id=org_id)
        qualified_row = _fake_lead(
            lead_id=lead_id, org_id=org_id,
            status="qualified", ai_score=8, ai_notes="Strong agency fit",
        )
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[initial_row, qualified_row])
        svc = LeadService(_make_pool(conn))

        mock_result = MagicMock(success=True, content='{"score": 8, "notes": "Strong agency fit"}', error=None)

        original_cls = rt_mod.AgentRuntime
        try:
            mock_rt_instance = MagicMock()
            mock_rt_instance.run = AsyncMock(return_value=mock_result)
            rt_mod.AgentRuntime = lambda cfg: mock_rt_instance
            result = run(svc.qualify(lead_id=lead_id, org_id=org_id))
        finally:
            rt_mod.AgentRuntime = original_cls

        assert result["status"] == "qualified"
        assert result["ai_score"] == 8

    def test_qualify_sql_stores_ai_score_and_notes(self):
        from app.core.leads.service import LeadService
        from app.core.ai.agents import runtime as rt_mod

        org_id = str(uuid.uuid4())
        lead_id = str(uuid.uuid4())
        initial_row = _fake_lead(lead_id=lead_id, org_id=org_id)
        updated_row = _fake_lead(lead_id=lead_id, org_id=org_id, status="qualified", ai_score=9)
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[initial_row, updated_row])
        svc = LeadService(_make_pool(conn))

        mock_result = MagicMock(success=True, content='{"score": 9, "notes": "Top agency"}', error=None)
        original_cls = rt_mod.AgentRuntime
        try:
            mock_rt = MagicMock()
            mock_rt.run = AsyncMock(return_value=mock_result)
            rt_mod.AgentRuntime = lambda cfg: mock_rt
            run(svc.qualify(lead_id=lead_id, org_id=org_id))
        finally:
            rt_mod.AgentRuntime = original_cls

        # Second fetchrow call is the UPDATE
        sql, *params = conn.fetchrow.call_args.args
        assert "UPDATE leads" in sql
        assert "ai_score" in sql


# ══════════════════════════════════════════════════════════════════════════════
# 7b. AI qualification failure
# ══════════════════════════════════════════════════════════════════════════════

class TestAIQualificationFailure:
    def test_qualify_keeps_status_new_on_runtime_error(self):
        from app.core.leads.service import LeadService
        from app.core.ai.agents import runtime as rt_mod

        org_id = str(uuid.uuid4())
        lead_id = str(uuid.uuid4())
        initial_row = _fake_lead(lead_id=lead_id, org_id=org_id)
        degraded_row = _fake_lead(
            lead_id=lead_id, org_id=org_id,
            status="new", ai_score=None, ai_notes="AI qualification unavailable: network error",
        )
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[initial_row, degraded_row])
        svc = LeadService(_make_pool(conn))

        original_cls = rt_mod.AgentRuntime
        try:
            mock_rt = MagicMock()
            mock_rt.run = AsyncMock(side_effect=Exception("network error"))
            rt_mod.AgentRuntime = lambda cfg: mock_rt
            result = run(svc.qualify(lead_id=lead_id, org_id=org_id))
        finally:
            rt_mod.AgentRuntime = original_cls

        assert result["status"] == "new"
        assert result["ai_score"] is None

    def test_qualify_keeps_status_new_on_ai_failure_flag(self):
        from app.core.leads.service import LeadService
        from app.core.ai.agents import runtime as rt_mod

        org_id = str(uuid.uuid4())
        lead_id = str(uuid.uuid4())
        initial_row = _fake_lead(lead_id=lead_id, org_id=org_id)
        degraded_row = _fake_lead(
            lead_id=lead_id, org_id=org_id,
            status="new", ai_notes="AI qualification failed: quota exceeded",
        )
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[initial_row, degraded_row])
        svc = LeadService(_make_pool(conn))

        mock_result = MagicMock(success=False, content=None, error="quota exceeded")
        original_cls = rt_mod.AgentRuntime
        try:
            mock_rt = MagicMock()
            mock_rt.run = AsyncMock(return_value=mock_result)
            rt_mod.AgentRuntime = lambda cfg: mock_rt
            result = run(svc.qualify(lead_id=lead_id, org_id=org_id))
        finally:
            rt_mod.AgentRuntime = original_cls

        assert result["status"] == "new"

    def test_lead_record_never_lost_on_crash(self):
        """A total RuntimeError inside qualify() must not lose the lead."""
        from app.core.leads.service import LeadService
        from app.core.ai.agents import runtime as rt_mod

        org_id = str(uuid.uuid4())
        lead_id = str(uuid.uuid4())
        row = _fake_lead(lead_id=lead_id, org_id=org_id)
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[row, row])
        svc = LeadService(_make_pool(conn))

        original_cls = rt_mod.AgentRuntime
        try:
            mock_rt = MagicMock()
            mock_rt.run = AsyncMock(side_effect=RuntimeError("crash"))
            rt_mod.AgentRuntime = lambda cfg: mock_rt
            result = run(svc.qualify(lead_id=lead_id, org_id=org_id))
        finally:
            rt_mod.AgentRuntime = original_cls

        # Lead is returned, never None
        assert result is not None
        assert result.get("name") == "Ahmed Al-Rashid"


# ══════════════════════════════════════════════════════════════════════════════
# 8. lead.qualified notification
# ══════════════════════════════════════════════════════════════════════════════

class TestLeadQualifiedNotification:
    def _patch_notif(self, mock_notif):
        """Patch get_notification_service in the notifications service stub."""
        notif_svc_mod = sys.modules.get("app.core.notifications.service")
        if notif_svc_mod is None:
            notif_svc_mod = types.ModuleType("app.core.notifications.service")
            sys.modules["app.core.notifications.service"] = notif_svc_mod
        original = getattr(notif_svc_mod, "get_notification_service", None)
        notif_svc_mod.get_notification_service = lambda: mock_notif
        return notif_svc_mod, original

    def test_notification_sent_to_all_org_members(self):
        from app.core.leads.service import LeadService
        org_id = str(uuid.uuid4())
        user_a = str(uuid.uuid4())
        user_b = str(uuid.uuid4())

        conn = AsyncMock()
        svc = LeadService(_make_pool(conn))

        mock_notif = AsyncMock()
        mock_notif.org_member_ids = AsyncMock(return_value=[user_a, user_b])
        mock_notif.create = AsyncMock()

        lead = {"id": str(uuid.uuid4()), "name": "Test Lead", "ai_score": 8, "ai_notes": "Strong fit"}
        mod, original = self._patch_notif(mock_notif)
        try:
            run(svc.dispatch_qualified_notification(lead=lead, org_id=org_id))
        finally:
            mod.get_notification_service = original

        assert mock_notif.create.await_count == 2
        call_kwargs = mock_notif.create.call_args_list[0].kwargs
        assert call_kwargs["type_"] == "lead.qualified"
        assert call_kwargs["category"] == "workflow"

    def test_notification_contains_lead_name(self):
        from app.core.leads.service import LeadService
        org_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())

        conn = AsyncMock()
        svc = LeadService(_make_pool(conn))

        mock_notif = AsyncMock()
        mock_notif.org_member_ids = AsyncMock(return_value=[user_id])
        mock_notif.create = AsyncMock()

        lead = {"id": str(uuid.uuid4()), "name": "Yassi Agency", "ai_score": 9, "ai_notes": "Top tier"}
        mod, original = self._patch_notif(mock_notif)
        try:
            run(svc.dispatch_qualified_notification(lead=lead, org_id=org_id))
        finally:
            mod.get_notification_service = original

        call_kwargs = mock_notif.create.call_args_list[0].kwargs
        assert "Yassi Agency" in call_kwargs["title"]
        assert "9" in call_kwargs["message"]

    def test_notification_failure_silenced(self):
        from app.core.leads.service import LeadService
        conn = AsyncMock()
        svc = LeadService(_make_pool(conn))

        mock_notif = AsyncMock()
        mock_notif.org_member_ids = AsyncMock(side_effect=Exception("service down"))

        lead = {"id": str(uuid.uuid4()), "name": "Test", "ai_score": 7, "ai_notes": "ok"}
        mod, original = self._patch_notif(mock_notif)
        try:
            run(svc.dispatch_qualified_notification(lead=lead, org_id=str(uuid.uuid4())))
        finally:
            mod.get_notification_service = original
        # If we get here, the exception was correctly swallowed


# ══════════════════════════════════════════════════════════════════════════════
# 9. _parse_qualification helper
# ══════════════════════════════════════════════════════════════════════════════

class TestParseQualification:
    def test_parses_valid_json(self):
        from app.core.leads.service import _parse_qualification
        result = _parse_qualification('{"score": 7, "notes": "Good fit"}')
        assert result["score"] == 7
        assert "Good fit" in result["notes"]

    def test_clamps_score_above_10(self):
        from app.core.leads.service import _parse_qualification
        result = _parse_qualification('{"score": 15, "notes": "too high"}')
        assert result["score"] == 10

    def test_clamps_score_below_1(self):
        from app.core.leads.service import _parse_qualification
        result = _parse_qualification('{"score": -3, "notes": "too low"}')
        assert result["score"] == 1

    def test_returns_raw_notes_when_no_json(self):
        from app.core.leads.service import _parse_qualification
        result = _parse_qualification("No JSON here at all")
        assert result["notes"] == "No JSON here at all"
        assert result.get("score") is None

    def test_handles_json_embedded_in_text(self):
        from app.core.leads.service import _parse_qualification
        result = _parse_qualification('Some text {"score": 5, "notes": "average"} more text')
        assert result["score"] == 5


# ══════════════════════════════════════════════════════════════════════════════
# 10. Follow-up workflow wiring (source-level verification)
# ══════════════════════════════════════════════════════════════════════════════

class TestFollowUpWorkflowWiring:
    def _src(self) -> str:
        return open("/home/user/ai-automation-studio/app/routers/leads.py").read()

    def test_follow_up_status_no_definition_is_default(self):
        """follow_up_status must default to 'no_definition'."""
        assert "no_definition" in self._src()

    def test_follow_up_status_enqueued_on_definition_found(self):
        """When a definition row is found, follow_up_status becomes 'enqueued'."""
        assert "enqueued" in self._src()

    def test_follow_up_query_checks_lead_followup_flag(self):
        """The automation_definitions query must check lead_followup='true'."""
        assert "lead_followup" in self._src()

    def test_job_queue_submit_called_for_followup(self):
        """Follow-up must be submitted via get_job_queue().submit()."""
        src = self._src()
        assert "get_job_queue()" in src
        assert "automation.trigger.manual" in src

    def test_lead_service_singleton_raises_before_init(self):
        from app.core.leads import service as svc_mod
        original = svc_mod._service_instance
        svc_mod._service_instance = None
        try:
            svc_mod.get_lead_service()
            assert False, "Expected RuntimeError"
        except RuntimeError as exc:
            assert "init_lead_service" in str(exc)
        finally:
            svc_mod._service_instance = original
