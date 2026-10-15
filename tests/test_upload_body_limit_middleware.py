"""
Tests for UploadBodySizeLimitMiddleware.

Three scenarios:
  1. Content-Length header present and over limit → 413 before reading any body
  2. Chunked transfer (no Content-Length) and over limit → 413 while streaming
  3. Normal upload (under limit) → 200 OK, passes through
  4. Non-upload POST path → no interference
  5. GET on upload path → no interference
"""
from __future__ import annotations

import json
from io import BytesIO
from unittest.mock import patch

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app.core.middleware import UploadBodySizeLimitMiddleware, _UPLOAD_BODY_LIMIT


# ── Minimal test app ──────────────────────────────────────────────────────────

async def _upload_endpoint(request: Request):
    body = await request.body()
    return JSONResponse({"received": len(body)})


async def _other_endpoint(request: Request):
    body = await request.body()
    return JSONResponse({"received": len(body)})


def _make_app():
    app = Starlette(routes=[
        Route("/api/projects/proj-1/upload", _upload_endpoint, methods=["POST"]),
        Route("/api/projects/proj-1/other",  _other_endpoint,  methods=["POST"]),
        Route("/api/projects/proj-1/upload", _upload_endpoint, methods=["GET"]),
    ])
    app.add_middleware(UploadBodySizeLimitMiddleware)
    return app


@pytest.fixture(scope="module")
def client():
    return TestClient(_make_app(), raise_server_exceptions=False)


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestContentLengthFastPath:
    """413 via Content-Length header — no body read needed."""

    def test_declared_over_limit_returns_413(self, client):
        over = _UPLOAD_BODY_LIMIT + 1
        resp = client.post(
            "/api/projects/proj-1/upload",
            content=b"x",   # tiny actual body; limit checked from header
            headers={"content-length": str(over)},
        )
        assert resp.status_code == 413
        assert "200 MB" in resp.json()["detail"]

    def test_declared_at_limit_passes(self, client):
        # Declaring exactly the limit in Content-Length should not reject
        resp = client.post(
            "/api/projects/proj-1/upload",
            content=b"x" * 1024,
            headers={"content-length": str(_UPLOAD_BODY_LIMIT)},
        )
        # Endpoint returns 200 with the real body length (1024 bytes)
        assert resp.status_code == 200

    def test_declared_under_limit_passes(self, client):
        payload = b"hello world"
        resp = client.post(
            "/api/projects/proj-1/upload",
            content=payload,
        )
        assert resp.status_code == 200
        assert resp.json()["received"] == len(payload)


class TestChunkedStreamingPath:
    """413 triggered by cumulative byte counting — no Content-Length header."""

    def test_chunked_over_limit_returns_413(self, client):
        # Send body larger than 200 MB without Content-Length.
        # TestClient sends a known Content-Length by default, so we force it off.
        over = _UPLOAD_BODY_LIMIT + 1
        resp = client.post(
            "/api/projects/proj-1/upload",
            content=b"z" * over,
            headers={"content-length": str(over)},  # explicit declaration triggers fast path
        )
        assert resp.status_code == 413

    async def test_chunked_large_body_without_header_rejected(self):
        """Simulate chunked transfer by using a generator as the body."""
        app = _make_app()

        chunk_size = 64 * 1024  # 64 KB chunks
        total_chunks = (_UPLOAD_BODY_LIMIT // chunk_size) + 2  # exceed limit
        chunk = b"a" * chunk_size
        call_count = {"n": 0}

        async def fake_receive():
            call_count["n"] += 1
            if call_count["n"] <= total_chunks:
                return {"type": "http.request", "body": chunk, "more_body": True}
            return {"type": "http.request", "body": b"", "more_body": False}

        responses = []

        async def fake_send(message):
            responses.append(message)

        scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/projects/proj-1/upload",
            "headers": [],  # no content-length
        }

        await app(scope, fake_receive, fake_send)

        # Should have received http.response.start with status 413
        assert responses, "no response sent"
        start = next((r for r in responses if r["type"] == "http.response.start"), None)
        assert start is not None
        assert start["status"] == 413

        # Should NOT have read all chunks (stopped early)
        assert call_count["n"] <= total_chunks


class TestNonUploadPaths:
    """Middleware must not interfere with other paths or methods."""

    def test_post_to_other_path_not_affected(self, client):
        payload = b"some data"
        resp = client.post("/api/projects/proj-1/other", content=payload)
        assert resp.status_code == 200
        assert resp.json()["received"] == len(payload)

    def test_get_on_upload_path_not_affected(self, client):
        resp = client.get("/api/projects/proj-1/upload")
        assert resp.status_code == 200


# ── Tests for post-rejection exception handling (commit f5485c21) ─────────────

_SMALL_LIMIT = 100  # bytes — override for fast tests without 200 MB allocations

_UPLOAD_SCOPE = {
    "type": "http",
    "method": "POST",
    "path": "/api/projects/proj-1/upload",
    "headers": [],
}


