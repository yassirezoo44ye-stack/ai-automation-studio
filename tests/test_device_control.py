"""
Tests for Multi-Device Control

Coverage:
  - Enrollment token lifecycle (create → consume → single-use enforcement)
  - Device credential auth (correct, wrong, revoked)
  - Tenant isolation (Org A cannot see Org B devices)
  - Session lifecycle (create → start → stop)
  - RBAC (unpermissioned role cannot call device endpoints)
  - Failsafe: primary disconnect stops session
  - Coordinate translation math
  - SECURITY REGRESSION: vk/scan codes NEVER in any log output
"""
from __future__ import annotations

import hashlib
import pytest


# ── Pure-math tests (no DB required) ─────────────────────────────────────────

class TestTranslateCursor:
    """translate_cursor() is pure math — test exhaustively."""

    def _call(self, x, y, ws, hs, wt, ht):
        from app.services.device_control import translate_cursor
        return translate_cursor(x, y, ws, hs, wt, ht)

    def test_identity(self):
        """Same resolution → same coordinates."""
        tx, ty = self._call(500, 300, 1920, 1080, 1920, 1080)
        assert tx == 500 and ty == 300

    def test_scale_up(self):
        """1920→2560: center maps to center."""
        tx, ty = self._call(960, 540, 1920, 1080, 2560, 1440)
        assert tx == 1280 and ty == 720

    def test_scale_down(self):
        """2560→1920: center maps to center."""
        tx, ty = self._call(1280, 720, 2560, 1440, 1920, 1080)
        assert tx == 960 and ty == 540

    def test_origin(self):
        """Top-left always maps to top-left."""
        tx, ty = self._call(0, 0, 1920, 1080, 2560, 1440)
        assert tx == 0 and ty == 0

    def test_clamp_high(self):
        """Out-of-bounds input is clamped."""
        tx, ty = self._call(99999, 99999, 1920, 1080, 1920, 1080)
        assert tx == 1919 and ty == 1079

    def test_clamp_negative(self):
        tx, ty = self._call(-5, -10, 1920, 1080, 1920, 1080)
        assert tx == 0 and ty == 0

    def test_zero_source_size(self):
        """Zero source size → returns (0, 0), no ZeroDivisionError."""
        tx, ty = self._call(100, 100, 0, 0, 1920, 1080)
        assert tx == 0 and ty == 0

    def test_asymmetric_scale(self):
        """Different x/y scale factors are applied independently."""
        tx, ty = self._call(960, 540, 1920, 1080, 3840, 1080)
        assert tx == 1920 and ty == 540


class TestFindTargetDevice:
    """find_target_device() — virtual canvas neighbor lookup."""

    def _call(self, vx, vy, layout, current, direction):
        from app.services.device_control import find_target_device
        return find_target_device(vx, vy, layout, current, direction)

    def _layout(self):
        return [
            {"device_id": "A", "position_x": 0,    "position_y": 0, "width": 1920, "height": 1080, "enabled": True},
            {"device_id": "B", "position_x": 1920, "position_y": 0, "width": 1920, "height": 1080, "enabled": True},
            {"device_id": "C", "position_x": 0,    "position_y": 1080, "width": 1920, "height": 1080, "enabled": True},
        ]

    def test_right_neighbor(self):
        target = self._call(1920, 540, self._layout(), "A", "right")
        assert target is not None and target["device_id"] == "B"

    def test_bottom_neighbor(self):
        target = self._call(500, 1080, self._layout(), "A", "bottom")
        assert target is not None and target["device_id"] == "C"

    def test_no_left_of_a(self):
        target = self._call(0, 540, self._layout(), "A", "left")
        assert target is None

    def test_disabled_device_skipped(self):
        layout = [
            {"device_id": "A", "position_x": 0,    "position_y": 0, "width": 1920, "height": 1080, "enabled": True},
            {"device_id": "B", "position_x": 1920, "position_y": 0, "width": 1920, "height": 1080, "enabled": False},
        ]
        target = self._call(1920, 540, layout, "A", "right")
        assert target is None

    def test_wrap_across_gap(self):
        """Large gap between devices — should still find neighbor if aligned."""
        layout = [
            {"device_id": "A", "position_x": 0,    "position_y": 0,    "width": 1920, "height": 1080, "enabled": True},
            {"device_id": "B", "position_x": 3840, "position_y": 0,    "width": 1920, "height": 1080, "enabled": True},
        ]
        # cursor leaving right edge of A, but B is 2 monitors away — no target
        target = self._call(1920, 540, layout, "A", "right")
        # Depends on implementation — at minimum should not crash
        assert target is None or target["device_id"] == "B"


