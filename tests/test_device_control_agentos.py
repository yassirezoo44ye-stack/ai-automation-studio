"""
Gate J test suite: AgentOS / App Builder integration for Multi-Device Control.

Tests cover:
  1. Tool registration — all 5 tools in global registry
  2. ContextVar security — tools reject missing org context
  3. org_id injection prevention — tool schemas have no org_id field
  4. _safe_device / _safe_session — no secrets in returned payloads
  5. DeviceControlAgent — validate() rejects no-org context
  6. DeviceControlAgent — class-level attributes
  7. DeviceControlCoordinator — present in BUILTIN_AGENTS, correct tools
  8. AppSpec — multi_device_config field exists and is Optional
  9. AppSpec parsing — null multi_device_config
 10. AppSpec parsing — enabled multi_device_config
 11. AppSpec parsing — invalid enabled value → None
 12. _SPEC_SYSTEM — mentions multi_device_config
 13. factory.py — import of tools_device_control is present
 14. DEVICE_CONTROL_TOOL_NAMES — correct length and members
 15. Event dataclasses — all six exist and have correct event_type
 16. DeviceControlAgent.execute — rejects empty org_id
 17. device_control_list_devices — rejects missing context
 18. device_control_validate_session — rejects missing context
 19. device_control_propose_session — rejects missing context
 20. device_control_session_status — rejects missing context
 21. device_control_stop_session — rejects missing context
 22. _safe_device strips credential_hash and device_fingerprint
 23. _safe_session strips session_token
 24. set_device_control_context + _require_context round-trip
 25. BUILTIN_AGENTS registry contains 'device_control_coordinator'
"""
from __future__ import annotations

import json
from dataclasses import fields as dc_fields
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ──────────────────────────────────────────────────────────────────────────────
# 1.  Tool registration — all 5 tools in global registry
# ──────────────────────────────────────────────────────────────────────────────

def test_all_device_control_tools_registered():
    """Importing the module must register all 5 tools into _REGISTRY."""
    import app.ai.tools_device_control  # noqa: F401 — ensure imported
    from app.ai.tools import _REGISTRY

    expected = {
        "device_control_list_devices",
        "device_control_validate_session",
        "device_control_propose_session",
        "device_control_session_status",
        "device_control_stop_session",
    }
    registered = set(_REGISTRY.keys())
    for name in expected:
        assert name in registered, f"Tool '{name}' not found in registry"


# ──────────────────────────────────────────────────────────────────────────────
# 2.  ContextVar security — tools reject missing org context
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_devices_rejects_missing_context():
    from app.ai.tools_device_control import (
        device_control_list_devices,
        _dc_org_id_var,
    )
    # Ensure context is empty
    token = _dc_org_id_var.set("")
    try:
        result_json = await device_control_list_devices()
        result = json.loads(result_json)
        assert "error" in result, "Expected error when org context is missing"
    finally:
        _dc_org_id_var.reset(token)


@pytest.mark.asyncio
async def test_validate_session_rejects_missing_context():
    from app.ai.tools_device_control import (
        device_control_validate_session,
        _dc_org_id_var,
    )
    token = _dc_org_id_var.set("")
    try:
        result_json = await device_control_validate_session("dev-1", ["dev-2"])
        result = json.loads(result_json)
        assert "error" in result
    finally:
        _dc_org_id_var.reset(token)


@pytest.mark.asyncio
async def test_propose_session_rejects_missing_context():
    from app.ai.tools_device_control import (
        device_control_propose_session,
        _dc_org_id_var,
    )
    token = _dc_org_id_var.set("")
    try:
        result_json = await device_control_propose_session("dev-1", ["dev-2"])
        result = json.loads(result_json)
        assert "error" in result
    finally:
        _dc_org_id_var.reset(token)


@pytest.mark.asyncio
async def test_session_status_rejects_missing_context():
    from app.ai.tools_device_control import (
        device_control_session_status,
        _dc_org_id_var,
    )
    token = _dc_org_id_var.set("")
    try:
        result_json = await device_control_session_status("sess-1")
        result = json.loads(result_json)
        assert "error" in result
    finally:
        _dc_org_id_var.reset(token)


