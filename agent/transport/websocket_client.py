"""
Flow Device Agent — WebSocket Transport with exponential backoff reconnect.

Reconnect schedule:
  1s → 2s → 4s → 8s → 16s → 30s → 60s (max)

Stops reconnecting if:
  - device has been revoked (server sends auth_fail with reason="device_revoked")
  - explicit stop() is called

TLS:
  - Production: always WSS (wss://)
  - Development: WS allowed when server_url starts with ws:// (not wss://)

Never puts long-lived JWT in the URL — uses device credential for auth.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Callable, Optional

log = logging.getLogger(__name__)

_BACKOFF_STEPS = [1, 2, 4, 8, 16, 30, 60]


class DeviceWebSocketClient:
    def __init__(
        self,
        server_url: str,
        device_id: str,
        credential: str,
        on_message: Callable[[dict], None],
        on_connected: Callable[[], None],
        on_disconnected: Callable[[], None],
    ):
        self._server_url = server_url.rstrip("/")
        self._device_id = device_id
        self._credential = credential   # NOT logged
        self._on_message = on_message
        self._on_connected = on_connected
        self._on_disconnected = on_disconnected

        self._ws = None
        self._running = False
        self._revoked = False
        self._send_queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._session_id: Optional[str] = None
        self._session_token: Optional[str] = None

    def set_session(self, session_id: str, session_token: str) -> None:
        self._session_id = session_id
        self._session_token = session_token

    def clear_session(self) -> None:
        self._session_id = None
        self._session_token = None

    async def send(self, frame: dict) -> None:
        """Queue a frame for sending. Drops if queue is full (backpressure)."""
        try:
            self._send_queue.put_nowait(frame)
        except asyncio.QueueFull:
            # High-frequency frames (mouse_move) may be dropped under pressure
            pass

    async def send_now(self, frame: dict) -> bool:
        """Send a frame immediately — for auth, heartbeat, keyboard events."""
        if self._ws is None:
            return False
        try:
            await self._ws.send(json.dumps(frame))
            return True
        except Exception:
            return False

    async def run(self) -> None:
        """Connect and maintain the WebSocket connection with reconnect."""
        self._running = True
        backoff_idx = 0

        while self._running and not self._revoked:
            try:
                await self._connect_and_run()
                # Successful connection — reset backoff
                backoff_idx = 0
            except Exception as e:
                log.warning("ws_client: connection error: %s", type(e).__name__)

            if not self._running or self._revoked:
                break

            # Backoff before reconnect
            delay = _BACKOFF_STEPS[min(backoff_idx, len(_BACKOFF_STEPS) - 1)]
            backoff_idx += 1
            log.info("ws_client: reconnecting in %ds", delay)
            await asyncio.sleep(delay)

    async def _connect_and_run(self) -> None:
        import websockets

        ws_url = f"{self._server_url}/ws/device/{self._device_id}"
        # Never log the credential — only log the URL (without credentials)
        log.info("ws_client: connecting to %s", ws_url)

        async with websockets.connect(
            ws_url,
            ssl=ws_url.startswith("wss://"),
            ping_interval=None,      # We manage our own heartbeat
            max_size=4096,
            close_timeout=5,
        ) as ws:
            self._ws = ws
            log.info("ws_client: connected")

            # Send auth frame — credential NOT logged
            auth_frame = {
                "version":       1,
                "type":          "auth",
                "device_id":     self._device_id,
                "credential":    self._credential,
                "session_id":    self._session_id,
                "session_token": self._session_token,
            }
            await ws.send(json.dumps(auth_frame))

            # Wait for auth_ok / auth_fail
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=15)
                msg = json.loads(raw)
            except (asyncio.TimeoutError, json.JSONDecodeError) as e:
                log.warning("ws_client: auth handshake failed: %s", type(e).__name__)
                return

            if msg.get("type") == "auth_fail":
                reason = msg.get("reason", "unknown")
                log.warning("ws_client: auth failed reason=%s", reason)
                if reason in ("device_revoked", "invalid_credential"):
                    self._revoked = True
                return

            if msg.get("type") != "auth_ok":
                log.warning("ws_client: unexpected auth response type=%s", msg.get("type"))
                return

            log.info("ws_client: authenticated")
            self._on_connected()

            # Run send-queue drainer + receive loop concurrently
            try:
                await asyncio.gather(
                    self._send_loop(ws),
                    self._recv_loop(ws),
                )
            except Exception:
                pass
            finally:
                self._ws = None
                self._on_disconnected()

    async def _send_loop(self, ws) -> None:
        """Drain the outbound queue — runs concurrently with _recv_loop."""
        while True:
            try:
                frame = await asyncio.wait_for(self._send_queue.get(), timeout=5)
                await ws.send(json.dumps(frame))
            except asyncio.TimeoutError:
                # Idle — send a heartbeat
                await ws.send(json.dumps({
                    "version":   1,
                    "type":      "heartbeat",
                    "timestamp": int(time.time() * 1000),
                }))
            except Exception:
                raise

    async def _recv_loop(self, ws) -> None:
        """Process inbound frames from the server."""
        async for raw in ws:
            if not isinstance(raw, str):
                continue
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            mtype = msg.get("type", "")

            if mtype == "heartbeat_ack":
                # Server acknowledged our heartbeat — connection is alive
                continue

            if mtype == "session_stop":
                reason = msg.get("reason", "")
                log.info("ws_client: session_stop reason=%s", reason)
                if reason == "device_revoked":
                    self._revoked = True
                # Deliver to application layer for hook release
                self._on_message(msg)
                continue

            if mtype == "auth_fail":
                reason = msg.get("reason", "")
                log.warning("ws_client: received auth_fail reason=%s", reason)
                if reason in ("device_revoked",):
                    self._revoked = True
                return

            # Deliver all other frames to the application layer
            # NEVER log the frame contents for mouse_move/key_down/key_up
            try:
                self._on_message(msg)
            except Exception as e:
                log.warning("ws_client: on_message error: %s", type(e).__name__)

    def stop(self) -> None:
        self._running = False
        if self._ws:
            asyncio.create_task(self._ws.close())