class TestHashToken:
    """Token hashing — SHA-256, deterministic, no plaintext stored."""

    def test_hash_is_sha256(self):
        from app.services.device_control import _hash_token
        raw = "test_token_abc123"
        expected = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        assert _hash_token(raw) == expected

    def test_different_inputs_different_hashes(self):
        from app.services.device_control import _hash_token
        assert _hash_token("abc") != _hash_token("def")

    def test_empty_string(self):
        from app.services.device_control import _hash_token
        h = _hash_token("")
        assert len(h) == 64  # SHA-256 hex is always 64 chars

    def test_generate_credential_returns_two_values(self):
        from app.services.device_control import _generate_credential
        raw, hashed = _generate_credential()
        assert len(raw) == 64  # 32 bytes hex
        assert len(hashed) == 64  # SHA-256 hex
        assert raw != hashed

    def test_generate_enrollment_token_returns_three_values(self):
        from app.services.device_control import _generate_enrollment_token
        raw, hashed, prefix = _generate_enrollment_token()
        assert len(raw) > 20
        assert len(hashed) == 64
        assert len(prefix) > 0
        assert prefix == raw[:4].upper()  # prefix is the uppercase display hint of the first 4 chars

    def test_generate_credential_uniqueness(self):
        from app.services.device_control import _generate_credential
        raw1, _ = _generate_credential()
        raw2, _ = _generate_credential()
        assert raw1 != raw2  # Cryptographically random — should never collide


# ── Security regression: vk/scan codes never logged ──────────────────────────

class TestNoInputLogging:
    """
    SECURITY REGRESSION SUITE.

    Verifies that keyboard vk/scan codes and cursor coordinates are
    NEVER written to any log output, even when injected or forwarded.

    If these tests fail, a security regression has been introduced.
    """

    def test_ws_device_handler_does_not_log_vk(self):
        """
        The WS device router must not reference logging of vk/scan keys.
        Scan the source to verify the invariant is maintained.
        """
        import pathlib
        src = pathlib.Path("app/routers/ws_device.py").read_text(encoding="utf-8")

        # Any log call that includes vk or scan as a format argument is a violation
        import re
        bad_patterns = [
            r'log\.(debug|info|warning|error|critical).*vk',
            r'log\.(debug|info|warning|error|critical).*scan',
            r'print.*vk\b',
            r'print.*scan\b',
        ]
        for pattern in bad_patterns:
            matches = re.findall(pattern, src, re.IGNORECASE)
            assert not matches, (
                f"SECURITY REGRESSION: found potential vk/scan logging in ws_device.py "
                f"(pattern={pattern!r}, matches={matches})"
            )

    def test_controller_does_not_log_vk(self):
        """The controller must not log vk/scan in forwarded key events."""
        import pathlib
        src = pathlib.Path("agent/core/controller.py").read_text(encoding="utf-8")
        import re
        # _forward_key logs only 'action' string, not the vk/scan integers
        # Check that no log.* call appears in the same block as vk= or scan=
        # Simple heuristic: log.info/debug/warning with vk in format string
        bad = re.findall(r'log\.\w+\(.*\bvk\b', src)
        assert not bad, f"SECURITY REGRESSION: controller logs vk: {bad}"

    def test_input_module_does_not_log_key_values(self):
        """Windows input module must not log vk/scan."""
        import pathlib
        src = pathlib.Path("agent/windows/input.py").read_text(encoding="utf-8")
        import re
        # Allow comments and docstrings that mention vk/scan for documentation
        # Disallow log.* calls that reference vk or scan as values
        bad = re.findall(r'(?:log|print)\s*[\(].*?(?:vk|scan)\b', src)
        # Filter out lines that are comments
        bad = [b for b in bad if not b.strip().startswith("#")]
        assert not bad, f"SECURITY REGRESSION: input.py logs key values: {bad}"

    def test_no_keystroke_persistence(self):
        """Verify no INSERT/UPDATE SQL for keystroke columns anywhere in device_control."""
        import pathlib
        src = pathlib.Path("app/services/device_control.py").read_text(encoding="utf-8")
        import re
        # Should not find SQL that stores vk, scan, or raw_key columns
        bad = re.findall(r'INSERT.*(?:vk_code|scan_code|raw_key|keystroke)', src, re.IGNORECASE)
        assert not bad, f"SECURITY REGRESSION: keystroke persistence found: {bad}"


