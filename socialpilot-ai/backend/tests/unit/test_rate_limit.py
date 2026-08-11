"""Exercises the slowapi wiring itself (in isolation from the real app, whose
auth endpoints are deliberately configured with a high limit in tests so the
auth test suite isn't flaky) — proves a `Limiter` with a tight limit actually
blocks the Nth request, using the exact exception-handler wiring `app.main`
uses for the real app.
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address


def _build_tiny_app(limit: str) -> FastAPI:
    limiter = Limiter(key_func=get_remote_address, storage_uri="memory://")
    app = FastAPI()
    app.state.limiter = limiter

    async def _handler(request: Request, exc: RateLimitExceeded):
        from starlette.responses import JSONResponse

        return JSONResponse(status_code=429, content={"detail": "rate limited"})

    app.add_exception_handler(RateLimitExceeded, _handler)
    app.add_middleware(SlowAPIMiddleware)

    @app.get("/ping")
    @limiter.limit(limit)
    async def ping(request: Request):
        return {"pong": True}

    return app


def test_requests_under_the_limit_succeed() -> None:
    app = _build_tiny_app("5/minute")
    client = TestClient(app)
    for _ in range(5):
        assert client.get("/ping").status_code == 200


def test_requests_over_the_limit_are_rejected_with_429() -> None:
    app = _build_tiny_app("2/minute")
    client = TestClient(app)
    assert client.get("/ping").status_code == 200
    assert client.get("/ping").status_code == 200
    third = client.get("/ping")
    assert third.status_code == 429
    assert third.json()["detail"] == "rate limited"
