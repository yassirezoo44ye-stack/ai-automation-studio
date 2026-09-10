"""
Device Agent WebSocket — /ws/device/{device_id}

Architecture:
  - Native Device Agent opens WSS to this endpoint
  - Agent authenticates via device credential (not JWT — agents are machines)
  - Session authorization validated against device_session_authorizations
  - High-frequency mouse frames never hit the database
  - Keyboard events preserve ordering (sequential processing)
  - Failsafe: any disconnect/error → stop_session for primary devices

Protocol (JSON frames, version=1):
  Agent → Server:
    {"version":1, "type":"auth",       "device_id":"...", "credential":"...", "session_id":"..."}
    {"version":1, "type":"heartbeat",  "timestamp":...}
    {"version":1, "type":"mouse_move", "x":..., "y":..., "timestamp":...}
    {"version":1, "type":"mouse_down", "button":..., "x":..., "y":..., "timestamp":...}
    {"version":1, "type":"mouse_up",   "button":..., "x":..., "y":..., "timestamp":...}
    {"version":1, "type":"mouse_scroll","dx":..., "dy":..., "timestamp":...}
    {"version":1, "type":"key_down",   "vk":..., "scan":..., "flags":..., "seq":..., "timestamp":...}
    {"version":1, "type":"key_up",     "vk":..., "scan":..., "flags":..., "seq":..., "timestamp":...}
    {"version":1, "type":"display_config", "monitors":[...], "primary_width":..., "primary_height":...}
    {"version":1, "type":"device_focus"}     -- agent has UI focus on its local device

  Server → Agent:
    {"version":1, "type":"auth_ok",    "device_id":"...", "session_id":"..."}
    {"version":1, "type":"auth_fail",  "reason":"..."}
    {"version":1, "type":"session_start"}
    {"version":1, "type":"session_stop", "reason":"..."}
    {"version":1, "type":"device_switch", "from_device":"...", "to_device":"...",
                  "cursor_x":..., "cursor_y":..., "timestamp":...}
    {"version":1, "type":"device_focus"}
    {"version":1, "type":"heartbeat_ack"}
    {"version":1, "type":"error", "message":"..."}

SECURITY:
  - Credential is not a JWT — it's an opaque token verified by hash comparison.
  - Session authorization is additionally checked on every control-start.
  - Raw key codes / mouse coordinates are NEVER written to DB, audit logs, or traces.
  - On any authentication / authorization failure: close with 4401/4403.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from app.services.device_control import (
    _DeviceConn,
    get_device_control_service,
    get_registry,
    HEARTBEAT_INTERVAL_S,
    WS_TIMEOUT_S,
)
from app.core.db import write_audit

log = logging.getLogger(__name__)

router = APIRouter(tags=["device-control-ws"])

# Maximum allowed frame size in bytes (protects against oversized payloads)
_MAX_FRAME_BYTES = 4096

# Allowed message types from the agent after authentication
_ALLOWED_TYPES = frozenset({
    "heartbeat",
    "mouse_move", "mouse_down", "mouse_up", "mouse_scroll",
    "key_down", "key_up",
    "display_config",
    "device_focus",
    "device_switch",
})

# Mouse move is high-frequency — coalesce window in seconds
_MOUSE_COALESCE_S = 0.016   # ~60 Hz cap

# Timestamp drift tolerance (reject frames more than 30s in the future)
_MAX_FUTURE_DRIFT_S = 30


def _validate_frame(msg: dict) -> bool:
    """Validate an incoming control frame. Never log input payloads."""
    if not isinstance(msg, dict):
        return False
    if msg.get("version") != 1:
        return False
    if msg.get("type") not in _ALLOWED_TYPES:
        return False
    ts = msg.get("timestamp")
    if ts is not None:
        try:
            t = float(ts) / 1000  # ms → s
            if t > time.time() + _MAX_FUTURE_DRIFT_S:
                return False  # Reject obviously future timestamps
        except (TypeError, ValueError):
            return False
    return True


async def _send(ws: WebSocket, payload: dict) -> bool:
    try:
        await ws.send_text(json.dumps(payload))
        return True
    except Exception:
        return False


async def _heartbeat_loop(ws: WebSocket, interval: float) -> None:
    while True:
        await asyncio.sleep(interval)
        ok = await _send(ws, {"version": 1, "type": "heartbeat_ack",
                               "ts": int(time.time() * 1000)})
        if not ok:
            break


@router.websocket("/ws/device/{device_id}")
async def device_agent_ws(ws: WebSocket, device_id: str):
    """
    Authenticated WebSocket for Flow Device Agents.

    Authentication flow:
      1. Accept the raw connection (no auth yet)
      2. Wait for {"type":"auth", "credential":"...", "session_id":"..."} frame
      3. Verify device credential against DB hash
      4. If session_id provided, verify session authorization
      5. Register in _ControlRegistry
      6. Begin streaming control frames

    Failsafe:
      - Any disconnect → unregister from registry, update DB status
      - If disconnected device was primary → terminate entire session
      - Input hooks are released by the agent on receiving session_stop
    """
    svc = get_device_control_service()

    # Step 1: Accept
    await ws.accept()

    device_info: Optional[dict] = None
    session_id: Optional[str] = None
    conn_obj: Optional[_DeviceConn] = None
    is_primary: bool = False
    org_id: Optional[str] = None

    hb_task: Optional[asyncio.Task] = None

    try:
        # ── Step 2: Auth handshake ─────────────────────────────────────────
        try:
            raw_auth = await asyncio.wait_for(ws.receive_text(), timeout=float(WS_TIMEOUT_S))
        except asyncio.TimeoutError:
            await _send(ws, {"version": 1, "type": "auth_fail", "reason": "auth_timeout"})
            await ws.close(code=4401, reason="auth_timeout")
            return

        if len(raw_auth) > _MAX_FRAME_BYTES:
            await _send(ws, {"version": 1, "type": "auth_fail", "reason": "frame_too_large"})
            await ws.close(code=4400, reason="frame_too_large")
            return

        try:
            auth_msg = json.loads(raw_auth)
        except json.JSONDecodeError:
            await _send(ws, {"version": 1, "type": "auth_fail", "reason": "invalid_json"})
            await ws.close(code=4400, reason="invalid_json")
            return

        if auth_msg.get("type") != "auth":
            await _send(ws, {"version": 1, "type": "auth_fail", "reason": "expected_auth"})
            await ws.close(code=4401, reason="expected_auth")
            return

        raw_credential = auth_msg.get("credential", "")
        claimed_session_id = auth_msg.get("session_id")  # may be None for idle agents

        # ── Step 3: Verify device credential ──────────────────────────────
        device_info = await svc.authenticate_device(device_id, raw_credential)
        if device_info is None:
            log.warning("ws_device: auth failed device_id=%s", device_id)
            await _send(ws, {"version": 1, "type": "auth_fail", "reason": "invalid_credential"})
            await ws.close(code=4401, reason="invalid_credential")

            # Audit only the failure event (no credential in audit)
            asyncio.create_task(write_audit(
                "agent@system", "device_authentication_failed",
                resource="devices", resource_id=device_id,
            ))
            return

        org_id = device_info["organization_id"]

        # ── Step 4: Session authorization (if session_id provided) ─────────
        if claimed_session_id:
            # Agent must provide its session auth token (obtained via
            # POST /api/device-sessions/{id}/auth-token after device auth)
            session_token = auth_msg.get("session_token", "")
            authorized = await svc.authorize_ws_session(
                device_id, claimed_session_id, session_token
            )
            if not authorized:
                log.warning(
                    "ws_device: session auth failed device=%s session=%s",
                    device_id, claimed_session_id,
                )
                await _send(ws, {
                    "version": 1, "type": "auth_fail",
                    "reason": "session_authorization_failed",
                })
                await ws.close(code=4403, reason="session_authorization_failed")

                asyncio.create_task(write_audit(
                    "agent@system", "session_authorization_failed",
                    resource="device_sessions", resource_id=claimed_session_id,
                    details={"device_id": device_id},
                ))
                return

            session_id = claimed_session_id

            # Determine if this is the primary device (for failsafe)
            session = await svc.get_session(org_id, session_id)
            if session:
                is_primary = session.get("primary_device_id") == device_id

        # ── Step 5: Register & mark online ────────────────────────────────
        conn_obj = _DeviceConn(
            device_id=device_id,
            org_id=org_id,
            session_id=session_id,
            ws=ws,
        )
        await get_registry().register(conn_obj)
        await svc.mark_device_online(device_id, org_id)

        await _send(ws, {
            "version":    1,
            "type":       "auth_ok",
            "device_id":  device_id,
            "session_id": session_id,
        })

        asyncio.create_task(write_audit(
            "agent@system", "device_connected",
            resource="devices", resource_id=device_id,
            details={"session_id": session_id},
        ))

        log.info("ws_device: connected device=%s session=%s primary=%s",
                 device_id, session_id, is_primary)

        # ── Step 6: Main control loop ──────────────────────────────────────
        hb_task = asyncio.create_task(_heartbeat_loop(ws, float(HEARTBEAT_INTERVAL_S)))

        last_mouse_forward = 0.0   # For mouse-move coalescing

        while True:
            try:
                raw = await asyncio.wait_for(
                    ws.receive_text(),
                    timeout=float(HEARTBEAT_INTERVAL_S) * 5,
                )
            except asyncio.TimeoutError:
                # Missed heartbeat window — send a ping and keep going
                # (the client's heartbeat_loop will detect dead connections)
                await _send(ws, {"version": 1, "type": "heartbeat_ack",
                                  "ts": int(time.time() * 1000)})
                continue

            if len(raw) > _MAX_FRAME_BYTES:
                log.warning("ws_device: oversized frame from device=%s (%d bytes)", device_id, len(raw))
                await _send(ws, {"version": 1, "type": "error", "message": "frame_too_large"})
                continue

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await _send(ws, {"version": 1, "type": "error", "message": "invalid_json"})
                continue

            if not _validate_frame(msg):
                # Do not echo back invalid frame contents — could contain raw input
                await _send(ws, {"version": 1, "type": "error", "message": "invalid_frame"})
                continue

            mtype = msg["type"]

            if mtype == "heartbeat":
                conn_obj.last_heartbeat = time.monotonic()
                await svc.record_heartbeat(device_id, org_id)
                await _send(ws, {"version": 1, "type": "heartbeat_ack",
                                  "ts": int(time.time() * 1000)})

            elif mtype == "display_config":
                # Agent reporting its monitor layout — safe to persist (geometry only)
                monitors = msg.get("monitors", [])
                if isinstance(monitors, list) and len(monitors) <= 32:
                    asyncio.create_task(svc.update_device_display_config(
                        device_id, org_id,
                        monitors,
                        screen_width=msg.get("primary_width"),
                        screen_height=msg.get("primary_height"),
                    ))

            elif mtype == "mouse_move":
                # High-frequency — coalesce, never persist, route to target device
                now = time.monotonic()
                if (now - last_mouse_forward) < _MOUSE_COALESCE_S:
                    continue   # coalesce: drop intermediate moves
                last_mouse_forward = now

                if session_id:
                    await _route_frame_to_target(session_id, device_id, msg, svc)

            elif mtype in ("mouse_down", "mouse_up"):
                # Button events: MUST NOT be dropped — route immediately
                if session_id:
                    await _route_frame_to_target(session_id, device_id, msg, svc)

            elif mtype == "mouse_scroll":
                if session_id:
                    await _route_frame_to_target(session_id, device_id, msg, svc)

            elif mtype in ("key_down", "key_up"):
                # Keyboard events: MUST preserve ordering, MUST NOT be logged
                # Route to current target device; never persist vk/scan codes
                if session_id:
                    await _route_frame_to_target(session_id, device_id, msg, svc)

            elif mtype == "device_focus":
                # Agent's device received local focus — update audit only
                if session_id:
                    asyncio.create_task(write_audit(
                        "agent@system", "device_focus",
                        resource="device_sessions", resource_id=session_id,
                        details={"device_id": device_id},
                    ))

            elif mtype == "device_switch":
                # Explicit switch request from primary agent
                if session_id and is_primary:
                    await _handle_device_switch(session_id, device_id, msg, svc, org_id)

    except WebSocketDisconnect:
        log.info("ws_device: disconnected device=%s", device_id)
    except Exception as exc:
        log.warning("ws_device: error device=%s: %s", device_id, exc, exc_info=False)
    finally:
        if hb_task:
            hb_task.cancel()

        if conn_obj:
            await get_registry().unregister(device_id)

        if org_id:
            asyncio.create_task(svc.mark_device_offline(device_id, org_id))
            asyncio.create_task(write_audit(
                "agent@system", "device_disconnected",
                resource="devices", resource_id=device_id,
                details={"session_id": session_id},
            ))

        # Failsafe: primary disconnect → terminate session
        if is_primary and session_id and org_id:
            log.warning(
                "ws_device: primary device %s disconnected — terminating session %s",
                device_id, session_id,
            )
            asyncio.create_task(svc.handle_primary_disconnect(session_id, org_id))


async def _route_frame_to_target(
    session_id: str,
    source_device_id: str,
    frame: dict,
    svc,
) -> None:
    """
    Forward a control frame to the currently active target device.
    The target is determined by the in-memory registry (the device
    that last received a device_focus or device_switch command).

    IMPORTANT: raw coordinates and key codes are forwarded verbatim — they
    are NEVER stored, logged, or emitted as events. They exist in memory
    only for the duration of the WS connection.
    """
    registry = get_registry()
    conns = registry.all_in_session(session_id)

    # The target is any device in the session that is NOT the source
    # and that is currently focused. In the initial implementation,
    # we forward to all non-source members; the primary agent decides
    # which device has focus via device_switch messages.
    for conn in conns:
        if conn.device_id == source_device_id:
            continue
        try:
            await conn.ws.send_text(json.dumps(frame))
        except Exception:
            pass


async def _handle_device_switch(
    session_id: str,
    primary_device_id: str,
    msg: dict,
    svc,
    org_id: str,
) -> None:
    """
    Route a device_switch frame and audit the switch event (metadata only).
    The switch notification is sent to all session members.
    """
    to_device = msg.get("to_device", "")
    from_device = msg.get("from_device", primary_device_id)
    cursor_x = msg.get("cursor_x", 0)
    cursor_y = msg.get("cursor_y", 0)

    registry = get_registry()
    conns = registry.all_in_session(session_id)

    switch_frame = {
        "version":     1,
        "type":        "device_switch",
        "from_device": from_device,
        "to_device":   to_device,
        "cursor_x":    cursor_x,
        "cursor_y":    cursor_y,
        "timestamp":   int(time.time() * 1000),
    }

    for conn in conns:
        try:
            await conn.ws.send_text(json.dumps(switch_frame))
        except Exception:
            pass

    # Audit switch: metadata only — no cursor coordinates, no key state
    asyncio.create_task(write_audit(
        "agent@system", "device_switched",
        resource="device_sessions", resource_id=session_id,
        details={
            "from_device": from_device,
            "to_device":   to_device,
            # cursor_x and cursor_y deliberately NOT included in audit
        },
    ))

    try:
        from app.core.events import get_event_bus, Event
        await get_event_bus().publish(Event(
            type="device_control.device_switched",
            data={
                "session_id":  session_id,
                "from_device": from_device,
                "to_device":   to_device,
            },
            organization_id=org_id,
        ))
    except Exception:
        pass