@pytest.mark.asyncio
async def test_stop_session_rejects_missing_context():
    from app.ai.tools_device_control import (
        device_control_stop_session,
        _dc_org_id_var,
    )
    token = _dc_org_id_var.set("")
    try:
        result_json = await device_control_stop_session("sess-1")
        result = json.loads(result_json)
        assert "error" in result
    finally:
        _dc_org_id_var.reset(token)


# ──────────────────────────────────────────────────────────────────────────────
# 3.  org_id injection prevention — tool schemas have NO org_id parameter
# ──────────────────────────────────────────────────────────────────────────────

def test_tool_schemas_have_no_org_id_parameter():
    """The LLM must never be able to supply an org_id."""
    from app.ai.tools import _REGISTRY
    from app.ai.tools_device_control import DEVICE_CONTROL_TOOL_NAMES

    for name in DEVICE_CONTROL_TOOL_NAMES:
        entry = _REGISTRY[name]
        schema_props: dict = entry.schema.parameters.get("properties", {})
        assert "org_id" not in schema_props, (
            f"Tool '{name}' exposes 'org_id' in its schema — "
            "the LLM could inject a foreign org_id!"
        )
        assert "organization_id" not in schema_props, (
            f"Tool '{name}' exposes 'organization_id' in its schema"
        )


# ──────────────────────────────────────────────────────────────────────────────
# 4.  _safe_device / _safe_session — no secrets in returned payloads
# ──────────────────────────────────────────────────────────────────────────────

def test_safe_device_strips_secrets():
    from app.ai.tools_device_control import _safe_device

    raw = {
        "id":               "dev-uuid",
        "name":             "My Laptop",
        "platform":         "windows",
        "hostname":         "LAPTOP-01",
        "status":           "online",
        "screen_width":     1920,
        "screen_height":    1080,
        "last_seen_at":     "2026-01-01T00:00:00Z",
        "agent_version":    "1.0.0",
        # Secrets that must never be returned:
        "credential_hash":   "sha256_of_secret",
        "device_fingerprint": "fingerprint_blob",
        "display_config":    {"raw": "data"},
        "capabilities":      {"internal": True},
    }
    safe = _safe_device(raw)

    assert "credential_hash"    not in safe
    assert "device_fingerprint" not in safe
    assert "display_config"     not in safe
    # Safe fields must be present
    assert safe["id"]      == "dev-uuid"
    assert safe["name"]    == "My Laptop"
    assert safe["status"]  == "online"


def test_safe_session_strips_secrets():
    from app.ai.tools_device_control import _safe_session

    raw = {
        "id":                "sess-uuid",
        "status":            "active",
        "primary_device_id": "dev-uuid",
        "device_count":      2,
        "created_at":        "2026-01-01T00:00:00Z",
        "started_at":        "2026-01-01T00:01:00Z",
        "stopped_at":        None,
        "stop_reason":       None,
        # Secrets that must never be returned:
        "session_token":         "tok_supersecret",
        "authorization_token":   "auth_supersecret",
        "ws_secret":             "websocket_secret",
    }
    safe = _safe_session(raw)

    assert "session_token"       not in safe
    assert "authorization_token" not in safe
    assert "ws_secret"           not in safe
    # Safe fields must be present
    assert safe["id"]     == "sess-uuid"
    assert safe["status"] == "active"


# ──────────────────────────────────────────────────────────────────────────────
# 5.  DeviceControlAgent — validate() rejects missing org context
# ──────────────────────────────────────────────────────────────────────────────

def test_device_control_agent_validate_rejects_no_org():
    from app.agents.device_control_agent import DeviceControlAgent
    from app.agents.base import AgentContext

    agent = DeviceControlAgent()
    ctx = AgentContext(
        input="List devices",
        args="",
        kernel=MagicMock(),
        memory=MagicMock(),
        organization_id=None,   # missing
    )
    result = agent.validate(ctx)
    assert not result.valid
    assert result.errors


