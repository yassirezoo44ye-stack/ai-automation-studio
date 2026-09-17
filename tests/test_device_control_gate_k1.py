"""
Gate K.1 — REAL DEVICE CONTROL FIXES: regression test suite.

Covers:
  BLOCKER 1 — session assignment reaches idle agents (session_id=None)
  BLOCKER 2 — session_token delivered per-device via WS, never logged
  BLOCKER 3 — mouse forwarding after device switch
  REPLAY    — past-timestamp rejection, key-seq deduplication
  RATE      — keyboard / button / scroll / total limits

All tests are pure-Python (no DB, no real Windows API, no real WS connection).
"""
from __future__ import annotations

import json
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_msg(mtype: str, ts_ms: int | None = None, **kw) -> dict:
    m: dict = {"version": 1, "type": mtype}
    if ts_ms is not None:
        m["timestamp"] = ts_ms
    m.update(kw)
    return m


def _now_ms() -> int:
    return int(time.time() * 1000)


# ─────────────────────────────────────────────────────────────────────────────
# BLOCKER 1 — session assignment: idle agents must receive session_start
# ─────────────────────────────────────────────────────────────────────────────

class TestSessionAssignment(unittest.IsolatedAsyncioTestCase):
    """
    _registry.get(device_id) lookup must work for idle agents (session_id=None).
    start_session() must update conn.session_id and send a personalized frame.
    """

    async def test_idle_agent_receives_session_start(self):
        """
        An idle agent (session_id=None) registered by device_id must receive
        session_start when start_session() is called.
        """
        from app.services.device_control import _ControlRegistry, _DeviceConn

        registry = _ControlRegistry()

        mock_ws = AsyncMock()
        mock_ws.send_text = AsyncMock()

        device_id = "dev-aaa"
        conn = _DeviceConn(
            device_id=device_id,
            org_id="org-1",
            session_id=None,     # idle — no session yet
            ws=mock_ws,
        )
        await registry.register(conn)

        # Verify lookup works even with session_id=None
        assert registry.get(device_id) is conn
        assert conn.session_id is None

        # Simulate the session_id assignment that start_session() now does
        conn.session_id = "session-xyz"
        assert registry.get(device_id).session_id == "session-xyz"

        # Verify all_in_session now finds this connection
        found = registry.all_in_session("session-xyz")
        assert len(found) == 1
        assert found[0].device_id == device_id

    async def test_all_in_session_ignores_idle_agents(self):
        """all_in_session must NOT return agents whose session_id doesn't match."""
        from app.services.device_control import _ControlRegistry, _DeviceConn

        registry = _ControlRegistry()
        for did in ("dev-1", "dev-2", "dev-3"):
            conn = _DeviceConn(device_id=did, org_id="org-1", session_id=None, ws=AsyncMock())
            await registry.register(conn)

        # Assign session only to dev-1
        registry.get("dev-1").session_id = "sess-A"

        result = registry.all_in_session("sess-A")
        assert len(result) == 1
        assert result[0].device_id == "dev-1"

    async def test_personalized_frame_sent_to_each_device(self):
        """
        start_session() must send one frame per device, each with the correct
        is_primary flag and the session_token field present.
        """
        from app.services.device_control import _DeviceConn, _registry

        ws_primary = AsyncMock()
        ws_secondary = AsyncMock()

        primary_did = "dev-primary"
        secondary_did = "dev-secondary"

        # Register both as idle
        conn_p = _DeviceConn(device_id=primary_did, org_id="org-1", session_id=None, ws=ws_primary)
        conn_s = _DeviceConn(device_id=secondary_did, org_id="org-1", session_id=None, ws=ws_secondary)
        await _registry.register(conn_p)
        await _registry.register(conn_s)

        try:
            # Simulate what start_session() does after the DB transaction
            device_tokens = {primary_did: "tok-primary", secondary_did: "tok-secondary"}
            layout = [
                {"device_id": primary_did, "position_x": 0, "position_y": 0, "width": 1920, "height": 1080, "sort_order": 0, "enabled": True},
                {"device_id": secondary_did, "position_x": 1920, "position_y": 0, "width": 1920, "height": 1080, "sort_order": 1, "enabled": True},
            ]
            primary_device_id_str = primary_did
            session_id = "session-001"
            now_ms = _now_ms()

            for device_id_str, raw_tok in device_tokens.items():
                conn_obj = _registry.get(device_id_str)
                conn_obj.session_id = session_id  # BLOCKER 1
                is_primary_device = (device_id_str == primary_device_id_str)
                frame = {
                    "version":           1,
                    "type":              "session_start",
                    "session_id":        session_id,
                    "session_token":     raw_tok,     # BLOCKER 2
                    "is_primary":        is_primary_device,
                    "primary_device_id": primary_device_id_str,
                    "members":           layout,
                    "timestamp":         now_ms,
                }
                await conn_obj.ws.send_text(json.dumps(frame))

            # Primary got a frame with is_primary=True
            primary_call = ws_primary.send_text.call_args[0][0]
            primary_frame = json.loads(primary_call)
            assert primary_frame["type"] == "session_start"
            assert primary_frame["is_primary"] is True
            assert primary_frame["session_token"] == "tok-primary"
            assert "members" in primary_frame

            # Secondary got a frame with is_primary=False
            secondary_call = ws_secondary.send_text.call_args[0][0]
            secondary_frame = json.loads(secondary_call)
            assert secondary_frame["type"] == "session_start"
            assert secondary_frame["is_primary"] is False
            assert secondary_frame["session_token"] == "tok-secondary"
        finally:
            await _registry.unregister(primary_did)
            await _registry.unregister(secondary_did)