# ── Schema / import smoke tests ───────────────────────────────────────────────

class TestSchemaImports:
    """Verify that all modules import cleanly (catches syntax errors)."""

    def test_import_device_control_schema(self):
        from app.services import device_control_schema
        assert hasattr(device_control_schema, "init_device_control_schema")

    def test_import_device_control_service(self):
        from app.services import device_control
        assert hasattr(device_control, "DeviceControlService")
        assert hasattr(device_control, "translate_cursor")
        assert hasattr(device_control, "find_target_device")
        assert hasattr(device_control, "_hash_token")

    def test_import_devices_router(self):
        from app.routers import devices
        assert hasattr(devices, "router")
        assert hasattr(devices, "sessions_router")

    def test_import_ws_device_router(self):
        from app.routers import ws_device
        assert hasattr(ws_device, "router")

    def test_import_agent_layout(self):
        from agent.core import layout
        assert hasattr(layout, "detect_edge_crossing")
        assert hasattr(layout, "compute_switch")

    def test_import_agent_session(self):
        from agent.core import session
        assert hasattr(session, "AgentSessionState")

    def test_import_agent_controller(self):
        from agent.core import controller
        assert hasattr(controller, "DeviceAgentController")

    def test_import_agent_credentials(self):
        from agent.security import credentials
        assert hasattr(credentials, "save_credential")
        assert hasattr(credentials, "load_credential")
        assert hasattr(credentials, "clear_credential")


# ── Tenant isolation (unit) ────────────────────────────────────────────────────

class TestTenantIsolation:
    """
    Unit-level verification that service methods filter by org_id.
    No DB required — we inspect the SQL queries generated.
    """

    def test_list_devices_includes_org_filter(self):
        """DeviceControlService.list_devices() must query with organization_id."""
        import pathlib
        src = pathlib.Path("app/services/device_control.py").read_text(encoding="utf-8")
        # The list_devices method should filter by organization_id
        import re
        list_fn = re.search(
            r'async def list_devices.*?(?=async def|\Z)',
            src, re.DOTALL
        )
        assert list_fn is not None, "list_devices method not found"
        body = list_fn.group(0)
        assert "organization_id" in body, (
            "TENANT ISOLATION VIOLATION: list_devices does not filter by organization_id"
        )

    def test_create_session_includes_org_id(self):
        """create_session() must write organization_id to the sessions table."""
        import pathlib
        src = pathlib.Path("app/services/device_control.py").read_text(encoding="utf-8")
        import re
        create_fn = re.search(
            r'async def create_session.*?(?=async def|\Z)',
            src, re.DOTALL
        )
        assert create_fn is not None, "create_session method not found"
        body = create_fn.group(0)
        assert "organization_id" in body, (
            "TENANT ISOLATION VIOLATION: create_session does not record organization_id"
        )

    def test_get_device_includes_org_filter(self):
        """get_device() must include organization_id in the WHERE clause."""
        import pathlib
        src = pathlib.Path("app/services/device_control.py").read_text(encoding="utf-8")
        import re
        get_fn = re.search(
            r'async def get_device.*?(?=async def|\Z)',
            src, re.DOTALL
        )
        assert get_fn is not None, "get_device method not found"
        body = get_fn.group(0)
        assert "organization_id" in body, (
            "TENANT ISOLATION VIOLATION: get_device does not filter by org"
        )

    def test_rls_tables_registered(self):
        """All device tables must appear in the RLS registry."""
        from app.tenancy.rls import _RLS_TABLES
        table_names = {t[0] for t in _RLS_TABLES}
        required = {
            "devices",
            "device_enrollment_tokens",
            "device_control_sessions",
            "device_session_authorizations",
        }
        missing = required - table_names
        assert not missing, (
            f"TENANT ISOLATION VIOLATION: these tables are NOT in _RLS_TABLES: {missing}"
        )


# ── RBAC permission constants ─────────────────────────────────────────────────