def test_device_control_agent_validate_passes_with_org():
    from app.agents.device_control_agent import DeviceControlAgent
    from app.agents.base import AgentContext

    agent = DeviceControlAgent()
    ctx = AgentContext(
        input="List devices",
        args="",
        kernel=MagicMock(),
        memory=MagicMock(),
        organization_id="org-123",
    )
    result = agent.validate(ctx)
    assert result.valid


# ──────────────────────────────────────────────────────────────────────────────
# 6.  DeviceControlAgent — class-level attributes
# ──────────────────────────────────────────────────────────────────────────────

def test_device_control_agent_attributes():
    from app.agents.device_control_agent import DeviceControlAgent

    agent = DeviceControlAgent()
    assert agent.name == "device_control"
    assert agent.metadata.name == "device_control"
    assert agent.metadata.version == "1.0.0"
    # Permissions: must NOT allow arbitrary subprocess or filesystem writes
    assert not agent.permissions.can_execute_subprocess
    assert not agent.permissions.can_write_filesystem
    assert not agent.permissions.can_read_filesystem
    assert agent.permissions.can_call_llm


# ──────────────────────────────────────────────────────────────────────────────
# 7.  DeviceControlCoordinator — in BUILTIN_AGENTS, has correct tools
# ──────────────────────────────────────────────────────────────────────────────

def test_device_control_coordinator_in_builtin_agents():
    from app.core.ai.agents.builtin import BUILTIN_AGENTS, DeviceControlCoordinator
    assert "device_control_coordinator" in BUILTIN_AGENTS
    assert BUILTIN_AGENTS["device_control_coordinator"] is DeviceControlCoordinator


def test_device_control_coordinator_tools():
    from app.core.ai.agents.builtin import DeviceControlCoordinator
    from unittest.mock import MagicMock

    bus = MagicMock()
    agent = DeviceControlCoordinator(bus=bus)
    tools = set(agent.config.tools)
    expected = {
        "device_control_list_devices",
        "device_control_validate_session",
        "device_control_propose_session",
        "device_control_session_status",
        "device_control_stop_session",
    }
    assert expected.issubset(tools), f"Missing tools: {expected - tools}"


def test_device_control_coordinator_no_start_tool():
    """start_session must NOT be in the tool set — human approval required."""
    from app.core.ai.agents.builtin import DeviceControlCoordinator
    from unittest.mock import MagicMock

    bus = MagicMock()
    agent = DeviceControlCoordinator(bus=bus)
    assert "device_control_start_session" not in agent.config.tools
    assert "start_session" not in agent.config.tools


# ──────────────────────────────────────────────────────────────────────────────
# 8.  AppSpec — multi_device_config field is Optional
# ──────────────────────────────────────────────────────────────────────────────

def test_app_spec_has_multi_device_config_field():
    from app.services.app_builder import AppSpec

    spec_field_names = {f.name for f in dc_fields(AppSpec)}
    assert "multi_device_config" in spec_field_names

    # Must be Optional (default is None)
    spec = AppSpec(
        name="Test", description="x", target_users="ops",
        entities=[], pages=[], roles=[], workflows=[], agents=[],
        integrations=[], settings={},
    )
    assert spec.multi_device_config is None


# ──────────────────────────────────────────────────────────────────────────────
# 9.  AppSpec parsing — null multi_device_config in AI JSON
# ──────────────────────────────────────────────────────────────────────────────

def test_parse_spec_null_multi_device_config():
    from app.services.app_builder import AppBuilderService

    svc = AppBuilderService.__new__(AppBuilderService)  # skip __init__
    data = {
        "name": "CRM", "description": "A CRM.", "target_users": "Sales",
        "entities": [], "pages": [], "roles": [], "workflows": [], "agents": [],
        "integrations": [], "settings": {}, "multi_device_config": None,
    }
    spec = svc._parse_and_validate_spec(data)
    assert spec.multi_device_config is None


# ──────────────────────────────────────────────────────────────────────────────
# 10.  AppSpec parsing — enabled multi_device_config
# ──────────────────────────────────────────────────────────────────────────────