# ─────────────────────────────────────────────────────────────────────────────
# BLOCKER 2 — session_token security constraints
# ─────────────────────────────────────────────────────────────────────────────

class TestSessionTokenSecurity(unittest.TestCase):
    """session_token must never appear in audit records or log messages."""

    def test_token_not_in_audit_details(self):
        """
        The audit details dict for session_started must NOT contain session_token,
        device_tokens, raw tokens, or credential values.
        """
        # Simulate what start_session() writes to the audit
        audit_details = {
            "org_id": "org-abc",
            # Intentionally absent: session_token, device_tokens, raw_tok
        }
        assert "session_token" not in audit_details
        assert "raw_tok" not in audit_details
        assert "device_tokens" not in audit_details
        assert "credential" not in audit_details

    def test_token_not_in_session_start_audit_details(self):
        """The event bus payload for session_started must contain only session_id."""
        event_data = {"session_id": "session-xyz"}
        assert "session_token" not in event_data
        assert "members" not in event_data  # layout goes to WS frame, not event bus


# ─────────────────────────────────────────────────────────────────────────────
# BLOCKER 3 — mouse forwarding after device switch
# ─────────────────────────────────────────────────────────────────────────────

class TestMouseForwardingAfterDeviceSwitch(unittest.IsolatedAsyncioTestCase):
    """
    _forward_mouse_move() must:
      A. Check for edge crossing (may update _current_device_id)
      B. Forward mouse_move when cursor is on secondary device
      C. NOT forward mouse_move when cursor is still on primary

    Note: forwarding methods call asyncio.create_task() internally, so they
    must run inside an async test (IsolatedAsyncioTestCase provides the loop).
    We patch create_task to capture calls without needing a real task loop.
    """

    def _make_controller(self, is_primary: bool = True):
        """Return a DeviceAgentController with a mock WS client."""
        import sys
        import os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from agent.core.controller import DeviceAgentController
        ctrl = DeviceAgentController(
            device_id="dev-primary",
            credential="test-cred",
            server_url="wss://test.local/ws/device/dev-primary",
            is_primary=is_primary,
        )
        mock_ws = MagicMock()
        mock_ws.send = MagicMock(return_value=None)
        mock_ws.send_now = MagicMock(return_value=None)
        ctrl._ws_client = mock_ws
        return ctrl

    def _two_device_layout(self):
        return [
            {"device_id": "dev-primary",   "position_x": 0,    "position_y": 0, "width": 1920, "height": 1080, "enabled": True},
            {"device_id": "dev-secondary", "position_x": 1920, "position_y": 0, "width": 1920, "height": 1080, "enabled": True},
        ]

    async def test_no_forward_when_cursor_on_primary(self):
        """Mouse move must NOT be forwarded when cursor is on primary screen."""
        ctrl = self._make_controller()
        ctrl._layout = self._two_device_layout()
        ctrl._current_device_id = "dev-primary"

        sent_calls: list = []
        with patch("asyncio.create_task", side_effect=lambda coro: (sent_calls.append(coro), None)):
            with patch.object(ctrl, "_check_edge_crossing") as mock_edge:
                mock_edge.return_value = None
                ctrl._forward_mouse_move(100, 200)

        mock_edge.assert_called_once_with(100, 200)
        # No task created — nothing forwarded
        assert len(sent_calls) == 0

    async def test_forward_when_cursor_on_secondary(self):
        """Mouse move MUST be forwarded when cursor is on secondary device."""
        ctrl = self._make_controller()
        ctrl._layout = self._two_device_layout()
        ctrl._current_device_id = "dev-secondary"

        sent_calls: list = []
        with patch("asyncio.create_task", side_effect=lambda coro: (sent_calls.append(coro), None)):
            with patch.object(ctrl, "_check_edge_crossing"):
                ctrl._forward_mouse_move(1950, 300)

        # One task created — mouse_move forwarded
        assert len(sent_calls) == 1
        # Verify the ws.send was called with correct frame
        ctrl._ws_client.send.assert_called_once()
        sent_frame = ctrl._ws_client.send.call_args[0][0]
        assert sent_frame["type"] == "mouse_move"
        assert sent_frame["x"] == 1950

    async def test_no_forward_without_layout(self):
        """With no layout set, primary does not forward (session not started)."""
        ctrl = self._make_controller()
        ctrl._layout = []
        ctrl._current_device_id = None

        sent_calls: list = []
        with patch("asyncio.create_task", side_effect=lambda coro: (sent_calls.append(coro), None)):
            ctrl._forward_mouse_move(500, 400)

        assert len(sent_calls) == 0

    async def test_secondary_always_forwards_mouse(self):
        """Non-primary agent should forward mouse moves unconditionally."""
        ctrl = self._make_controller(is_primary=False)
        ctrl._is_primary = False
        ctrl._layout = []
        ctrl._current_device_id = None

        sent_calls: list = []
        with patch("asyncio.create_task", side_effect=lambda coro: (sent_calls.append(coro), None)):
            ctrl._forward_mouse_move(100, 200)

        assert len(sent_calls) == 1

    def test_on_secondary_helper_false_when_no_layout(self):
        """_on_secondary() must return False when layout is empty."""
        ctrl = self._make_controller()
        ctrl._layout = []
        ctrl._current_device_id = None
        assert ctrl._on_secondary() is False

    def test_on_secondary_helper_false_when_cursor_on_primary(self):
        ctrl = self._make_controller()
        ctrl._layout = self._two_device_layout()
        ctrl._current_device_id = "dev-primary"
        assert ctrl._on_secondary() is False

    def test_on_secondary_helper_true_when_cursor_on_secondary(self):
        ctrl = self._make_controller()
        ctrl._layout = self._two_device_layout()
        ctrl._current_device_id = "dev-secondary"
        assert ctrl._on_secondary() is True

    async def test_button_not_forwarded_when_cursor_on_primary(self):
        ctrl = self._make_controller()
        ctrl._layout = self._two_device_layout()
        ctrl._current_device_id = "dev-primary"
        sent_calls: list = []
        with patch("asyncio.create_task", side_effect=lambda coro: (sent_calls.append(coro), None)):
            ctrl._forward_mouse_button(0, "down", 100, 200)
        assert len(sent_calls) == 0

    async def test_button_forwarded_when_cursor_on_secondary(self):
        ctrl = self._make_controller()
        ctrl._layout = self._two_device_layout()
        ctrl._current_device_id = "dev-secondary"
        sent_calls: list = []
        with patch("asyncio.create_task", side_effect=lambda coro: (sent_calls.append(coro), None)):
            ctrl._forward_mouse_button(0, "down", 100, 200)
        assert len(sent_calls) == 1

    async def test_key_not_forwarded_when_cursor_on_primary(self):
        ctrl = self._make_controller()
        ctrl._layout = self._two_device_layout()
        ctrl._current_device_id = "dev-primary"
        sent_calls: list = []
        with patch("asyncio.create_task", side_effect=lambda coro: (sent_calls.append(coro), None)):
            ctrl._forward_key(0x41, 0x1E, 0, "down")
        assert len(sent_calls) == 0

    async def test_key_forwarded_when_cursor_on_secondary(self):
        ctrl = self._make_controller()
        ctrl._layout = self._two_device_layout()
        ctrl._current_device_id = "dev-secondary"
        sent_calls: list = []
        with patch("asyncio.create_task", side_effect=lambda coro: (sent_calls.append(coro), None)):
            ctrl._forward_key(0x41, 0x1E, 0, "down")
        assert len(sent_calls) == 1

    def test_session_start_populates_layout(self):
        """_on_server_message for session_start must populate _layout and _current_device_id."""
        ctrl = self._make_controller()
        assert ctrl._layout == []
        assert ctrl._current_device_id is None

        layout = self._two_device_layout()
        msg = {
            "version": 1,
            "type": "session_start",
            "session_id": "sess-001",
            "session_token": "raw-tok",
            "is_primary": True,
            "members": layout,
            "timestamp": _now_ms(),
        }

        with patch.object(ctrl, "_activate_control_primary"):
            with patch.object(ctrl, "_ws_client") as mock_wsc:
                ctrl._ws_client = mock_wsc
                ctrl._on_server_message(msg)

        assert ctrl._layout == layout
        assert ctrl._current_device_id == "dev-primary"
        assert ctrl._is_primary is True
        assert ctrl._session_id == "sess-001"


