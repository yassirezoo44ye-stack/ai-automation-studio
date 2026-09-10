# Flow — Multi-Device Control

Control up to **5 computers** (1 primary + up to 4 secondaries) from a single keyboard and mouse.

---

## Table of Contents

1. [Architecture](#architecture)
2. [Security Model](#security-model)
3. [Device Agent](#device-agent)
4. [Backend API](#backend-api)
5. [WebSocket Protocol](#websocket-protocol)
6. [Session Lifecycle](#session-lifecycle)
7. [Screen Layout & Edge Switching](#screen-layout--edge-switching)
8. [Failsafe Mechanisms](#failsafe-mechanisms)
9. [Installation](#installation)
10. [Development](#development)

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     Flow Platform (FastAPI)                      │
│                                                                  │
│  REST API          WebSocket           Database                  │
│  /api/devices/*    /ws/device/{id}     PostgreSQL + RLS          │
│  /api/device-      ─────────────────   devices                   │
│  sessions/*        ControlRegistry     device_enrollment_tokens  │
│                    (in-memory)         device_control_sessions   │
│                                        device_session_members    │
└────────────────────────┬───────────────────────────────────────┘
                         │ WebSocket (WSS)
          ┌──────────────┼──────────────────┐
          │              │                  │
   ┌──────▼──────┐ ┌─────▼──────┐ ┌────────▼───────┐
   │  PRIMARY PC │ │SECONDARY 1 │ │  SECONDARY 2   │
   │             │ │            │ │                │
   │ Flow Agent  │ │ Flow Agent │ │  Flow Agent    │
   │ (captures   │ │ (injects   │ │  (injects      │
   │  input)     │ │  input)    │ │   input)       │
   └─────────────┘ └────────────┘ └────────────────┘
```

**Key constraints:**
- Maximum **5 devices per session** (primary counts as 1 of 5)
- The **browser UI never captures OS input** — all input capture/injection lives in the native Device Agent
- All communication is over **TLS-protected WebSocket** (WSS)
- Each tenant's devices are **fully isolated** via Row-Level Security (RLS)

---

## Security Model

### Enrollment Token Security

1. A cryptographically random 32-byte token is generated
2. Only the **SHA-256 hash** is stored in the database — the raw token is never persisted
3. The raw token is returned once to the admin for installation on the target device
4. The token is **single-use** and expires after **24 hours**

### Device Credential Security

1. On enrollment, a 32-byte random credential is generated
2. Only the **SHA-256 hash** is stored in the database
3. The raw credential is returned once to the agent during enrollment
4. The agent stores it using **Windows DPAPI** (encrypted to the local machine account — never plaintext on disk)
5. Credentials can be rotated (old credential immediately invalidated)

### Input Security

- **NEVER** log keyboard virtual-key codes (`vk`) or scan codes (`scan`)
- **NEVER** persist mouse coordinates or keystrokes to any database
- Mouse moves are **coalesced at 60 Hz** — only position is forwarded, nothing stored
- Keyboard events carry only `vk`, `scan`, `flags`, `action` — forwarded over TLS, never written to disk

### Tenant Isolation

- All device tables are registered in the RLS framework (`_RLS_TABLES`)
- Every query includes `organization_id` in the WHERE clause
- The `_ControlRegistry` is keyed by `(org_id, session_id)` — cross-tenant access is architecturally impossible at the service layer

---

## Device Agent

The native agent runs on each machine being controlled.

### Requirements

- Python 3.9+ (Windows 10/11 64-bit recommended)
- Dependencies: `websockets`, `aiohttp`, `pywin32` (Windows), `pystray`, `pillow`

### Installation

```bash
# Install dependencies
pip install websockets aiohttp pywin32 pystray pillow

# Enroll the device (run once — token from Flow web UI)
python -m agent enroll \
    --server wss://your-flow-server.com \
    --token FLOW_ENROLLMENT_TOKEN_HERE

# Start the agent (runs in background, shows system tray icon)
python -m agent run
```

### Agent Commands

| Command | Description |
|---------|-------------|
| `python -m agent enroll --server URL --token TOKEN` | First-time device enrollment |
| `python -m agent run` | Start the agent (uses stored credentials) |
| `python -m agent clear` | Remove stored credentials (before decommissioning) |
| `python -m agent version` | Print agent version |

### Environment Variable Overrides (testing only)

| Variable | Description |
|----------|-------------|
| `FLOW_SERVER_URL` | WebSocket server URL |
| `FLOW_DEVICE_ID` | Device UUID |
| `FLOW_CREDENTIAL` | Raw credential (use enrollment in production) |

---

## Backend API

### Devices

| Method | Endpoint | Permission | Description |
|--------|----------|------------|-------------|
| `GET` | `/api/devices/` | `devices:read` | List all devices in org |
| `GET` | `/api/devices/{id}` | `devices:read` | Get one device |
| `POST` | `/api/devices/enroll-token` | `devices:create` | Generate enrollment token |
| `POST` | `/api/devices/enroll` | — (public) | Consume enrollment token (called by agent) |
| `POST` | `/api/devices/{id}/revoke` | `devices:revoke` | Revoke a device |
| `DELETE` | `/api/devices/{id}` | `devices:delete` | Delete a device record |
| `POST` | `/api/devices/{id}/rotate-credential` | `devices:update` | Rotate device credential |

### Control Sessions

| Method | Endpoint | Permission | Description |
|--------|----------|------------|-------------|
| `GET` | `/api/device-sessions/` | `device_sessions:read` | List all sessions |
| `POST` | `/api/device-sessions/` | `device_sessions:create` | Create a session |
| `GET` | `/api/device-sessions/{id}` | `device_sessions:read` | Get a session |
| `POST` | `/api/device-sessions/{id}/start` | `device_sessions:control` | Start a session |
| `POST` | `/api/device-sessions/{id}/stop` | `device_sessions:control` | Stop a session |
| `PATCH` | `/api/device-sessions/{id}/layout` | `device_sessions:control` | Update device layout |

---

## WebSocket Protocol

Agents connect to `/ws/device/{device_id}` with a raw WebSocket (not the browser-ticket-based path).

### Protocol Version: 1

All frames are JSON objects with:
```json
{
  "version": 1,
  "type": "...",
  "timestamp": 1234567890123
}
```

### Authentication Handshake

```
Agent → Server: {"type": "auth", "device_id": "...", "credential": "...", "session_id": "...", "session_token": "..."}
Server → Agent: {"type": "auth_ok"} | {"type": "auth_fail", "reason": "..."}
```

### Frame Types

| Type | Direction | Description |
|------|-----------|-------------|
| `heartbeat` | Agent→Server | Keep-alive ping |
| `heartbeat_ack` | Server→Agent | Heartbeat acknowledgement |
| `display_config` | Agent→Server | Screen resolution/monitor info |
| `mouse_move` | Primary→Server→Secondary | Cursor position |
| `mouse_down` | Primary→Server→Secondary | Button press (never dropped) |
| `mouse_up` | Primary→Server→Secondary | Button release (never dropped) |
| `mouse_scroll` | Primary→Server→Secondary | Scroll delta |
| `key_down` | Primary→Server→Secondary | Key press (never dropped, never logged) |
| `key_up` | Primary→Server→Secondary | Key release (never dropped, never logged) |
| `device_switch` | Primary→Server→All | Cursor moved to a different device |
| `session_start` | Server→All | Session is now active |
| `session_stop` | Server→All | Session ended |
| `layout_update` | Server→All | Screen layout changed mid-session |

### Mouse Coalescing

Mouse move events are coalesced at **60 Hz** (16 ms window) on the primary agent before forwarding. Button events (`mouse_down`, `mouse_up`) and key events are **never coalesced** — they are sent immediately via `send_now()` to preserve fidelity.

---

## Session Lifecycle

```
IDLE ──────────────────────────────────────────────────────────┐
  │                                                             │
  │  POST /api/device-sessions/                                 │
  ▼                                                             │
PENDING ── POST /api/device-sessions/{id}/start ─────────────▶ │
  │                                                             │
  │  Server: sends "session_start" to all member agents         │
  ▼                                                             │
ACTIVE                                                          │
  │                                                             │
  ├── POST /api/device-sessions/{id}/stop ──────────────────── │
  ├── Primary disconnects (auto-stop) ─────────────────────── │
  └── Failsafe hotkey on any device ──────────────────────────▶│
                                                                │
  Server sends "session_stop" to all remaining agents           │
  All agents release hooks, restore local input                 │
  Session marked "stopped" in database                          │
                                                                │
  └─────────────────────────────────────────────────────────────┘
```

---

## Screen Layout & Edge Switching

The layout editor allows placing devices on a virtual canvas. When the cursor reaches a configured edge on the primary device, control switches to the neighboring device.

### Virtual Canvas

Each device occupies a rectangle `(position_x, position_y, width, height)` in canvas units. The admin drags devices in the Layout Editor to set their positions.

### Edge Detection

1. The agent checks if the cursor is within `edge_margin` pixels (default: 2) of a screen edge
2. The cursor position is translated to virtual canvas coordinates
3. `find_target_device()` searches for an enabled neighbor in the direction of travel
4. On match, `translate_cursor()` maps the position to the target device's coordinate space
5. A `device_switch` frame is sent to the server, which forwards it to all session members

### Coordinate Translation

```
target_x = clamp(round(x_source * width_target / width_source), 0, width_target - 1)
target_y = clamp(round(y_source * height_target / height_source), 0, height_target - 1)
```

Different monitor resolutions are handled transparently.

---

## Failsafe Mechanisms

### Failsafe Hotkey: `Ctrl + Shift + Alt + F12`

- Installed as a low-level keyboard hook on **every device** in the session
- When pressed, the hook proc calls `uninstall()` **before** any network operation
- The uninstall is purely local (ctypes calls) — **network-independent**
- After hooks are uninstalled, local input is immediately restored
- A best-effort `session_stop` frame is sent to the server (may fail if disconnected — that's acceptable)

### Primary Disconnect

- If the primary device's WebSocket disconnects for any reason, `handle_primary_disconnect()` is called
- This immediately calls `stop_session()`, which broadcasts `session_stop` to all remaining agents
- All agents uninstall their hooks in their own `finally` blocks

### Agent State Machine

```
IDLE → CONNECTING → CONNECTED → CONTROL_ACTIVE → CONNECTED/IDLE
```

On **any** error or disconnect at `CONTROL_ACTIVE`, hooks are released before state is updated.

---

## Installation

### Database Schema

The schema is created automatically on server startup via `init_device_control_schema(conn)` in `app/factory.py`. No manual migration is needed.

Tables created:
- `devices` — enrolled device registry
- `device_enrollment_tokens` — single-use enrollment tokens (hash only)
- `device_control_sessions` — session records
- `device_control_session_members` — per-session device layout
- `device_session_authorizations` — per-session device auth tokens

### RBAC Permissions

Added to all roles that previously had workspace access:
- `devices:read`, `devices:create`, `devices:update`, `devices:revoke`, `devices:delete`
- `device_sessions:read`, `device_sessions:create`, `device_sessions:control`

---

## Development

### Running Tests

```bash
# Backend tests (pure-math + security regression suite)
pytest tests/test_device_control.py -v

# Specific test class
pytest tests/test_device_control.py::TestTranslateCursor -v
pytest tests/test_device_control.py::TestNoInputLogging -v
pytest tests/test_device_control.py::TestTenantIsolation -v
```

### Agent Development (Windows)

```bash
cd agent

# Run without system tray (for debugging)
python -m agent run --no-tray

# Check enrolled credential
python -c "from agent.security.credentials import load_credential; print(load_credential()[:2])"
```

### Security Review Checklist

Before every PR that touches this feature:

- [ ] `tests/test_device_control.py::TestNoInputLogging` passes — no vk/scan logged
- [ ] `tests/test_device_control.py::TestTenantIsolation` passes — all tables in RLS
- [ ] No new `INSERT` into tables that store keystrokes or raw coordinates
- [ ] `_hash_token()` / `_generate_credential()` still produce SHA-256 hashes (not plaintext)
- [ ] `agent/security/credentials.py` still uses DPAPI on Windows
- [ ] Failsafe hotkey still calls `uninstall()` before any `asyncio.create_task()`

---

*Feature branch: `feature/multi-device-control`*  
*Protocol version: v1*  
*Max devices per session: 5*