def test_parse_spec_enabled_multi_device_config():
    from app.services.app_builder import AppBuilderService, MultiDeviceConfig

    svc = AppBuilderService.__new__(AppBuilderService)
    data = {
        "name": "Broadcast Studio", "description": "Control 3 monitors.",
        "target_users": "Broadcast engineers",
        "entities": [], "pages": [], "roles": [], "workflows": [], "agents": [],
        "integrations": [], "settings": {},
        "multi_device_config": {
            "enabled": True,
            "primary_device_hint": "STUDIO-PC",
            "max_concurrent_sessions": 2,
            "suggest_sessions": True,
            "agent_display_name": "Broadcast Control Agent",
        },
    }
    spec = svc._parse_and_validate_spec(data)
    assert spec.multi_device_config is not None
    assert isinstance(spec.multi_device_config, MultiDeviceConfig)
    assert spec.multi_device_config.enabled is True
    assert spec.multi_device_config.primary_device_hint == "STUDIO-PC"
    assert spec.multi_device_config.max_concurrent_sessions == 2
    assert spec.multi_device_config.suggest_sessions is True
    assert spec.multi_device_config.agent_display_name == "Broadcast Control Agent"


# ──────────────────────────────────────────────────────────────────────────────
# 11.  AppSpec parsing — invalid (enabled=False) → None
# ──────────────────────────────────────────────────────────────────────────────

def test_parse_spec_disabled_multi_device_config_is_none():
    from app.services.app_builder import AppBuilderService

    svc = AppBuilderService.__new__(AppBuilderService)
    data = {
        "name": "CRM", "description": "A CRM.", "target_users": "Sales",
        "entities": [], "pages": [], "roles": [], "workflows": [], "agents": [],
        "integrations": [], "settings": {},
        "multi_device_config": {"enabled": False},
    }
    spec = svc._parse_and_validate_spec(data)
    # enabled=False means we should NOT create a MultiDeviceConfig
    assert spec.multi_device_config is None


# ──────────────────────────────────────────────────────────────────────────────
# 12.  _SPEC_SYSTEM — mentions multi_device_config
# ──────────────────────────────────────────────────────────────────────────────

def test_spec_system_mentions_multi_device_config():
    from app.services.app_builder import _SPEC_SYSTEM
    assert "multi_device_config" in _SPEC_SYSTEM, (
        "_SPEC_SYSTEM must mention 'multi_device_config' so the AI knows "
        "it should populate or omit the field."
    )


# ──────────────────────────────────────────────────────────────────────────────
# 13.  factory.py — import of tools_device_control is present
# ──────────────────────────────────────────────────────────────────────────────

def test_factory_imports_tools_device_control():
    """factory.py must import tools_device_control to register tools at startup."""
    import pathlib
    factory_path = pathlib.Path(__file__).parent.parent / "app" / "factory.py"
    content = factory_path.read_text(encoding="utf-8")
    assert "tools_device_control" in content, (
        "app/factory.py does not import app.ai.tools_device_control — "
        "device-control tools will not be registered at startup."
    )


# ──────────────────────────────────────────────────────────────────────────────
# 14.  DEVICE_CONTROL_TOOL_NAMES — correct length and members
# ──────────────────────────────────────────────────────────────────────────────

def test_device_control_tool_names_count():
    from app.ai.tools_device_control import DEVICE_CONTROL_TOOL_NAMES
    assert len(DEVICE_CONTROL_TOOL_NAMES) == 5, (
        f"Expected 5 tool names, got {len(DEVICE_CONTROL_TOOL_NAMES)}"
    )


def test_device_control_tool_names_no_start():
    """No 'start' tool — starting requires human approval."""
    from app.ai.tools_device_control import DEVICE_CONTROL_TOOL_NAMES
    for name in DEVICE_CONTROL_TOOL_NAMES:
        assert "start" not in name.lower(), (
            f"Tool '{name}' contains 'start' — starting a session must "
            "require human approval, not an LLM tool call."
        )


