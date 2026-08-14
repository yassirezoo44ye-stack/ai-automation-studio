"""
Tests: Engineering Control Plane — 10 security tests (per spec Phase J).

1.  org_id never accepted from request body in missions_api
2.  user_id never accepted from request body in missions_api
3.  Credentials never appear in ToolCallResult.output
4.  Tool results are sanitized before returning (no secrets leaked)
5.  Allowlist: unknown tool_name raises ToolNotFoundError
6.  Approval is required for DEPLOY risk tools (gate not skippable)
7.  SHA mismatch → is_production_verified=False (never SUCCEEDED)
8.  SSRF guard blocks private-IP health URLs
9.  RLS tables list includes all 5 eng_* tables
10. _sanitize redacts every key in _SECRET_KEYS
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── 1. org_id is never from request body ─────────────────────────────────────

def test_create_mission_request_has_no_org_id_field():
    """CreateMissionRequest must not have an org_id field."""
    from app.routers.missions_api import CreateMissionRequest
    fields = CreateMissionRequest.model_fields
    assert "org_id" not in fields
    assert "organization_id" not in fields


# ── 2. user_id is never from request body ────────────────────────────────────

def test_create_mission_request_has_no_user_id_field():
    from app.routers.missions_api import CreateMissionRequest
    fields = CreateMissionRequest.model_fields
    assert "user_id" not in fields
    assert "created_by" not in fields


def test_launch_request_has_no_org_or_user_id():
    from app.routers.missions_api import LaunchReleasePipelineRequest
    fields = LaunchReleasePipelineRequest.model_fields
    for bad in ("org_id", "organization_id", "user_id", "created_by"):
        assert bad not in fields, f"field {bad!r} must not be in request body"


# ── 3. Credentials never in ToolCallResult.output ────────────────────────────

def test_tool_call_result_output_is_sanitized():
    """
    Simulate a tool that accidentally returns credential data.
    The gateway sanitizes before building the result — so the caller
    never sees the raw secret.
    """
    from app.engineering.tools.gateway import _sanitize
    raw_output = {
        "data": "some data",
        "api_key": "rnd_this_should_not_leak",
        "nested": {"password": "hunter2"},
    }
    safe = _sanitize(raw_output)
    assert safe["api_key"] == "***REDACTED***"
    assert safe["nested"]["password"] == "***REDACTED***"
    assert safe["data"] == "some data"


# ── 4. Tool results (UNTRUSTED DATA) sanitized ───────────────────────────────

def test_sanitize_handles_all_secret_key_variations():
    from app.engineering.tools.gateway import _sanitize, _SECRET_KEYS
    data = {k: "secret_value" for k in _SECRET_KEYS}
    result = _sanitize(data)
    for k in _SECRET_KEYS:
        assert result[k] == "***REDACTED***", f"key {k!r} was not redacted"


# ── 5. Allowlist enforcement ──────────────────────────────────────────────────

def test_tool_not_found_raises_for_unknown_tool():
    from app.engineering.tools.gateway import ToolRegistry, ToolNotFoundError
    registry = ToolRegistry()
    with pytest.raises(ToolNotFoundError):
        registry.require("generic_tool.execute")  # not in allowlist


def test_tool_not_found_for_shell_execute():
    from app.engineering.tools.gateway import ToolRegistry, ToolNotFoundError
    registry = ToolRegistry()
    with pytest.raises(ToolNotFoundError):
        registry.require("shell")


def test_tool_not_found_for_eval():
    from app.engineering.tools.gateway import ToolRegistry, ToolNotFoundError
    registry = ToolRegistry()
    with pytest.raises(ToolNotFoundError):
        registry.require("eval")


# ── 6. Approval required for DEPLOY risk ─────────────────────────────────────

def test_deploy_risk_in_approval_required_set():
    from app.engineering.tools.gateway import _APPROVAL_REQUIRED, RiskLevel
    assert RiskLevel.DEPLOY in _APPROVAL_REQUIRED
    assert RiskLevel.DESTRUCTIVE in _APPROVAL_REQUIRED
    assert RiskLevel.READ not in _APPROVAL_REQUIRED
    assert RiskLevel.ANALYZE not in _APPROVAL_REQUIRED
    assert RiskLevel.WRITE not in _APPROVAL_REQUIRED


# ── 7. SHA mismatch → not PRODUCTION VERIFIED ────────────────────────────────

def test_sha_mismatch_never_verified():
    from app.engineering.verify import VerificationResult
    r = VerificationResult(
        success=True,
        requested_sha="aaa111",
        observed_sha="bbb222",
        sha_match=False,
        health_ok=True,
        deploy_status="live",
        deploy_id="dep-x",
    )
    assert r.is_production_verified is False


def test_null_sha_never_verified():
    from app.engineering.verify import VerificationResult
    r = VerificationResult(
        success=True,
        requested_sha="aaa111",
        observed_sha=None,
        sha_match=False,
        health_ok=True,
        deploy_status="live",
        deploy_id="dep-x",
    )
    assert r.is_production_verified is False


# ── 8. SSRF guard (tested in depth in test_engineering_verify.py) ─────────────

@pytest.mark.asyncio
async def test_health_check_blocks_loopback():
    from app.engineering.verify import ProductionVerifier

    class _FakeUnsafe(Exception):
        pass

    verifier = ProductionVerifier(pool=None)
    # assert_public_url is imported locally inside _check_health,
    # so we patch it at the source module level
    with patch("app.core.ssrf_guard.assert_public_url",
               side_effect=_FakeUnsafe("blocked")):
        with patch("app.core.ssrf_guard.UnsafeUrlError", _FakeUnsafe):
            result = await verifier._check_health("http://127.0.0.1/health")
    assert result is False


# ── 9. RLS tables ─────────────────────────────────────────────────────────────

def test_rls_tables_include_all_eng_tables():
    from app.tenancy.rls import _RLS_TABLES
    table_names = {t[0] for t in _RLS_TABLES}
    required = {
        "eng_missions",
        "eng_tasks",
        "eng_task_transitions",
        "eng_evidence",
        "eng_approvals",
    }
    missing = required - table_names
    assert not missing, f"RLS missing for tables: {missing}"


# ── 10. _SECRET_KEYS completeness ────────────────────────────────────────────

def test_secret_keys_includes_critical_patterns():
    from app.engineering.tools.gateway import _SECRET_KEYS
    must_include = {
        "token", "api_key", "secret", "password",
        "private_key_pem", "auth_token", "client_secret",
        "access_token", "refresh_token",
    }
    missing = must_include - _SECRET_KEYS
    assert not missing, f"_SECRET_KEYS missing: {missing}"
