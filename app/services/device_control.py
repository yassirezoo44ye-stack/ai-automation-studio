"""
Device Control Service — business logic for Multi-Device Control.

Responsibilities:
  - device registration and enrollment
  - enrollment token hashing / verification
  - device credential hashing / verification
  - device revocation
  - session lifecycle (create → start → stop)
  - session membership and layout
  - active controller management
  - heartbeat / status
  - WebSocket session authorization
  - audit events (metadata only — never raw input)
  - event bus publication
  - metrics
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import secrets
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import asyncpg

from app.core.db import get_pool, write_audit

log = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────────────────────────────
DEVICE_CONTROL_ENABLED = os.getenv("DEVICE_CONTROL_ENABLED", "true").lower() != "false"
MAX_DEVICES_PER_SESSION = int(os.getenv("DEVICE_CONTROL_MAX_DEVICES", "5"))
HEARTBEAT_INTERVAL_S = int(os.getenv("DEVICE_CONTROL_HEARTBEAT_INTERVAL", "10"))
ENROLLMENT_TTL_S = int(os.getenv("DEVICE_CONTROL_ENROLLMENT_TTL", "300"))  # 5 min
SESSION_AUTH_TTL_S = int(os.getenv("DEVICE_CONTROL_SESSION_AUTH_TTL", "3600"))
WS_TIMEOUT_S = int(os.getenv("DEVICE_CONTROL_WS_TIMEOUT", "30"))
OFFLINE_THRESHOLD_MISSED = 3   # missed heartbeats before marking offline


# ── Security helpers ──────────────────────────────────────────────────────────

def _hash_token(raw: str) -> str:
    """SHA-256 hex of a raw token/credential — safe to store in DB."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _generate_credential() -> tuple[str, str]:
    """Returns (raw_credential, hashed_credential). Store only the hash."""
    raw = secrets.token_urlsafe(48)   # 384 bits
    return raw, _hash_token(raw)


def _generate_enrollment_token() -> tuple[str, str, str]:
    """Returns (raw_token, hash, prefix). Show raw to user once; store hash only."""
    raw = secrets.token_urlsafe(24)   # 192 bits
    return raw, _hash_token(raw), raw[:4].upper()


# ── In-memory state (authoritative source: DB; in-memory = live WS cache) ────

@dataclass
class _DeviceConn:
    """Tracks a single live WebSocket connection for a device agent."""
    device_id: str
    org_id: str
    session_id: str | None
    ws: Any                         # starlette WebSocket (typed as Any to avoid import)
    last_heartbeat: float = field(default_factory=time.monotonic)


class _ControlRegistry:
    """
    In-memory registry of active agent WebSocket connections.

    The database is the authoritative source of truth for sessions/membership/
    revocation. This registry only tracks live WebSocket objects so we can
    route control frames and broadcast session events without a DB round-trip
    per frame. It is safe to lose on restart — agents reconnect automatically.
    """

    def __init__(self) -> None:
        self._conns: dict[str, _DeviceConn] = {}   # device_id → conn
        self._lock = asyncio.Lock()

    async def register(self, conn: _DeviceConn) -> None:
        async with self._lock:
            self._conns[conn.device_id] = conn

    async def unregister(self, device_id: str) -> None:
        async with self._lock:
            self._conns.pop(device_id, None)

    def get(self, device_id: str) -> _DeviceConn | None:
        return self._conns.get(device_id)

    def all_in_session(self, session_id: str) -> list[_DeviceConn]:
        return [c for c in self._conns.values() if c.session_id == session_id]

    def touch_heartbeat(self, device_id: str) -> None:
        conn = self._conns.get(device_id)
        if conn:
            conn.last_heartbeat = time.monotonic()

    def stale_devices(self, threshold_s: float) -> list[str]:
        now = time.monotonic()
        return [
            did for did, c in self._conns.items()
            if (now - c.last_heartbeat) > threshold_s
        ]


_registry = _ControlRegistry()


def get_registry() -> _ControlRegistry:
    return _registry


# ── Service ───────────────────────────────────────────────────────────────────

