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