# ──────────────────────────────────────────────────────────────────────────────
# 15.  Event dataclasses — all six exist, have correct event_type
# ──────────────────────────────────────────────────────────────────────────────

def test_device_control_events_exist():
    from app.core.ai.events.device_control_events import (
        DeviceControlSessionProposed,
        DeviceControlSessionApproved,
        DeviceControlSessionStarted,
        DeviceControlSessionStopped,
        DeviceControlSessionFailed,
        DeviceControlDiscoveryRun,
    )
    assert DeviceControlSessionProposed().event_type  == "device_control.session.proposed"
    assert DeviceControlSessionApproved().event_type  == "device_control.session.approved"
    assert DeviceControlSessionStarted().event_type   == "device_control.session.started"
    assert DeviceControlSessionStopped().event_type   == "device_control.session.stopped"
    assert DeviceControlSessionFailed().event_type    == "device_control.session.failed"
    assert DeviceControlDiscoveryRun().event_type     == "device_control.discovery.run"


def test_session_proposed_has_no_secret_fields():
    """Proposed event must never carry credentials or session tokens."""
    from app.core.ai.events.device_control_events import DeviceControlSessionProposed
    field_names = {f.name for f in dc_fields(DeviceControlSessionProposed)}
    forbidden = {"session_token", "credential_hash", "enrollment_token", "ws_secret"}
    overlap = field_names & forbidden
    assert not overlap, f"DeviceControlSessionProposed has secret fields: {overlap}"


# ──────────────────────────────────────────────────────────────────────────────
# 16.  DeviceControlAgent.execute — rejects empty org_id fast-path
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_device_control_agent_execute_rejects_no_org():
    from app.agents.device_control_agent import DeviceControlAgent
    from app.agents.base import AgentContext

    agent = DeviceControlAgent()
    ctx = AgentContext(
        input="List my devices",
        args="",
        kernel=MagicMock(),
        memory=MagicMock(),
        organization_id="",  # empty — blocked by validate() before execute()
    )
    result = await agent.run(ctx)
    # run() calls validate() first → AgentResult.fail
    assert not result.success
    assert "validation" in result.output.lower() or "organization" in result.output.lower()


# ──────────────────────────────────────────────────────────────────────────────
# 17-21.  Context missing — each tool returns JSON error (duplicate of 2 with
#          more explicit assertions about no exception being raised)
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tools_return_json_on_missing_context():
    """All tools must return parseable JSON, never raise, on missing context."""
    from app.ai.tools_device_control import (
        device_control_list_devices,
        device_control_validate_session,
        device_control_propose_session,
        device_control_session_status,
        device_control_stop_session,
        _dc_org_id_var,
    )
    token = _dc_org_id_var.set("")
    try:
        for coro in [
            device_control_list_devices(),
            device_control_validate_session("dev-1", []),
            device_control_propose_session("dev-1", []),
            device_control_session_status("sess-1"),
            device_control_stop_session("sess-1"),
        ]:
            result_json = await coro
            parsed = json.loads(result_json)   # must be valid JSON
            assert "error" in parsed, f"Expected error key in: {parsed}"
    finally:
        _dc_org_id_var.reset(token)


# ──────────────────────────────────────────────────────────────────────────────
# 22-23.  _safe_device and _safe_session — already covered in §4; extra edge cases
# ──────────────────────────────────────────────────────────────────────────────

def test_safe_device_all_safe_keys_present():
    from app.ai.tools_device_control import _safe_device
    raw = {k: None for k in [
        "id", "name", "platform", "hostname", "status",
        "screen_width", "screen_height", "last_seen_at", "agent_version",
        "credential_hash", "device_fingerprint",
    ]}
    safe = _safe_device(raw)
    for key in ("id", "name", "platform", "hostname", "status",
                "screen_width", "screen_height", "last_seen_at", "agent_version"):
        assert key in safe, f"Expected safe key '{key}' missing from _safe_device output"