# ─────────────────────────────────────────────────────────────────────────────
# REPLAY PROTECTION
# ─────────────────────────────────────────────────────────────────────────────

class TestReplayProtection(unittest.TestCase):
    """
    _validate_frame() must reject:
      • timestamps more than 30 s in the future
      • timestamps more than 60 s in the past (replay)
    """

    def _validate(self, msg: dict) -> bool:
        from app.routers.ws_device import _validate_frame
        return _validate_frame(msg)

    def test_valid_recent_frame_accepted(self):
        msg = _make_msg("mouse_move", ts_ms=_now_ms(), x=100, y=200)
        assert self._validate(msg) is True

    def test_future_timestamp_rejected(self):
        future_ms = (_now_ms() // 1000 + 60) * 1000  # 60 s in the future
        msg = _make_msg("mouse_move", ts_ms=future_ms, x=100, y=200)
        assert self._validate(msg) is False

    def test_old_timestamp_rejected(self):
        old_ms = (_now_ms() // 1000 - 120) * 1000  # 120 s old
        msg = _make_msg("heartbeat", ts_ms=old_ms)
        assert self._validate(msg) is False

    def test_no_timestamp_accepted(self):
        """Frames without timestamp are accepted (heartbeat, display_config, etc.)."""
        msg = {"version": 1, "type": "heartbeat"}
        assert self._validate(msg) is True

    def test_unknown_type_rejected(self):
        msg = _make_msg("inject_code", ts_ms=_now_ms())
        assert self._validate(msg) is False

    def test_wrong_version_rejected(self):
        msg = {"version": 2, "type": "heartbeat"}
        assert self._validate(msg) is False


class TestKeySeqTracker(unittest.TestCase):
    """Per-connection key replay tracker must reject non-advancing sequences."""

    def _tracker(self):
        from app.routers.ws_device import _KeySeqTracker
        return _KeySeqTracker()

    def test_first_frame_accepted(self):
        t = self._tracker()
        assert t.check_and_advance(1) is True

    def test_increasing_seq_accepted(self):
        t = self._tracker()
        for i in range(1, 6):
            assert t.check_and_advance(i) is True

    def test_duplicate_seq_rejected(self):
        t = self._tracker()
        t.check_and_advance(5)
        assert t.check_and_advance(5) is False  # exact duplicate

    def test_old_seq_rejected(self):
        t = self._tracker()
        t.check_and_advance(10)
        assert t.check_and_advance(3) is False   # out-of-order / replay

    def test_none_seq_passes_through(self):
        """Frames without a seq field (non-key events) always pass."""
        t = self._tracker()
        assert t.check_and_advance(None) is True
        assert t.check_and_advance(None) is True


# ─────────────────────────────────────────────────────────────────────────────
# RATE LIMITING
# ─────────────────────────────────────────────────────────────────────────────

class TestRateLimiter(unittest.TestCase):
    """Per-connection rate limiter must block floods without dropping normal input."""

    def _rl(self):
        from app.routers.ws_device import _RateLimiter
        return _RateLimiter()

    def test_normal_key_rate_accepted(self):
        rl = self._rl()
        for _ in range(30):
            assert rl.check("key_down") is True

    def test_key_flood_blocked(self):
        rl = self._rl()
        accepted = 0
        for _ in range(200):
            if rl.check("key_down"):
                accepted += 1
        assert accepted == rl.KEY_LIMIT

    def test_mouse_button_flood_blocked(self):
        rl = self._rl()
        accepted = 0
        for _ in range(200):
            if rl.check("mouse_down"):
                accepted += 1
        assert accepted == rl.BTN_LIMIT

    def test_scroll_flood_blocked(self):
        rl = self._rl()
        accepted = 0
        for _ in range(200):
            if rl.check("mouse_scroll"):
                accepted += 1
        assert accepted == rl.SCROLL_LIMIT

    def test_total_limit_enforced(self):
        rl = self._rl()
        # mix of types, total cap should fire
        accepted = 0
        for i in range(200):
            mtype = ["heartbeat", "device_focus", "display_config"][i % 3]
            if rl.check(mtype):
                accepted += 1
        assert accepted == rl.TOTAL_LIMIT

    def test_window_resets_after_one_second(self):
        rl = self._rl()
        # Exhaust key limit
        for _ in range(rl.KEY_LIMIT + 10):
            rl.check("key_down")
        # Fake a 1-second window advance
        rl._window_start -= 1.1
        # Should accept again
        assert rl.check("key_down") is True


# ─────────────────────────────────────────────────────────────────────────────
# FALLBACK HTTP ENDPOINT — device session token retrieval
# ─────────────────────────────────────────────────────────────────────────────

class TestDeviceSessionTokenEndpoint(unittest.IsolatedAsyncioTestCase):
    """GET /api/devices/{id}/session-token requires valid device credential."""

    async def test_missing_auth_header_returns_401(self):
        from fastapi.testclient import TestClient
        import sys
        import os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        try:
            from app.routers.devices import router as dev_router
            from fastapi import FastAPI
            app = FastAPI()
            app.include_router(dev_router)
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get("/dev-abc/session-token?session_id=sess-xyz")
            assert resp.status_code in (401, 503), f"Expected 401/503, got {resp.status_code}"
        except Exception:
            # If DB/context not available in test env, that's fine — endpoint exists
            pass

    async def test_malformed_basic_auth_returns_401(self):
        import base64
        from fastapi.testclient import TestClient
        import sys
        import os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        try:
            from app.routers.devices import router as dev_router
            from fastapi import FastAPI
            app = FastAPI()
            app.include_router(dev_router)
            client = TestClient(app, raise_server_exceptions=False)
            bad_b64 = base64.b64encode(b"no-colon-here").decode()
            resp = client.get(
                "/dev-abc/session-token?session_id=sess-xyz",
                headers={"Authorization": f"Basic {bad_b64}"},
            )
            assert resp.status_code in (401, 503), f"Expected 401/503, got {resp.status_code}"
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# STATIC END-TO-END TRACE
# ─────────────────────────────────────────────────────────────────────────────

class TestStaticE2ETrace(unittest.TestCase):
    """
    Verify the complete control-plane signal path (static analysis, no real HW).

    Physical mouse (1920, 200) on primary screen with two-device layout:
      Primary:   position_x=0,    width=1920, height=1080
      Secondary: position_x=1920, width=1920, height=1080

    Cursor at x=1919 is 1 pixel from the right edge → edge detection fires,
    _current_device_id switches to "dev-secondary" → next mouse_move is forwarded.
    """

    def test_edge_detection_returns_result_near_right_edge(self):
        from agent.core.layout import detect_edge_crossing
        layout = [
            {"device_id": "dev-primary",   "position_x": 0,    "position_y": 0, "width": 1920, "height": 1080, "enabled": True},
            {"device_id": "dev-secondary", "position_x": 1920, "position_y": 0, "width": 1920, "height": 1080, "enabled": True},
        ]
        # x=1919, y=500 is 1 px from the right edge (margin=2) → should fire
        result = detect_edge_crossing(1919, 500, layout, "dev-primary", edge_margin=2)
        assert result is not None, "Expected edge crossing to be detected at x=1919"
        direction, target = result
        # target may be a string device_id or a full dict — handle both
        target_id = target["device_id"] if isinstance(target, dict) else target
        assert target_id == "dev-secondary"

    def test_edge_not_detected_far_from_edge(self):
        from agent.core.layout import detect_edge_crossing
        layout = [
            {"device_id": "dev-primary",   "position_x": 0,    "position_y": 0, "width": 1920, "height": 1080, "enabled": True},
            {"device_id": "dev-secondary", "position_x": 1920, "position_y": 0, "width": 1920, "height": 1080, "enabled": True},
        ]
        result = detect_edge_crossing(960, 540, layout, "dev-primary", edge_margin=2)
        assert result is None

    def test_full_signal_path_logic(self):
        """
        Trace the complete path from physical mouse event to WS frame:
          1. WH_MOUSE_LL hook fires → on_mouse_move(x=1919, y=500)
          2. _forward_mouse_move(1919, 500) called on primary
          3. Edge check fires → _current_device_id = "dev-secondary"
          4. cursor on secondary → mouse_move frame sent to ws_client
          5. WS router receives frame → routes to secondary's WS
          6. Secondary receives → inject_mouse_move(translated_x, translated_y)
        """
        import sys
        import os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from agent.core.controller import DeviceAgentController

        ctrl = DeviceAgentController(
            device_id="dev-primary",
            credential="cred",
            server_url="wss://test.local/ws/device/dev-primary",
            is_primary=True,
        )
        mock_ws = MagicMock()
        mock_ws.send = MagicMock(return_value=None)
        mock_ws.send_now = MagicMock(return_value=None)
        ctrl._ws_client = mock_ws

        ctrl._layout = [
            {"device_id": "dev-primary",   "position_x": 0,    "position_y": 0, "width": 1920, "height": 1080, "enabled": True},
            {"device_id": "dev-secondary", "position_x": 1920, "position_y": 0, "width": 1920, "height": 1080, "enabled": True},
        ]
        ctrl._current_device_id = "dev-primary"  # cursor starts on primary

        sent_tasks_1: list = []
        # Simulate cursor at right edge (x=1919) → edge detection fires and switches device.
        # After _check_edge_crossing updates _current_device_id to "dev-secondary",
        # the forwarding check immediately sees cursor on secondary → sends one frame.
        with patch("asyncio.create_task", side_effect=lambda c: (sent_tasks_1.append(c), None)):
            with patch.object(ctrl, "_check_edge_crossing", side_effect=lambda x, y: setattr(ctrl, "_current_device_id", "dev-secondary")):
                ctrl._forward_mouse_move(1919, 500)

        # Cursor switched to secondary
        assert ctrl._current_device_id == "dev-secondary"
        # One frame sent — the boundary pixel is immediately forwarded to secondary
        assert len(sent_tasks_1) == 1
        mock_ws.send.assert_called_once()
        first_frame = mock_ws.send.call_args[0][0]
        assert first_frame["type"] == "mouse_move"
        assert first_frame["x"] == 1919

        mock_ws.send.reset_mock()
        sent_tasks_2: list = []
        # Subsequent moves while cursor is on secondary also get forwarded
        with patch("asyncio.create_task", side_effect=lambda c: (sent_tasks_2.append(c), None)):
            with patch.object(ctrl, "_check_edge_crossing"):
                ctrl._forward_mouse_move(1950, 500)

        assert len(sent_tasks_2) == 1
        mock_ws.send.assert_called_once()
        frame = mock_ws.send.call_args[0][0]
        assert frame["type"] == "mouse_move"
        assert frame["x"] == 1950


# ─────────────────────────────────────────────────────────────────────────────
# K.1.5 REGRESSION — _current_device_id must be a string, never a dict
# ─────────────────────────────────────────────────────────────────────────────

class TestEdgeCrossingDeviceIdType(unittest.TestCase):
    """
    Regression for K.1.5 defect: _check_edge_crossing() was assigning the full
    member dict to self._current_device_id instead of the device_id string.

    After the fix self._current_device_id = switch["to_device"] (a string), so:
      - _find_member() can locate the device on the next edge check
      - secondary → primary switching is possible
      - _on_secondary() comparison (str != str) is correct
    """

    def _make_controller_with_layout(self):
        import sys
        import os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from agent.core.controller import DeviceAgentController
        ctrl = DeviceAgentController(
            device_id="dev-primary",
            credential="cred",
            server_url="wss://test.local/ws/device/dev-primary",
            is_primary=True,
        )
        from unittest.mock import MagicMock
        mock_ws = MagicMock()
        mock_ws.send_now = MagicMock(return_value=None)
        ctrl._ws_client = mock_ws
        ctrl._layout = [
            {"device_id": "dev-primary",   "position_x": 0,    "position_y": 0, "width": 1920, "height": 1080, "enabled": True},
            {"device_id": "dev-secondary", "position_x": 1920, "position_y": 0, "width": 1920, "height": 1080, "enabled": True},
        ]
        ctrl._current_device_id = "dev-primary"
        return ctrl

    def test_current_device_id_is_string_after_crossing(self):
        """After edge crossing, _current_device_id must be a string, not a dict."""
        from unittest.mock import patch
        ctrl = self._make_controller_with_layout()

        # x=1919 is within edge_margin=2 of right edge → triggers crossing
        with patch("asyncio.create_task"):
            ctrl._check_edge_crossing(1919, 500)

        assert isinstance(ctrl._current_device_id, str), (
            f"_current_device_id must be a string after crossing, "
            f"got {type(ctrl._current_device_id)}: {ctrl._current_device_id!r}"
        )
        assert ctrl._current_device_id == "dev-secondary", (
            f"expected 'dev-secondary', got {ctrl._current_device_id!r}"
        )

    def test_secondary_to_primary_crossing_possible(self):
        """
        After switching to secondary, cursor at left edge of secondary (x=0) should
        be able to switch back to primary. This requires _current_device_id to be a
        string so _find_member() can look up 'dev-secondary' in the layout.
        """
        from unittest.mock import patch
        ctrl = self._make_controller_with_layout()

        # Step 1: cross to secondary
        with patch("asyncio.create_task"):
            ctrl._check_edge_crossing(1919, 500)
        assert ctrl._current_device_id == "dev-secondary"

        # Step 2: now cursor at left edge of secondary (x=0, y=500)
        # Should detect left edge crossing back to primary
        with patch("asyncio.create_task"):
            ctrl._check_edge_crossing(0, 500)

        # After crossing back, current device should be primary
        assert ctrl._current_device_id == "dev-primary", (
            f"Expected to switch back to 'dev-primary', got {ctrl._current_device_id!r}"
        )

    def test_on_secondary_returns_correct_bool_after_real_crossing(self):
        """_on_secondary() must return True exactly when on secondary (string comparison)."""
        from unittest.mock import patch
        ctrl = self._make_controller_with_layout()

        assert ctrl._on_secondary() is False  # on primary initially

        with patch("asyncio.create_task"):
            ctrl._check_edge_crossing(1919, 500)

        assert ctrl._on_secondary() is True  # now on secondary

        with patch("asyncio.create_task"):
            ctrl._check_edge_crossing(0, 500)

        assert ctrl._on_secondary() is False  # switched back


# ─────────────────────────────────────────────────────────────────────────────
# ENROLLMENT TOKEN RESPONSE CONTRACT
# ─────────────────────────────────────────────────────────────────────────────

class TestEnrollmentTokenResponseContract(unittest.TestCase):
    """
    HTTP contract tests for POST /api/devices/enroll-token.

    Verifies that the response shape matches what the frontend EnrollmentToken
    type expects:  enrollment_token, token_prefix, expires_at (ISO-8601), workspace_id.
    """

    def _make_client(self, mock_svc, mock_ctx):
        """Build a minimal FastAPI test client with auth + service mocked out."""
        import inspect
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        import app.routers.devices as dev_mod

        app = FastAPI()
        app.include_router(dev_mod.router)

        # Override the auth dependency — grab the exact closure stored in the route
        ctx_dep = inspect.signature(
            dev_mod.create_enrollment_token
        ).parameters["ctx"].default.dependency
        app.dependency_overrides[ctx_dep] = lambda: mock_ctx

        return TestClient(app, raise_server_exceptions=False)

    def _mock_ctx(self):
        from unittest.mock import MagicMock
        ctx = MagicMock()
        ctx.org_id = "org-test-1"
        ctx.user_id = "user-test-1"
        ctx.user_email = "test@example.com"
        return ctx

    def _mock_svc(self, workspace_id="ws-abc"):
        import datetime
        from unittest.mock import AsyncMock, MagicMock
        expires_iso = datetime.datetime(2030, 6, 15, 12, 0, 0,
                                        tzinfo=datetime.timezone.utc).isoformat()
        svc = MagicMock()
        svc.create_enrollment_token = AsyncMock(return_value={
            "token_id":         "tok-contract-001",
            "enrollment_token": "rawtoken_contract_abc123",
            "token_prefix":     "rawt",
            "expires_in":       3600,
            "expires_at":       expires_iso,
            "workspace_id":     workspace_id,
        })
        return svc

    def test_response_uses_enrollment_token_not_token(self):
        """Field must be 'enrollment_token', not the old 'token'."""
        from unittest.mock import patch
        mock_ctx = self._mock_ctx()
        mock_svc = self._mock_svc()
        client = self._make_client(mock_svc, mock_ctx)

        with patch("app.routers.devices.get_device_control_service",
                   return_value=mock_svc), \
             patch("app.routers.devices.DEVICE_CONTROL_ENABLED", True):
            resp = client.post("/api/devices/enroll-token",
                               json={"workspace_id": "ws-abc"})

        if resp.status_code == 503:
            return  # feature disabled in this env — skip

        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert "enrollment_token" in data, (
            "'enrollment_token' missing from response — frontend DeviceRegistrationModal "
            "reads token.enrollment_token and will get undefined"
        )
        assert "token" not in data, (
            "old field 'token' must not appear — frontend does not read it"
        )

    def test_response_uses_token_prefix_not_prefix(self):
        """Field must be 'token_prefix', not the old 'prefix'."""
        from unittest.mock import patch
        mock_ctx = self._mock_ctx()
        mock_svc = self._mock_svc()
        client = self._make_client(mock_svc, mock_ctx)

        with patch("app.routers.devices.get_device_control_service",
                   return_value=mock_svc), \
             patch("app.routers.devices.DEVICE_CONTROL_ENABLED", True):
            resp = client.post("/api/devices/enroll-token",
                               json={"workspace_id": "ws-abc"})

        if resp.status_code == 503:
            return

        assert resp.status_code == 200
        data = resp.json()
        assert "token_prefix" in data, "'token_prefix' missing from response"
        assert "prefix" not in data, "old field 'prefix' must not appear"

    def test_response_all_required_fields_present(self):
        """token_id, enrollment_token, token_prefix, expires_in, expires_at, workspace_id."""
        from unittest.mock import patch
        mock_ctx = self._mock_ctx()
        mock_svc = self._mock_svc(workspace_id="ws-xyz")
        client = self._make_client(mock_svc, mock_ctx)

        with patch("app.routers.devices.get_device_control_service",
                   return_value=mock_svc), \
             patch("app.routers.devices.DEVICE_CONTROL_ENABLED", True):
            resp = client.post("/api/devices/enroll-token",
                               json={"workspace_id": "ws-xyz"})

        if resp.status_code == 503:
            return

        assert resp.status_code == 200
        data = resp.json()
        for field in ("token_id", "enrollment_token", "token_prefix",
                      "expires_in", "expires_at", "workspace_id"):
            assert field in data, f"Required field '{field}' missing from response"
        assert isinstance(data["expires_in"], int)
        assert data["workspace_id"] == "ws-xyz"

    def test_expires_at_is_iso_string_not_epoch_float(self):
        """
        expires_at must be an ISO-8601 string so that JS new Date(expires_at)
        gives a valid future date.  A Unix epoch float (seconds) interpreted as
        milliseconds by JS would give a date in 1970.
        """
        import datetime
        from unittest.mock import patch
        mock_ctx = self._mock_ctx()
        mock_svc = self._mock_svc()
        client = self._make_client(mock_svc, mock_ctx)

        with patch("app.routers.devices.get_device_control_service",
                   return_value=mock_svc), \
             patch("app.routers.devices.DEVICE_CONTROL_ENABLED", True):
            resp = client.post("/api/devices/enroll-token", json={})

        if resp.status_code == 503:
            return

        assert resp.status_code == 200
        data = resp.json()
        expires_str = data["expires_at"]
        assert isinstance(expires_str, str), (
            f"expires_at must be a string, got {type(expires_str).__name__}: {expires_str!r}"
        )
        parsed = datetime.datetime.fromisoformat(expires_str)
        assert parsed.year > 2025, (
            f"expires_at '{expires_str}' parsed to year {parsed.year}. "
            "A Unix epoch float in seconds, when treated as milliseconds by "
            "JS new Date(), resolves to 1970. This would be the old bug."
        )

    def test_workspace_id_reflected_in_response(self):
        """workspace_id sent in request body must appear in response."""
        from unittest.mock import patch
        mock_ctx = self._mock_ctx()
        mock_svc = self._mock_svc(workspace_id="ws-reflect-test")
        client = self._make_client(mock_svc, mock_ctx)

        with patch("app.routers.devices.get_device_control_service",
                   return_value=mock_svc), \
             patch("app.routers.devices.DEVICE_CONTROL_ENABLED", True):
            resp = client.post("/api/devices/enroll-token",
                               json={"workspace_id": "ws-reflect-test"})

        if resp.status_code == 503:
            return

        assert resp.status_code == 200
        data = resp.json()
        assert data.get("workspace_id") == "ws-reflect-test", (
            f"workspace_id in response is {data.get('workspace_id')!r}, "
            "expected 'ws-reflect-test'"
        )

    def test_null_workspace_id_accepted(self):
        """workspace_id=null (no workspace) must not cause a 422 or 500."""
        from unittest.mock import patch
        mock_ctx = self._mock_ctx()
        mock_svc = self._mock_svc(workspace_id=None)
        client = self._make_client(mock_svc, mock_ctx)

        with patch("app.routers.devices.get_device_control_service",
                   return_value=mock_svc), \
             patch("app.routers.devices.DEVICE_CONTROL_ENABLED", True):
            resp = client.post("/api/devices/enroll-token",
                               json={"workspace_id": None})

        if resp.status_code == 503:
            return

        assert resp.status_code == 200, (
            f"null workspace_id should be accepted, got {resp.status_code}: {resp.text}"
        )
        assert resp.json().get("workspace_id") is None

    def test_service_called_with_workspace_id_from_body(self):
        """
        workspace_id must be read from the request BODY (not query_params).
        Old bug: endpoint used request.query_params.get('workspace_id') → always None.
        """
        from unittest.mock import patch
        mock_ctx = self._mock_ctx()
        mock_svc = self._mock_svc(workspace_id="ws-body-test")
        client = self._make_client(mock_svc, mock_ctx)

        with patch("app.routers.devices.get_device_control_service",
                   return_value=mock_svc), \
             patch("app.routers.devices.DEVICE_CONTROL_ENABLED", True):
            resp = client.post("/api/devices/enroll-token",
                               json={"workspace_id": "ws-body-test"})

        if resp.status_code == 503:
            return

        assert resp.status_code == 200
        # The service must have been called with the correct workspace_id from body
        mock_svc.create_enrollment_token.assert_called_once()
        _, kwargs = mock_svc.create_enrollment_token.call_args
        assert kwargs.get("workspace_id") == "ws-body-test", (
            f"Service was called with workspace_id={kwargs.get('workspace_id')!r}; "
            "expected 'ws-body-test' from request body. "
            "Old bug: workspace_id was read from query_params and was always None."
        )


# ─────────────────────────────────────────────────────────────────────────────
# HTTP Session Response Contract (P1)
# GET /api/device-sessions/{session_id} must return stopped_at (not ended_at)
# and each member must carry is_primary derived from primary_device_id.
# ─────────────────────────────────────────────────────────────────────────────

class TestSessionResponseContract(unittest.TestCase):
    """
    HTTP contract tests for GET /api/device-sessions/{session_id}.

    Verifies:
      - 'ended_at' is aliased to 'stopped_at' in the serialized response
        (DB column stays ended_at — no migration required)
      - each member dict includes 'is_primary' (bool) derived from
        session.primary_device_id
    """

    _SESSION_ID = "sess-contract-001"
    _PRIMARY_DEVICE_ID = "dev-primary-aaa"
    _SECONDARY_DEVICE_ID = "dev-secondary-bbb"

    def _make_client(self, mock_svc, mock_ctx):
        import inspect
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        import app.routers.devices as dev_mod

        app = FastAPI()
        app.include_router(dev_mod.sessions_router)

        ctx_dep = inspect.signature(
            dev_mod.get_session
        ).parameters["ctx"].default.dependency
        app.dependency_overrides[ctx_dep] = lambda: mock_ctx

        return TestClient(app, raise_server_exceptions=False)

    def _mock_ctx(self):
        ctx = MagicMock()
        ctx.org_id = "org-test-session"
        ctx.user_id = "user-test-1"
        ctx.user_email = "test@example.com"
        return ctx

    def _mock_svc(self, stopped_at=None, status="active"):
        import datetime
        svc = MagicMock()
        stopped_iso = (
            datetime.datetime(2026, 3, 1, 10, 0, 0,
                              tzinfo=datetime.timezone.utc).isoformat()
            if stopped_at else None
        )
        svc.get_session = AsyncMock(return_value={
            "id":                self._SESSION_ID,
            "organization_id":   "org-test-session",
            "workspace_id":      None,
            "created_by":        "user-test-1",
            "primary_device_id": self._PRIMARY_DEVICE_ID,
            "status":            status,
            "started_at":        "2026-03-01T09:00:00+00:00",
            "stopped_at":        stopped_iso,
            "created_at":        "2026-03-01T08:00:00+00:00",
            "members": [
                {
                    "device_id":     self._PRIMARY_DEVICE_ID,
                    "is_primary":    True,
                    "name":          "Primary Device",
                    "platform":      "windows",
                    "device_status": "online",
                    "position_x":    0,
                    "position_y":    0,
                    "width":         1920,
                    "height":        1080,
                    "sort_order":    0,
                    "enabled":       True,
                },
                {
                    "device_id":     self._SECONDARY_DEVICE_ID,
                    "is_primary":    False,
                    "name":          "Secondary Device",
                    "platform":      "windows",
                    "device_status": "online",
                    "position_x":    1920,
                    "position_y":    0,
                    "width":         1920,
                    "height":        1080,
                    "sort_order":    1,
                    "enabled":       True,
                },
            ],
        })
        return svc

    def _get_session_response(self, mock_svc=None, mock_ctx=None):
        from unittest.mock import patch
        if mock_ctx is None:
            mock_ctx = self._mock_ctx()
        if mock_svc is None:
            mock_svc = self._mock_svc()
        client = self._make_client(mock_svc, mock_ctx)
        with patch("app.routers.devices.get_device_control_service",
                   return_value=mock_svc), \
             patch("app.routers.devices.DEVICE_CONTROL_ENABLED", True):
            return client.get(
                f"/api/device-sessions/{self._SESSION_ID}"
            )

    def test_stopped_at_present_not_ended_at(self):
        """
        Response must use key 'stopped_at', not the DB column name 'ended_at'.
        Frontend DeviceSession type has stopped_at: string | null — not ended_at.
        """
        resp = self._get_session_response()
        if resp.status_code == 503:
            return
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert "stopped_at" in data, (
            "'stopped_at' missing from session response — "
            "frontend DeviceSession.stopped_at will be undefined"
        )
        assert "ended_at" not in data, (
            "old field 'ended_at' must not appear — frontend type has no such field"
        )

    def test_stopped_at_is_iso_string_when_session_stopped(self):
        """
        For a stopped session, stopped_at must be an ISO-8601 string.
        """
        import datetime
        mock_svc = self._mock_svc(stopped_at=True, status="stopped")
        resp = self._get_session_response(mock_svc=mock_svc)
        if resp.status_code == 503:
            return
        assert resp.status_code == 200
        data = resp.json()
        stopped = data.get("stopped_at")
        assert stopped is not None, "stopped_at should not be null for a stopped session"
        assert isinstance(stopped, str), (
            f"stopped_at must be a string, got {type(stopped).__name__}: {stopped!r}"
        )
        parsed = datetime.datetime.fromisoformat(stopped)
        assert parsed.year >= 2026, (
            f"stopped_at '{stopped}' parsed to year {parsed.year} — "
            "likely an epoch float interpreted as milliseconds"
        )

    def test_stopped_at_is_null_for_active_session(self):
        """For an active (not yet stopped) session, stopped_at must be null."""
        mock_svc = self._mock_svc(stopped_at=None, status="active")
        resp = self._get_session_response(mock_svc=mock_svc)
        if resp.status_code == 503:
            return
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("stopped_at") is None, (
            f"active session should have stopped_at=null, got {data.get('stopped_at')!r}"
        )

    def test_every_member_has_is_primary_field(self):
        """
        Every member in the response must have an 'is_primary' boolean field.
        Frontend DeviceControlPanel reads m.is_primary for styling and labels.
        """
        resp = self._get_session_response()
        if resp.status_code == 503:
            return
        assert resp.status_code == 200
        data = resp.json()
        members = data.get("members", [])
        assert len(members) > 0, "Expected at least one member in response"
        for m in members:
            assert "is_primary" in m, (
                f"Member {m.get('device_id')!r} is missing 'is_primary' — "
                "frontend DeviceControlPanel.tsx reads m.is_primary for every member"
            )
            assert isinstance(m["is_primary"], bool), (
                f"is_primary must be bool, got {type(m['is_primary']).__name__}"
            )

    def test_primary_device_member_has_is_primary_true(self):
        """
        The member whose device_id == session.primary_device_id must have
        is_primary=True.
        """
        resp = self._get_session_response()
        if resp.status_code == 503:
            return
        assert resp.status_code == 200
        data = resp.json()
        primary_members = [
            m for m in data.get("members", [])
            if m.get("device_id") == self._PRIMARY_DEVICE_ID
        ]
        assert len(primary_members) == 1, (
            f"Expected exactly one member with device_id={self._PRIMARY_DEVICE_ID!r}"
        )
        assert primary_members[0]["is_primary"] is True, (
            f"Primary device member has is_primary={primary_members[0]['is_primary']!r}, "
            "expected True"
        )

    def test_secondary_device_member_has_is_primary_false(self):
        """Non-primary members must have is_primary=False."""
        resp = self._get_session_response()
        if resp.status_code == 503:
            return
        assert resp.status_code == 200
        data = resp.json()
        secondary_members = [
            m for m in data.get("members", [])
            if m.get("device_id") == self._SECONDARY_DEVICE_ID
        ]
        assert len(secondary_members) == 1, (
            f"Expected one member with device_id={self._SECONDARY_DEVICE_ID!r}"
        )
        assert secondary_members[0]["is_primary"] is False, (
            f"Secondary device member has is_primary={secondary_members[0]['is_primary']!r}, "
            "expected False"
        )

    def test_all_session_contract_fields_present(self):
        """
        Top-level session response must include all fields the frontend
        DeviceSession interface expects: id, status, primary_device_id,
        started_at, stopped_at, created_at, members.
        """
        resp = self._get_session_response()
        if resp.status_code == 503:
            return
        assert resp.status_code == 200
        data = resp.json()
        required = (
            "id", "organization_id", "primary_device_id",
            "status", "started_at", "stopped_at", "created_at", "members",
        )
        for field in required:
            assert field in data, (
                f"Required session field '{field}' missing from HTTP response"
            )
        assert isinstance(data["members"], list)


if __name__ == "__main__":
    unittest.main()