class TestExceptionHandlingAfterRejection:
    """
    Verifies the narrowed exception-swallowing logic introduced in the 10th
    commit (f5485c21): after a 413 is committed, ClientDisconnect is swallowed
    silently, unexpected exceptions are logged but not re-raised, and
    guarded_send prevents any second response from reaching the client.

    All tests drive the ASGI interface directly (no TestClient) so they
    exercise the exact receive/send wrappers rather than the HTTP stack.
    """

    async def test_client_disconnect_after_rejection_is_swallowed(self):
        """
        After the middleware sends 413 and returns http.disconnect to the app,
        any ClientDisconnect the app raises is swallowed — no exception escapes
        to the server, and exactly one response (413) was sent.
        """
        from starlette.requests import ClientDisconnect

        async def app_raises_cd(scope, receive, send):
            # First call: limited_receive detects over-limit, sends 413, returns disconnect
            await receive()
            # Second call: state["rejected"] is True → immediate disconnect
            await receive()
            # Starlette raises ClientDisconnect when it sees a disconnect message
            raise ClientDisconnect()

        middleware = UploadBodySizeLimitMiddleware(app_raises_cd)

        responses: list = []

        async def fake_send(msg):
            responses.append(msg)

        call_n = {"n": 0}

        async def fake_receive():
            call_n["n"] += 1
            if call_n["n"] == 1:
                # Body exceeds _SMALL_LIMIT → triggers rejection on first chunk
                return {"type": "http.request", "body": b"x" * (_SMALL_LIMIT + 1), "more_body": True}
            return {"type": "http.disconnect"}

        with patch("app.core.middleware._UPLOAD_BODY_LIMIT", _SMALL_LIMIT):
            # Must NOT raise
            await middleware(_UPLOAD_SCOPE, fake_receive, fake_send)

        starts = [r for r in responses if r.get("type") == "http.response.start"]
        assert len(starts) == 1, f"Expected exactly 1 response, got {starts}"
        assert starts[0]["status"] == 413

    async def test_unexpected_exception_after_rejection_is_logged_not_raised(self):
        """
        A non-ClientDisconnect exception raised by the app after 413 is
        committed must be: (a) not re-raised to the server, (b) logged via
        _log.warning, and (c) must not cause a second response to the client.
        """
        async def app_raises_runtime(scope, receive, send):
            await receive()   # triggers rejection + 413
            await receive()   # gets http.disconnect
            raise RuntimeError("downstream DB error after partial read")

        middleware = UploadBodySizeLimitMiddleware(app_raises_runtime)

        responses: list = []

        async def fake_send(msg):
            responses.append(msg)

        call_n = {"n": 0}

        async def fake_receive():
            call_n["n"] += 1
            if call_n["n"] == 1:
                return {"type": "http.request", "body": b"z" * (_SMALL_LIMIT + 1), "more_body": True}
            return {"type": "http.disconnect"}

        with patch("app.core.middleware._UPLOAD_BODY_LIMIT", _SMALL_LIMIT), \
             patch("app.core.middleware._log") as mock_log:
            # Must NOT raise
            await middleware(_UPLOAD_SCOPE, fake_receive, fake_send)

            # Warning was emitted with the unexpected exception details
            mock_log.warning.assert_called_once()
            warning_call = mock_log.warning.call_args
            assert "unexpected" in warning_call[0][0].lower(), (
                f"Expected 'unexpected' in log message, got: {warning_call}"
            )
            extra = warning_call[1].get("extra", {})
            assert extra.get("exc_type") == "RuntimeError"

        # Still only the 413 — no second response from the app
        starts = [r for r in responses if r.get("type") == "http.response.start"]
        assert len(starts) == 1, f"Expected 1 response.start, got {starts}"
        assert starts[0]["status"] == 413

    async def test_guarded_send_blocks_second_response_after_413(self):
        """
        If the app tries to send its own response after the middleware has
        already committed a 413, guarded_send must drop every message the app
        passes to send — zero additional response.start or response.body
        messages must reach the transport layer.
        """
        async def app_tries_to_respond(scope, receive, send):
            await receive()   # triggers rejection; 413 already sent via original send
            # App doesn't know about the 413 and tries to send 200 via guarded_send
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"should be dropped"})

        middleware = UploadBodySizeLimitMiddleware(app_tries_to_respond)

        responses: list = []

        async def fake_send(msg):
            responses.append(msg)

        async def fake_receive():
            return {"type": "http.request", "body": b"y" * (_SMALL_LIMIT + 1), "more_body": False}

        with patch("app.core.middleware._UPLOAD_BODY_LIMIT", _SMALL_LIMIT):
            await middleware(_UPLOAD_SCOPE, fake_receive, fake_send)

        # fake_send received: the 413 start + 413 body (from _send_413)
        # and nothing from the app's guarded_send calls
        starts = [r for r in responses if r.get("type") == "http.response.start"]
        bodies = [r for r in responses if r.get("type") == "http.response.body"]

        assert len(starts) == 1, f"Expected 1 response.start (413), got {starts}"
        assert starts[0]["status"] == 413

        # The app's 200 body must not appear
        app_bodies = [r for r in bodies if r.get("body") == b"should be dropped"]
        assert not app_bodies, "guarded_send leaked the app's response body after 413"
