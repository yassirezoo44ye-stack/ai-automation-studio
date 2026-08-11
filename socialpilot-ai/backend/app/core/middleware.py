"""Security headers applied to every response.

Implemented as plain ASGI middleware (not `starlette.middleware.base.BaseHTTPMiddleware`)
on purpose: `BaseHTTPMiddleware` runs the downstream app in a spawned task behind an
in-memory stream, which is known to corrupt event-loop/task affinity for greenlet-bridged
async DB drivers (SQLAlchemy async + asyncpg) — requests intermittently fail with
"Future attached to a different loop" once a DB call happens downstream of it. Wrapping
`send` directly avoids the extra task entirely.
"""
from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp, *, is_production: bool) -> None:
        self._app = app
        self._is_production = is_production

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.setdefault("headers", []))
                headers.extend(
                    [
                        (b"x-content-type-options", b"nosniff"),
                        (b"x-frame-options", b"DENY"),
                        (b"referrer-policy", b"strict-origin-when-cross-origin"),
                        (b"permissions-policy", b"geolocation=(), microphone=(), camera=()"),
                    ]
                )
                if self._is_production:
                    headers.append(
                        (b"strict-transport-security", b"max-age=63072000; includeSubDomains")
                    )
                message["headers"] = headers
            await send(message)

        await self._app(scope, receive, send_wrapper)