class DeviceControlService:
    """All device-control business logic. Routers/WS handlers call this."""

    # ── Enrollment ─────────────────────────────────────────────────────────

    async def create_enrollment_token(
        self,
        org_id: str,
        created_by_user_id: str,
        created_by_email: str,
        workspace_id: str | None = None,
    ) -> dict:
        """
        Generate a single-use, hashed enrollment token.
        Returns the raw token to show to the user exactly once.
        The plaintext is never persisted.
        """
        if not DEVICE_CONTROL_ENABLED:
            raise ValueError("Device Control is disabled on this server")

        raw, hashed, prefix = _generate_enrollment_token()
        expires_at_epoch = time.time() + ENROLLMENT_TTL_S
        token_id = str(uuid.uuid4())

        async with get_pool().acquire() as conn:
            await conn.execute(
                """
                INSERT INTO device_enrollment_tokens
                  (id, organization_id, workspace_id, created_by, token_hash,
                   token_prefix, expires_at)
                VALUES ($1, $2, $3, $4, $5, $6, to_timestamp($7))
                """,
                uuid.UUID(token_id),
                uuid.UUID(org_id),
                uuid.UUID(workspace_id) if workspace_id else None,
                uuid.UUID(created_by_user_id),
                hashed,
                prefix,
                expires_at_epoch,
            )

        asyncio.create_task(
            write_audit(
                created_by_email,
                "device_enrollment_token_created",
                resource="devices",
                resource_id=token_id,
                details={"org_id": org_id, "prefix": prefix},
            )
        )

        return {
            "token_id":    token_id,
            "token":       raw,       # shown to user once, then gone
            "prefix":      prefix,
            "expires_in":  ENROLLMENT_TTL_S,
            "expires_at":  expires_at_epoch,
        }

    async def consume_enrollment_token(
        self,
        raw_token: str,
        device_name: str,
        platform: str,
        hostname: str | None,
        agent_version: str | None,
        screen_width: int | None,
        screen_height: int | None,
        device_fingerprint: str | None = None,
    ) -> dict:
        """
        Verify + consume a single-use enrollment token.
        Issues a device credential (stored hashed). Returns the raw credential
        to the agent once — never stored in plaintext.
        """
        hashed = _hash_token(raw_token)
        raw_cred, cred_hash = _generate_credential()
        device_id = str(uuid.uuid4())

        async with get_pool().acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    SELECT id, organization_id, workspace_id, created_by,
                           expires_at, used_at
                    FROM device_enrollment_tokens
                    WHERE token_hash = $1
                    """,
                    hashed,
                )
                if row is None:
                    raise ValueError("Invalid enrollment token")
                if row["used_at"] is not None:
                    raise ValueError("Enrollment token already used")
                import datetime
                if row["expires_at"] < datetime.datetime.now(datetime.timezone.utc):
                    raise ValueError("Enrollment token expired")

                org_id = str(row["organization_id"])
                workspace_id = str(row["workspace_id"]) if row["workspace_id"] else None
                token_id = str(row["id"])

                # Mark token used atomically
                await conn.execute(
                    "UPDATE device_enrollment_tokens SET used_at=NOW(), device_id=$1 WHERE id=$2",
                    uuid.UUID(device_id),
                    row["id"],
                )

                # Create device
                await conn.execute(
                    """
                    INSERT INTO devices
                      (id, organization_id, workspace_id, created_by, name,
                       platform, hostname, agent_version, status,
                       screen_width, screen_height, credential_hash,
                       device_fingerprint)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,'offline',$9,$10,$11,$12)
                    """,
                    uuid.UUID(device_id),
                    uuid.UUID(org_id),
                    uuid.UUID(workspace_id) if workspace_id else None,
                    row["created_by"],
                    device_name,
                    platform,
                    hostname,
                    agent_version,
                    screen_width,
                    screen_height,
                    cred_hash,
                    device_fingerprint,
                )

        # Publish event (best-effort)
        try:
            from app.core.events import get_event_bus, Event
            await get_event_bus().publish(Event(
                type="device.registered",
                data={"device_id": device_id, "name": device_name, "platform": platform},
                organization_id=org_id,
            ))
        except Exception:
            pass

        return {
            "device_id":    device_id,
            "credential":   raw_cred,   # shown to agent once — never re-issued without rotation
            "org_id":       org_id,
            "workspace_id": workspace_id,
        }

    # ── Device CRUD ────────────────────────────────────────────────────────

    async def list_devices(self, org_id: str) -> list[dict]:
        async with get_pool().acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, organization_id, workspace_id, created_by, name,
                       platform, hostname, agent_version, status,
                       screen_width, screen_height, screen_position,
                       display_config, capabilities, credential_version,
                       registered_at, last_seen_at, revoked_at
                FROM devices
                WHERE organization_id = $1 AND revoked_at IS NULL
                ORDER BY registered_at DESC
                """,
                uuid.UUID(org_id),
            )
        return [_device_row_to_dict(r) for r in rows]

    async def get_device(self, org_id: str, device_id: str) -> dict | None:
        async with get_pool().acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, organization_id, workspace_id, created_by, name,
                       platform, hostname, agent_version, status,
                       screen_width, screen_height, screen_position,
                       display_config, capabilities, credential_version,
                       registered_at, last_seen_at, revoked_at
                FROM devices
                WHERE id = $1 AND organization_id = $2
                """,
                uuid.UUID(device_id),
                uuid.UUID(org_id),
            )
        return _device_row_to_dict(row) if row else None

    async def revoke_device(
        self,
        org_id: str,
        device_id: str,
        actor_email: str,
    ) -> None:
        """
        Revoke a device: mark DB, terminate active WS, remove from sessions,
        invalidate session authorizations, notify UI.
        """
        async with get_pool().acquire() as conn:
            result = await conn.execute(
                """
                UPDATE devices
                SET status='revoked', revoked_at=NOW(), updated_at=NOW()
                WHERE id=$1 AND organization_id=$2 AND revoked_at IS NULL
                """,
                uuid.UUID(device_id),
                uuid.UUID(org_id),
            )
            if result == "UPDATE 0":
                raise ValueError("Device not found or already revoked")

            # Revoke all active session authorizations for this device
            await conn.execute(
                "UPDATE device_session_authorizations SET revoked_at=NOW() "
                "WHERE device_id=$1 AND revoked_at IS NULL",
                uuid.UUID(device_id),
            )

        # Kill live WebSocket
        conn_obj = _registry.get(device_id)
        if conn_obj:
            try:
                await conn_obj.ws.send_text(json.dumps({
                    "type": "session_stop",
                    "reason": "device_revoked",
                }))
                await conn_obj.ws.close(code=4403, reason="device_revoked")
            except Exception:
                pass
            await _registry.unregister(device_id)

        asyncio.create_task(write_audit(
            actor_email, "device_revoked",
            resource="devices", resource_id=device_id,
            details={"org_id": org_id},
        ))

        try:
            from app.core.events import get_event_bus, Event
            await get_event_bus().publish(Event(
                type="device.revoked",
                data={"device_id": device_id},
                organization_id=org_id,
            ))
        except Exception:
            pass

    async def rotate_credential(
        self,
        org_id: str,
        device_id: str,
        actor_email: str,
    ) -> dict:
        """Issue a new device credential. The agent must re-authenticate."""
        raw_cred, cred_hash = _generate_credential()
        async with get_pool().acquire() as conn:
            result = await conn.execute(
                """
                UPDATE devices
                SET credential_hash=$1,
                    credential_version = credential_version + 1,
                    updated_at=NOW()
                WHERE id=$2 AND organization_id=$3 AND revoked_at IS NULL
                """,
                cred_hash,
                uuid.UUID(device_id),
                uuid.UUID(org_id),
            )
            if result == "UPDATE 0":
                raise ValueError("Device not found or revoked")

        asyncio.create_task(write_audit(
            actor_email, "device_credential_rotated",
            resource="devices", resource_id=device_id,
            details={"org_id": org_id},
        ))
        return {"credential": raw_cred}

    # ── Device authentication (agent-side) ─────────────────────────────────

    async def authenticate_device(
        self,
        device_id: str,
        raw_credential: str,
    ) -> dict | None:
        """
        Verify a device credential. Returns the device row on success, None on failure.
        Used by the WebSocket handshake — never by the HTTP API.
        """
        hashed = _hash_token(raw_credential)
        async with get_pool().acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, organization_id, workspace_id, name, platform,
                       status, credential_version
                FROM devices
                WHERE id=$1 AND credential_hash=$2 AND revoked_at IS NULL
                """,
                uuid.UUID(device_id),
                hashed,
            )
        return _device_row_to_dict(row) if row else None

    # ── Heartbeat / status ──────────────────────────────────────────────────

    async def record_heartbeat(self, device_id: str, org_id: str) -> None:
        """Update last_seen_at and set status to online (unless control_active)."""
        _registry.touch_heartbeat(device_id)
        async with get_pool().acquire() as conn:
            await conn.execute(
                """
                UPDATE devices
                SET last_seen_at=NOW(),
                    status = CASE
                        WHEN status NOT IN ('control_active','revoked') THEN 'online'
                        ELSE status
                    END,
                    updated_at=NOW()
                WHERE id=$1 AND organization_id=$2
                """,
                uuid.UUID(device_id),
                uuid.UUID(org_id),
            )

    async def mark_device_online(self, device_id: str, org_id: str) -> None:
        async with get_pool().acquire() as conn:
            await conn.execute(
                """
                UPDATE devices
                SET status='online', last_seen_at=NOW(),
                    last_connected_at=NOW(), updated_at=NOW()
                WHERE id=$1 AND organization_id=$2 AND revoked_at IS NULL
                """,
                uuid.UUID(device_id),
                uuid.UUID(org_id),
            )

    async def mark_device_offline(self, device_id: str, org_id: str) -> None:
        async with get_pool().acquire() as conn:
            # Only flip to offline if not revoked
            await conn.execute(
                """
                UPDATE devices
                SET status = CASE WHEN status='revoked' THEN 'revoked' ELSE 'offline' END,
                    last_seen_at=NOW(), last_disconnected_at=NOW(), updated_at=NOW()
                WHERE id=$1 AND organization_id=$2
                """,
                uuid.UUID(device_id),
                uuid.UUID(org_id),
            )

    async def update_device_display_config(
        self,
        device_id: str,
        org_id: str,
        display_config: list[dict],
        screen_width: int | None = None,
        screen_height: int | None = None,
    ) -> None:
        async with get_pool().acquire() as conn:
            await conn.execute(
                """
                UPDATE devices
                SET display_config=$1, screen_width=$2, screen_height=$3,
                    last_seen_at=NOW(), updated_at=NOW()
                WHERE id=$4 AND organization_id=$5
                """,
                json.dumps(display_config),
                screen_width,
                screen_height,
                uuid.UUID(device_id),
                uuid.UUID(org_id),
            )

    # ── Session lifecycle ───────────────────────────────────────────────────

    async def create_session(
        self,
        org_id: str,
        created_by_user_id: str,
        created_by_email: str,
        primary_device_id: str,
        device_ids: list[str],
        workspace_id: str | None = None,
    ) -> dict:
        """
        Create a draft session with up to MAX_DEVICES_PER_SESSION members.
        Validates: all devices belong to org, none revoked, count ≤ 5.
        """
        if not DEVICE_CONTROL_ENABLED:
            raise ValueError("Device Control is disabled")

        # Deduplicate + ensure primary is included
        all_ids = list({primary_device_id, *device_ids})
        if len(all_ids) > MAX_DEVICES_PER_SESSION:
            raise ValueError(
                f"Maximum {MAX_DEVICES_PER_SESSION} devices per session "
                f"(got {len(all_ids)}, counting primary)"
            )

        session_id = str(uuid.uuid4())

        async with get_pool().acquire() as conn:
            async with conn.transaction():
                # Verify all devices belong to org and are not revoked
                rows = await conn.fetch(
                    "SELECT id FROM devices WHERE id=ANY($1::uuid[]) "
                    "AND organization_id=$2 AND revoked_at IS NULL",
                    [uuid.UUID(d) for d in all_ids],
                    uuid.UUID(org_id),
                )
                found_ids = {str(r["id"]) for r in rows}
                missing = set(all_ids) - found_ids
                if missing:
                    raise ValueError(
                        f"Devices not found or revoked in this organization: {missing}"
                    )

                await conn.execute(
                    """
                    INSERT INTO device_control_sessions
                      (id, organization_id, workspace_id, created_by, primary_device_id, status)
                    VALUES ($1,$2,$3,$4,$5,'draft')
                    """,
                    uuid.UUID(session_id),
                    uuid.UUID(org_id),
                    uuid.UUID(workspace_id) if workspace_id else None,
                    uuid.UUID(created_by_user_id),
                    uuid.UUID(primary_device_id),
                )

                # Default layout: horizontal strip left-to-right
                for i, did in enumerate(all_ids):
                    default_w, default_h = 1920, 1080
                    await conn.execute(
                        """
                        INSERT INTO device_control_session_members
                          (session_id, device_id, position_x, position_y,
                           width, height, sort_order, enabled)
                        VALUES ($1,$2,$3,$4,$5,$6,$7,TRUE)
                        """,
                        uuid.UUID(session_id),
                        uuid.UUID(did),
                        i * default_w,  # horizontal layout by default
                        0,
                        default_w,
                        default_h,
                        i,
                    )

        asyncio.create_task(write_audit(
            created_by_email, "control_session_created",
            resource="device_sessions", resource_id=session_id,
            details={
                "org_id": org_id,
                "primary_device_id": primary_device_id,
                "device_count": len(all_ids),
            },
        ))

        return await self.get_session(org_id, session_id)  # type: ignore[return-value]

    async def start_session(
        self,
        org_id: str,
        session_id: str,
        actor_email: str,
    ) -> dict:
        """
        Transition session from draft → starting → active.
        Issues per-device session authorizations and delivers personalized
        session_start frames directly to each device's live WS connection.

        BLOCKER 1 FIX: Idle agents have session_id=None in the registry so
        _broadcast_to_session() (which filters by conn.session_id) would never
        reach them.  We look up each device by device_id instead and assign
        the session_id into the in-memory conn object here.

        BLOCKER 2 FIX: The session_token (raw value) is delivered only over the
        authenticated, TLS-encrypted WS channel.  It is NEVER logged, never put
        in a URL, and never sent to the browser.
        """
        # Collect per-device tokens and layout inside the transaction
        # so raw tokens and layout rows are both available for frame construction.
        device_tokens: dict[str, str] = {}   # device_id → raw_token  (NEVER LOGGED)
        primary_device_id_str = ""
        layout_rows: list = []

        async with get_pool().acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "SELECT id, status, primary_device_id "
                    "FROM device_control_sessions "
                    "WHERE id=$1 AND organization_id=$2 FOR UPDATE",
                    uuid.UUID(session_id),
                    uuid.UUID(org_id),
                )
                if row is None:
                    raise ValueError("Session not found")
                if row["status"] not in ("draft",):
                    raise ValueError(f"Session cannot be started from status '{row['status']}'")

                primary_device_id_str = str(row["primary_device_id"])

                await conn.execute(
                    "UPDATE device_control_sessions "
                    "SET status='starting', started_at=NOW(), updated_at=NOW() "
                    "WHERE id=$1",
                    uuid.UUID(session_id),
                )

                # Fetch members WITH layout geometry — agents need this for edge detection
                layout_rows = await conn.fetch(
                    """
                    SELECT device_id, position_x, position_y, width, height,
                           sort_order, enabled
                    FROM device_control_session_members
                    WHERE session_id=$1 AND enabled=TRUE
                    ORDER BY sort_order
                    """,
                    uuid.UUID(session_id),
                )

                # Issue per-device authorizations; collect raw tokens for WS delivery
                exp = time.time() + SESSION_AUTH_TTL_S
                for m in layout_rows:
                    raw_tok = secrets.token_urlsafe(32)
                    tok_hash = _hash_token(raw_tok)
                    device_tokens[str(m["device_id"])] = raw_tok  # hold for delivery below
                    await conn.execute(
                        """
                        INSERT INTO device_session_authorizations
                          (session_id, device_id, organization_id,
                           token_hash, expires_at)
                        VALUES ($1,$2,$3,$4,to_timestamp($5))
                        ON CONFLICT (session_id, device_id)
                        DO UPDATE SET token_hash=$4, expires_at=to_timestamp($5),
                                      revoked_at=NULL, issued_at=NOW()
                        """,
                        uuid.UUID(session_id),
                        m["device_id"],
                        uuid.UUID(org_id),
                        tok_hash,
                        exp,
                    )

                await conn.execute(
                    "UPDATE device_control_sessions "
                    "SET status='active', updated_at=NOW() "
                    "WHERE id=$1",
                    uuid.UUID(session_id),
                )

        # Build the layout list included in every session_start frame so agents
        # can initialise edge-detection geometry without a DB round-trip.
        layout: list[dict] = [
            {
                "device_id":  str(m["device_id"]),
                "position_x": m["position_x"],
                "position_y": m["position_y"],
                "width":      m["width"],
                "height":     m["height"],
                "sort_order": m["sort_order"],
                "enabled":    m["enabled"],
            }
            for m in layout_rows
        ]

        # ── BLOCKER 1+2 FIX: deliver personalized session_start per device ──
        # We bypass _broadcast_to_session() because that filters by conn.session_id
        # which is None for all idle agents.  Instead we look each device up by
        # device_id directly in the registry.
        #
        # The session_token field carries a per-device raw auth token.  It is:
        #   • delivered exclusively over the authenticated TLS WebSocket channel
        #   • NEVER logged (not at INFO, WARN, or DEBUG level)
        #   • NEVER placed in a URL or query-string
        #   • NEVER forwarded to the browser or to any AI layer
        now_ms = int(time.time() * 1000)
        offline_devices: list[str] = []

        for device_id_str, raw_tok in device_tokens.items():
            conn_obj = _registry.get(device_id_str)
            if conn_obj is None:
                # Device is offline.  Token is persisted in DB; the agent fetches it
                # via GET /api/devices/{id}/session-token when it reconnects.
                offline_devices.append(device_id_str)
                continue

            # BLOCKER 1: assign session_id so all_in_session() now includes this conn
            conn_obj.session_id = session_id

            # BLOCKER 2: send raw token inside the authenticated WS — never log it
            is_primary_device = (device_id_str == primary_device_id_str)
            frame: dict = {
                "version":           1,
                "type":              "session_start",
                "session_id":        session_id,
                "session_token":     raw_tok,            # raw — NEVER LOG
                "is_primary":        is_primary_device,
                "primary_device_id": primary_device_id_str,
                "members":           layout,
                "timestamp":         now_ms,
            }
            try:
                await conn_obj.ws.send_text(json.dumps(frame))
            except Exception:
                offline_devices.append(device_id_str)

        if offline_devices:
            log.info(
                "session_start %s: %d device(s) offline — token held in DB for reconnect",
                session_id[:8],
                len(offline_devices),
            )

        asyncio.create_task(write_audit(
            actor_email, "control_session_started",
            resource="device_sessions", resource_id=session_id,
            details={"org_id": org_id},
            # raw tokens are intentionally NOT included in the audit record
        ))

        try:
            from app.core.events import get_event_bus, Event
            await get_event_bus().publish(Event(
                type="device_control.session_started",
                data={"session_id": session_id},
                organization_id=org_id,
            ))
        except Exception:
            pass

        return await self.get_session(org_id, session_id)  # type: ignore[return-value]

    async def stop_session(
        self,
        org_id: str,
        session_id: str,
        actor_email: str,
        reason: str = "user_stopped",
    ) -> None:
        """
        Stop an active/starting session:
          1. Mark stopping in DB
          2. Broadcast session_stop to all agents (they release hooks)
          3. Revoke all session authorizations
          4. Mark stopped
        """
        async with get_pool().acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "SELECT id, status FROM device_control_sessions "
                    "WHERE id=$1 AND organization_id=$2 FOR UPDATE",
                    uuid.UUID(session_id),
                    uuid.UUID(org_id),
                )
                if row is None:
                    raise ValueError("Session not found")
                if row["status"] in ("stopped", "failed", "expired"):
                    return  # already terminal

                await conn.execute(
                    "UPDATE device_control_sessions "
                    "SET status='stopping', updated_at=NOW() "
                    "WHERE id=$1",
                    uuid.UUID(session_id),
                )

        # Broadcast BEFORE marking stopped so agents get the stop signal
        await self._broadcast_to_session(session_id, {
            "version":    1,
            "type":       "session_stop",
            "session_id": session_id,
            "reason":     reason,
            "timestamp":  int(time.time() * 1000),
        })

        async with get_pool().acquire() as conn:
            await conn.execute(
                "UPDATE device_session_authorizations SET revoked_at=NOW() "
                "WHERE session_id=$1 AND revoked_at IS NULL",
                uuid.UUID(session_id),
            )
            await conn.execute(
                "UPDATE device_control_sessions "
                "SET status='stopped', ended_at=NOW(), updated_at=NOW() "
                "WHERE id=$1",
                uuid.UUID(session_id),
            )
            # Reset device statuses
            await conn.execute(
                """
                UPDATE devices d SET status='online', updated_at=NOW()
                FROM device_control_session_members m
                WHERE m.session_id=$1 AND m.device_id=d.id
                  AND d.revoked_at IS NULL AND d.status='control_active'
                """,
                uuid.UUID(session_id),
            )

        asyncio.create_task(write_audit(
            actor_email, "control_session_stopped",
            resource="device_sessions", resource_id=session_id,
            details={"org_id": org_id, "reason": reason},
        ))

        try:
            from app.core.events import get_event_bus, Event
            await get_event_bus().publish(Event(
                type="device_control.session_stopped",
                data={"session_id": session_id, "reason": reason},
                organization_id=org_id,
            ))
        except Exception:
            pass

    async def update_layout(
        self,
        org_id: str,
        session_id: str,
        layout: list[dict],
    ) -> None:
        """Update the virtual canvas layout for session members."""
        async with get_pool().acquire() as conn:
            # Verify session belongs to org
            exists = await conn.fetchval(
                "SELECT 1 FROM device_control_sessions "
                "WHERE id=$1 AND organization_id=$2 AND status NOT IN ('stopped','failed','expired')",
                uuid.UUID(session_id),
                uuid.UUID(org_id),
            )
            if not exists:
                raise ValueError("Session not found or not active")

            for item in layout:
                device_id = item.get("device_id")
                if not device_id:
                    continue
                await conn.execute(
                    """
                    UPDATE device_control_session_members
                    SET position_x=$1, position_y=$2, width=$3, height=$4,
                        enabled=$5, sort_order=$6
                    WHERE session_id=$7 AND device_id=$8
                    """,
                    int(item.get("position_x", 0)),
                    int(item.get("position_y", 0)),
                    max(1, int(item.get("width", 1920))),
                    max(1, int(item.get("height", 1080))),
                    bool(item.get("enabled", True)),
                    int(item.get("sort_order", 0)),
                    uuid.UUID(session_id),
                    uuid.UUID(device_id),
                )

    async def get_session(self, org_id: str, session_id: str) -> dict | None:
        async with get_pool().acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, organization_id, workspace_id, created_by,
                       primary_device_id, status, started_at, ended_at, created_at
                FROM device_control_sessions
                WHERE id=$1 AND organization_id=$2
                """,
                uuid.UUID(session_id),
                uuid.UUID(org_id),
            )
            if row is None:
                return None

            members = await conn.fetch(
                """
                SELECT m.device_id, m.position_x, m.position_y, m.width, m.height,
                       m.sort_order, m.enabled, d.name, d.platform, d.status as device_status
                FROM device_control_session_members m
                JOIN devices d ON d.id = m.device_id
                WHERE m.session_id=$1
                ORDER BY m.sort_order
                """,
                uuid.UUID(session_id),
            )

        result = {
            "id":               str(row["id"]),
            "organization_id":  str(row["organization_id"]),
            "workspace_id":     str(row["workspace_id"]) if row["workspace_id"] else None,
            "created_by":       str(row["created_by"]) if row["created_by"] else None,
            "primary_device_id": str(row["primary_device_id"]) if row["primary_device_id"] else None,
            "status":           row["status"],
            "started_at":       row["started_at"].isoformat() if row["started_at"] else None,
            "ended_at":         row["ended_at"].isoformat() if row["ended_at"] else None,
            "created_at":       row["created_at"].isoformat(),
            "members": [
                {
                    "device_id":     str(m["device_id"]),
                    "name":          m["name"],
                    "platform":      m["platform"],
                    "device_status": m["device_status"],
                    "position_x":    m["position_x"],
                    "position_y":    m["position_y"],
                    "width":         m["width"],
                    "height":        m["height"],
                    "sort_order":    m["sort_order"],
                    "enabled":       m["enabled"],
                }
                for m in members
            ],
        }
        return result

    async def list_sessions(self, org_id: str) -> list[dict]:
        async with get_pool().acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id FROM device_control_sessions
                WHERE organization_id=$1
                ORDER BY created_at DESC
                LIMIT 50
                """,
                uuid.UUID(org_id),
            )
        results = []
        for r in rows:
            s = await self.get_session(org_id, str(r["id"]))
            if s:
                results.append(s)
        return results

    # ── WebSocket session authorization ────────────────────────────────────

    async def authorize_ws_session(
        self,
        device_id: str,
        session_id: str,
        raw_token: str,
    ) -> bool:
        """
        Verify that a device may connect to a session WebSocket.
        Checks: token hash, expiry, session active, device enabled.
        Never trusts client-supplied org_id.
        """
        hashed = _hash_token(raw_token)
        async with get_pool().acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT a.expires_at, a.revoked_at,
                       s.status as session_status,
                       m.enabled
                FROM device_session_authorizations a
                JOIN device_control_sessions s ON s.id = a.session_id
                JOIN device_control_session_members m
                     ON m.session_id = a.session_id AND m.device_id = a.device_id
                WHERE a.device_id=$1 AND a.session_id=$2 AND a.token_hash=$3
                """,
                uuid.UUID(device_id),
                uuid.UUID(session_id),
                hashed,
            )
        if row is None:
            return False
        if row["revoked_at"] is not None:
            return False

        import datetime
        if row["expires_at"] < datetime.datetime.now(datetime.timezone.utc):
            return False
        if row["session_status"] != "active":
            return False
        if not row["enabled"]:
            return False

        return True

    async def get_session_token_for_device(
        self,
        org_id: str,
        session_id: str,
        device_id: str,
    ) -> str | None:
        """
        Return a fresh session auth token raw value for a device.
        Only used when the agent connects to obtain its auth token via
        the device credential (authenticated device → session token exchange).
        """
        raw_tok = secrets.token_urlsafe(32)
        tok_hash = _hash_token(raw_tok)
        exp = time.time() + SESSION_AUTH_TTL_S

        async with get_pool().acquire() as conn:
            # Verify session is active and device is a member
            ok = await conn.fetchval(
                """
                SELECT 1 FROM device_control_session_members m
                JOIN device_control_sessions s ON s.id = m.session_id
                WHERE m.session_id=$1 AND m.device_id=$2
                  AND s.organization_id=$3 AND s.status='active'
                  AND m.enabled=TRUE
                """,
                uuid.UUID(session_id),
                uuid.UUID(device_id),
                uuid.UUID(org_id),
            )
            if not ok:
                return None

            await conn.execute(
                """
                INSERT INTO device_session_authorizations
                  (session_id, device_id, organization_id, token_hash, expires_at)
                VALUES ($1,$2,$3,$4,to_timestamp($5))
                ON CONFLICT (session_id, device_id)
                DO UPDATE SET token_hash=$4, expires_at=to_timestamp($5),
                              revoked_at=NULL, issued_at=NOW()
                """,
                uuid.UUID(session_id),
                uuid.UUID(device_id),
                uuid.UUID(org_id),
                tok_hash,
                exp,
            )

        return raw_tok

    # ── Internal helpers ────────────────────────────────────────────────────

    async def _broadcast_to_session(
        self,
        session_id: str,
        frame: dict,
    ) -> None:
        """Send a control frame to all agents connected to a session."""
        text = json.dumps(frame)
        conns = _registry.all_in_session(session_id)
        for conn_obj in conns:
            try:
                await conn_obj.ws.send_text(text)
            except Exception:
                pass

    async def handle_primary_disconnect(
        self,
        session_id: str,
        org_id: str,
    ) -> None:
        """
        If the primary device disconnects, terminate the entire session
        (initial production behavior — no auto-transfer of controller authority).
        """
        asyncio.create_task(self.stop_session(
            org_id, session_id,
            actor_email="system@flow.internal",
            reason="primary_disconnected",
        ))


# ── Module-level singleton ─────────────────────────────────────────────────────

_service: DeviceControlService | None = None


def get_device_control_service() -> DeviceControlService:
    global _service
    if _service is None:
        _service = DeviceControlService()
    return _service


# ── Coord translation utility ──────────────────────────────────────────────────

def translate_cursor(
    x_source: float,
    y_source: float,
    width_source: float,
    height_source: float,
    width_target: float,
    height_target: float,
) -> tuple[int, int]:
    """
    Map a cursor position from one screen's coordinate space to another's.
    Clamps to valid target bounds. Safe with zero-size inputs.
    """
    if width_source <= 0 or height_source <= 0:
        return 0, 0
    rel_x = max(0.0, min(1.0, x_source / width_source))
    rel_y = max(0.0, min(1.0, y_source / height_source))
    tx = int(rel_x * width_target)
    ty = int(rel_y * height_target)
    return (
        max(0, min(int(width_target) - 1, tx)),
        max(0, min(int(height_target) - 1, ty)),
    )


def find_target_device(
    current_x: float,
    current_y: float,
    members: list[dict],
    current_device_id: str,
    direction: str,   # "left"|"right"|"top"|"bottom"
) -> dict | None:
    """
    Given the cursor's virtual canvas position and movement direction,
    find the best adjacent device. Returns the matching member dict or None.

    Virtual canvas: each device occupies a rect at (position_x, position_y)
    with given width/height. Devices may be arranged arbitrarily.
    """
    current = next((m for m in members if m["device_id"] == current_device_id), None)
    if current is None:
        return None

    cx1 = current["position_x"]
    cy1 = current["position_y"]
    cx2 = cx1 + current["width"]
    cy2 = cy1 + current["height"]

    candidates = []
    for m in members:
        if m["device_id"] == current_device_id or not m.get("enabled", True):
            continue
        mx1 = m["position_x"]
        my1 = m["position_y"]
        mx2 = mx1 + m["width"]
        my2 = my1 + m["height"]

        if direction == "right" and mx1 >= cx2:
            # Overlap in Y
            overlap = max(0, min(cy2, my2) - max(cy1, my1))
            if overlap > 0:
                candidates.append((mx1, m))
        elif direction == "left" and mx2 <= cx1:
            overlap = max(0, min(cy2, my2) - max(cy1, my1))
            if overlap > 0:
                candidates.append((-mx2, m))
        elif direction == "bottom" and my1 >= cy2:
            overlap = max(0, min(cx2, mx2) - max(cx1, mx1))
            if overlap > 0:
                candidates.append((my1, m))
        elif direction == "top" and my2 <= cy1:
            overlap = max(0, min(cx2, mx2) - max(cx1, mx1))
            if overlap > 0:
                candidates.append((-my2, m))

    if not candidates:
        return None

    # Pick the closest candidate
    candidates.sort(key=lambda t: t[0])
    return candidates[0][1]


# ── Helper ────────────────────────────────────────────────────────────────────

def _device_row_to_dict(row: asyncpg.Record | None) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    # Serialize UUIDs and datetimes
    for k, v in d.items():
        if isinstance(v, uuid.UUID):
            d[k] = str(v)
        elif hasattr(v, "isoformat"):
            d[k] = v.isoformat()
        # asyncpg returns JSONB as dict/list already
    return d
