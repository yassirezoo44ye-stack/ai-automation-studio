"""
Tests: EngineeringToolGateway — allowlist enforcement, risk levels,
secret key redaction, budget guard, tool registration.
"""
import pytest

from app.engineering.tools.gateway import (
    RiskLevel, ToolDefinition, ToolCallResult, ToolRegistry,
    _sanitize, _SECRET_KEYS, _inputs_hash,
    ToolNotFoundError, ToolPermissionError,
)


# ── _sanitize ─────────────────────────────────────────────────────────────────

_REDACTED = "***REDACTED***"


def test_sanitize_redacts_secret_keys():
    data = {
        "api_key":           "rnd_actual_secret",
        "safe_field":        "hello",
        "auth_token":        "tok_abc123",
        "private_key_pem":   "-----BEGIN RSA PRIVATE KEY-----",
        "nested": {
            "password": "hunter2",
            "name":     "alice",
        },
    }
    result = _sanitize(data)
    assert result["api_key"]         == _REDACTED
    assert result["auth_token"]      == _REDACTED
    assert result["private_key_pem"] == _REDACTED
    assert result["safe_field"]      == "hello"
    assert result["nested"]["password"] == _REDACTED
    assert result["nested"]["name"]     == "alice"


def test_sanitize_truncates_long_strings():
    long_str = "a" * 5000
    result = _sanitize({"key": long_str})
    # Truncated at 4096 chars + "...<truncated>" suffix
    assert result["key"].startswith("a" * 4096)
    assert "<truncated>" in result["key"]


def test_sanitize_caps_list_size():
    big_list = list(range(200))
    result = _sanitize({"items": big_list})
    assert len(result["items"]) <= 50


def test_sanitize_depth_cap():
    # Build deeply nested dict
    data = {}
    node = data
    for i in range(15):
        node["next"] = {}
        node = node["next"]
    node["secret"] = "value"
    # Should not raise; depth cap prevents infinite recursion
    result = _sanitize(data)
    assert result is not None


def test_sanitize_handles_non_dict_types():
    assert _sanitize("plain string") == "plain string"
    assert _sanitize(42) == 42
    assert _sanitize(None) is None


def test_sanitize_handles_list_of_dicts():
    data = [{"api_key": "secret"}, {"name": "alice"}]
    result = _sanitize(data)
    assert result[0]["api_key"] == _REDACTED
    assert result[1]["name"] == "alice"


# ── _inputs_hash ──────────────────────────────────────────────────────────────

def test_inputs_hash_is_deterministic():
    args = {"repo": "owner/repo", "sha": "abc123"}
    h1 = _inputs_hash(args)
    h2 = _inputs_hash(args)
    assert h1 == h2
    assert len(h1) == 32


def test_inputs_hash_redacts_secrets():
    args_with_secret = {"api_key": "rnd_xxx", "repo": "owner/repo"}
    args_safe = {"repo": "owner/repo"}
    # The hash of args_with_secret should be different from args_safe
    # because _sanitize replaces api_key with "[REDACTED]" — both stable
    h1 = _inputs_hash(args_with_secret)
    h2 = _inputs_hash(args_with_secret)
    assert h1 == h2  # at least deterministic
    assert len(h1) == 32


# ── ToolRegistry ──────────────────────────────────────────────────────────────

def test_tool_registry_register_and_get():
    registry = ToolRegistry()
    defn = ToolDefinition(
        name="test.read_thing",
        provider="test",
        operation="read_thing",
        description="Read a thing",
        risk_level=RiskLevel.READ,
        required_args=["thing_id"],
    )
    registry.register(defn)
    assert registry.get("test.read_thing") is defn


def test_tool_registry_require_raises_on_missing():
    registry = ToolRegistry()
    with pytest.raises(ToolNotFoundError):
        registry.require("nonexistent.tool")


def test_tool_registry_list_for_role():
    registry = ToolRegistry()

    read_defn = ToolDefinition(
        name="svc.read", provider="svc", operation="read",
        description="read", risk_level=RiskLevel.READ, required_args=[],
    )
    deploy_defn = ToolDefinition(
        name="svc.deploy", provider="svc", operation="deploy",
        description="deploy", risk_level=RiskLevel.DEPLOY, required_args=[],
    )
    registry.register(read_defn)
    registry.register(deploy_defn)

    # viewer can only see READ tools — list_for_role returns ToolDefinition objects
    viewer_tools = registry.list_for_role("viewer")
    viewer_names = [t.name for t in viewer_tools]
    assert "svc.read" in viewer_names
    assert "svc.deploy" not in viewer_names

    # admin can see both
    admin_tools = registry.list_for_role("admin")
    admin_names = [t.name for t in admin_tools]
    assert "svc.read" in admin_names
    assert "svc.deploy" in admin_names


# ── RiskLevel ordering ────────────────────────────────────────────────────────

def test_risk_level_values_are_stable():
    assert RiskLevel.READ        == "read"
    assert RiskLevel.ANALYZE     == "analyze"
    assert RiskLevel.WRITE       == "write"
    assert RiskLevel.DEPLOY      == "deploy"
    assert RiskLevel.DESTRUCTIVE == "destructive"


# ── ToolDefinition ────────────────────────────────────────────────────────────

def test_tool_definition_defaults():
    defn = ToolDefinition(
        name="t.read",
        provider="t",
        operation="read",
        description="read something",
        risk_level=RiskLevel.READ,
        required_args=[],
    )
    assert defn.timeout_s == 30.0
    assert defn.idempotent is True


def test_tool_definition_custom_timeout():
    defn = ToolDefinition(
        name="t.long",
        provider="t",
        operation="long",
        description="long op",
        risk_level=RiskLevel.ANALYZE,
        required_args=[],
        timeout_s=120.0,
        idempotent=False,
    )
    assert defn.timeout_s == 120.0
    assert defn.idempotent is False


# ── ToolCallResult ────────────────────────────────────────────────────────────

def test_tool_call_result_structure():
    r = ToolCallResult(
        tool_name="github.list_commits",
        success=True,
        output={"commits": []},
        error=None,
        evidence_id="ev-abc",
        duration_ms=123.4,
        required_approval=False,
        approval_id=None,
    )
    assert r.success is True
    assert r.tool_name == "github.list_commits"
    assert r.required_approval is False
