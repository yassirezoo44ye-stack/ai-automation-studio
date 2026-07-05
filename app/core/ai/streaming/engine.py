"""
StreamingEngine — shared SSE streaming layer for all AI responses.

Provides: token streaming, tool events, heartbeat, progress,
          structured errors, cancellation, resume-from-offset.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Optional

from ..events.bus    import EventBus
from ..events.events import StreamCancelled, StreamResumed


@dataclass
class StreamSession:
    session_id:  str = field(default_factory=lambda: str(uuid.uuid4()))
    request_id:  str = ""
    cancelled:   bool   = False
    token_count: int    = 0
    started_at:  float  = field(default_factory=time.time)
    buffer:      list[dict[str, Any]] = field(default_factory=list)   # for resume


def _sse_line(event_type: str, data: Any) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


class StreamingEngine:
    """
    Wraps any async-generator AI source and adds:
    - Heartbeat (keep-alive pings every N seconds)
    - Cancellation support
    - Token buffering for resume
    - Structured error events
    - Progress events
    """

    def __init__(
        self,
        bus:              EventBus,
        heartbeat_s:      float = 15.0,
        max_buffer:       int   = 200,
    ) -> None:
        self._bus         = bus
        self._heartbeat_s = heartbeat_s
        self._max_buffer  = max_buffer
        self._sessions:   dict[str, StreamSession] = {}

    def create_session(self, request_id: str = "") -> StreamSession:
        s = StreamSession(request_id=request_id)
        self._sessions[s.session_id] = s
        return s

    def cancel(self, session_id: str, reason: str = "user") -> None:
        session = self._sessions.get(session_id)
        if session:
            session.cancelled = True
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._bus.emit(StreamCancelled(
                    request_id=session.request_id,
                    reason=reason,
                )))
            except RuntimeError:
                pass   # No running loop — event skipped; cancellation flag is still set

    async def stream(
        self,
        source:   AsyncGenerator[dict[str, Any], None],
        session:  StreamSession,
        from_offset: int = 0,
    ) -> AsyncGenerator[str, None]:
        """
        Wraps `source` with SSE formatting, heartbeat, cancellation.
        Yields raw SSE-formatted strings.
        """
        if from_offset > 0:
            await self._bus.emit(StreamResumed(
                request_id=session.request_id,
                from_offset=from_offset,
            ))
            # Replay buffered events
            for event in session.buffer[from_offset:]:
                yield _sse_line(event.get("type", "token"), event)

        last_hb = time.time()

        try:
            async for chunk in source:
                if session.cancelled:
                    yield _sse_line("cancelled", {"reason": "user"})
                    return

                # Heartbeat
                now = time.time()
                if now - last_hb > self._heartbeat_s:
                    yield _sse_line("heartbeat", {"ts": now})
                    last_hb = now

                chunk_type = chunk.get("type", "token")
                yield _sse_line(chunk_type, chunk)

                # Buffer (capped)
                if len(session.buffer) < self._max_buffer:
                    session.buffer.append(chunk)
                session.token_count += 1

        except Exception as exc:
            yield _sse_line("error", {
                "message":      str(exc),
                "request_id":   session.request_id,
            })
        finally:
            yield _sse_line("done", {
                "session_id":  session.session_id,
                "token_count": session.token_count,
            })

    async def stream_text(
        self,
        text: str,
        session: Optional[StreamSession] = None,
        chunk_size: int = 20,
    ) -> AsyncGenerator[str, None]:
        """Utility: stream a static string as tokens (useful for testing/replay)."""
        if session is None:
            session = self.create_session()

        async def _gen() -> AsyncGenerator[dict, None]:
            for i in range(0, len(text), chunk_size):
                yield {"type": "token", "content": text[i:i + chunk_size]}
                await asyncio.sleep(0)

        async for chunk in self.stream(_gen(), session):
            yield chunk

    def get_session(self, session_id: str) -> Optional[StreamSession]:
        return self._sessions.get(session_id)

    def diagnostics(self) -> dict[str, Any]:
        return {
            "active_sessions": len(self._sessions),
            "total_tokens":    sum(s.token_count for s in self._sessions.values()),
        }