def test_safe_session_all_safe_keys_present():
    from app.ai.tools_device_control import _safe_session
    raw = {k: None for k in [
        "id", "status", "primary_device_id", "device_count",
        "created_at", "started_at", "stopped_at", "stop_reason",
        "session_token",
    ]}
    safe = _safe_session(raw)
    for key in ("id", "status", "primary_device_id", "device_count",
                "created_at", "started_at", "stopped_at", "stop_reason"):
        assert key in safe, f"Expected safe key '{key}' missing from _safe_session output"


# ──────────────────────────────────────────────────────────────────────────────
# 24.  set_device_control_context + _require_context round-trip
# ──────────────────────────────────────────────────────────────────────────────

def test_set_and_require_context_round_trip():
    from app.ai.tools_device_control import (
        set_device_control_context,
        _require_context,
        _dc_org_id_var,
        _dc_user_id_var,
        _dc_user_email_var,
    )
    # Save old values
    old_org   = _dc_org_id_var.get()
    old_user  = _dc_user_id_var.get()
    old_email = _dc_user_email_var.get()
    try:
        set_device_control_context(
            org_id="org-abc", user_id="usr-xyz", user_email="alice@example.com"
        )
        org_id, user_id, user_email = _require_context()
        assert org_id    == "org-abc"
        assert user_id   == "usr-xyz"
        assert user_email == "alice@example.com"
    finally:
        _dc_org_id_var.set(old_org)
        _dc_user_id_var.set(old_user)
        _dc_user_email_var.set(old_email)


def test_require_context_raises_on_empty_org():
    from app.ai.tools_device_control import _require_context, _dc_org_id_var
    token = _dc_org_id_var.set("")
    try:
        with pytest.raises(ValueError, match="organization context"):
            _require_context()
    finally:
        _dc_org_id_var.reset(token)


# ──────────────────────────────────────────────────────────────────────────────
# 25.  BUILTIN_AGENTS registry
# ──────────────────────────────────────────────────────────────────────────────

def test_builtin_agents_registry_has_device_control():
    from app.core.ai.agents.builtin import BUILTIN_AGENTS
    assert "device_control_coordinator" in BUILTIN_AGENTS


# ──────────────────────────────────────────────────────────────────────────────
# Security invariant: propose_session is DRAFT-only (no start)
# ──────────────────────────────────────────────────────────────────────────────

def test_no_start_session_tool_exists():
    """There must be no 'start_session' tool in the registry."""
    from app.ai.tools import _REGISTRY
    for name in _REGISTRY:
        assert "start_session" not in name, (
            f"Found tool '{name}' with 'start_session' — "
            "session start must require human approval, not an LLM tool."
        )


def test_propose_session_response_includes_approval_required():
    """
    The response from device_control_propose_session must always include
    'approval_required: True' so downstream consumers know the session
    cannot be used yet.
    """
    # Test the response JSON shape even without a real DB (mock the service)
    import asyncio
    from app.ai.tools_device_control import (
        device_control_propose_session,
        _dc_org_id_var,
        _dc_user_id_var,
        _dc_user_email_var,
    )

    mock_session = {
        "id":           "sess-draft-001",
        "status":       "draft",
        "device_count": 2,
    }

    async def _run():
        # Bind context
        _dc_org_id_var.set("org-test")
        _dc_user_id_var.set("user-test")
        _dc_user_email_var.set("test@example.com")

        mock_svc = AsyncMock()
        mock_svc.create_session.return_value = mock_session

        with patch(
            "app.services.device_control.get_device_control_service",
            return_value=mock_svc,
        ):
            # Also mock the event bus to avoid Redis dependency
            with patch("app.core.ai.events.bus.bus.emit", new_callable=AsyncMock):
                result_json = await device_control_propose_session(
                    "dev-primary", ["dev-secondary"]
                )
        return result_json

    result_json = asyncio.run(_run())
    result = json.loads(result_json)

    assert result.get("approval_required") is True, (
        "device_control_propose_session must always return approval_required: True"
    )
    assert result.get("status") == "draft", (
        "Proposed session must have status 'draft'"
    )
    assert "session_id" in result
    # Confirm no secrets in response
    assert "session_token" not in result
    assert "credential_hash" not in result