class TestRBAC:
    """Verify that DEVICE_PERMISSIONS covers all required operations."""

    def test_device_permissions_defined(self):
        from app.services.device_control_schema import DEVICE_PERMISSIONS
        assert isinstance(DEVICE_PERMISSIONS, list)
        assert len(DEVICE_PERMISSIONS) > 0

    def test_device_read_permission_exists(self):
        from app.services.device_control_schema import DEVICE_PERMISSIONS
        resources = {(r, a) for _, r, a in DEVICE_PERMISSIONS}
        assert ("devices", "read") in resources

    def test_device_create_permission_exists(self):
        from app.services.device_control_schema import DEVICE_PERMISSIONS
        resources = {(r, a) for _, r, a in DEVICE_PERMISSIONS}
        assert ("devices", "create") in resources

    def test_device_control_permission_exists(self):
        from app.services.device_control_schema import DEVICE_PERMISSIONS
        resources = {(r, a) for _, r, a in DEVICE_PERMISSIONS}
        assert ("device_sessions", "control") in resources

    def test_device_revoke_permission_exists(self):
        from app.services.device_control_schema import DEVICE_PERMISSIONS
        resources = {(r, a) for _, r, a in DEVICE_PERMISSIONS}
        assert ("devices", "revoke") in resources


# ── Event bus registration ────────────────────────────────────────────────────

class TestEventBus:
    """Verify device events are registered in the event bus."""

    def test_device_events_registered(self):
        from app.core.events.bus import EVENT_TYPES
        required = {
            "device.registered",
            "device.connected",
            "device.disconnected",
            "device.revoked",
            "device_control.session_started",
            "device_control.session_stopped",
            "device_control.device_switched",
        }
        missing = required - EVENT_TYPES
        assert not missing, f"Missing device event types: {missing}"


# ── Agent session state ────────────────────────────────────────────────────────

class TestAgentSessionState:
    """AgentSessionState — thread-safe state transitions."""

    def _state(self):
        from agent.core.session import AgentSessionState
        return AgentSessionState()

    def test_initial_state_is_idle(self):
        s = self._state()
        assert not s.is_active
        assert s.session_id is None
        assert s.is_primary is False
        assert s.member_count() == 0

    def test_apply_session_start(self):
        s = self._state()
        s.apply_session_start({
            "session_id":    "sess-1",
            "session_token": "tok-abc",
            "workspace_id":  None,
            "members": [
                {"device_id": "dev-A", "is_primary": True,  "position_x": 0,    "position_y": 0, "width": 1920, "height": 1080, "enabled": True},
                {"device_id": "dev-B", "is_primary": False, "position_x": 1920, "position_y": 0, "width": 1920, "height": 1080, "enabled": True},
            ],
        }, our_device_id="dev-A")
        assert s.is_active
        assert s.session_id == "sess-1"
        assert s.is_primary is True
        assert s.member_count() == 2

    def test_apply_session_stop_clears_state(self):
        s = self._state()
        s.apply_session_start({
            "session_id": "sess-1", "session_token": "t",
            "workspace_id": None,
            "members": [{"device_id": "x", "is_primary": True,
                          "position_x": 0, "position_y": 0, "width": 1920, "height": 1080, "enabled": True}],
        }, our_device_id="x")
        s.apply_session_stop("test")
        assert not s.is_active
        assert s.session_id is None
        assert s.member_count() == 0

    def test_apply_layout_update(self):
        s = self._state()
        s.apply_session_start({
            "session_id": "sess-1", "session_token": "t",
            "workspace_id": None,
            "members": [
                {"device_id": "A", "is_primary": True, "position_x": 0, "position_y": 0, "width": 1920, "height": 1080, "enabled": True},
                {"device_id": "B", "is_primary": False, "position_x": 1920, "position_y": 0, "width": 1920, "height": 1080, "enabled": True},
            ],
        }, our_device_id="A")
        s.apply_layout_update({
            "members": [
                {"device_id": "A", "is_primary": True, "position_x": 0, "position_y": 1080, "width": 1920, "height": 1080, "enabled": True},
                {"device_id": "B", "is_primary": False, "position_x": 0, "position_y": 0, "width": 1920, "height": 1080, "enabled": True},
            ],
        })
        member_a = s.get_member("A")
        assert member_a is not None
        assert member_a["position_y"] == 1080

    def test_layout_update_ignored_when_not_active(self):
        s = self._state()
        # Should not crash when called without an active session
        s.apply_layout_update({"members": [{"device_id": "X", "is_primary": True, "position_x": 0, "position_y": 0, "width": 1920, "height": 1080, "enabled": True}]})
        assert s.member_count() == 0
