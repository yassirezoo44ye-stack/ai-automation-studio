"""Security and request tests; all DB calls are mocked, no external requests."""

import hashlib
import io
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from pypdf import PdfWriter
from starlette.requests import Request

from app.routers import study_library as study
from app.study.payhip import parse_event

API_KEY = "local-test-payhip-key"
PRODUCT = "Study42"


def payload(**changes):
    event = {
        "id": "order-1",
        "email": "Learner@example.com",
        "price": 1500,
        "type": "paid",
        "items": [{"product_key": PRODUCT}],
        "signature": hashlib.sha256(API_KEY.encode()).hexdigest(),
    }
    return dict(event, **changes)


def test_purchase_normalizes_email_and_full_refund():
    assert parse_event(payload(), API_KEY, PRODUCT).buyer_email == "learner@example.com"
    assert parse_event(
        payload(type="refunded", amount_refunded=1500), API_KEY, PRODUCT
    ).refunded


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"signature": "wrong"}, 401),
        ({"signature": "é" * 64}, 401),
        ({"signature": None}, 401),
        ({"email": "invalid"}, 400),
        ({"id": "../order"}, 400),
        ({"price": 0}, 400),
        ({"price": True}, 400),
        ({"price": "1500"}, 400),
        ({"items": {}}, 400),
        ({"type": "refunded", "amount_refunded": -1}, 400),
        ({"type": "refunded", "amount_refunded": 2000}, 400),
    ],
)
def test_invalid_purchase_rejected(changes, code):
    with pytest.raises(HTTPException) as exc:
        parse_event(payload(**changes), API_KEY, PRODUCT)
    assert exc.value.status_code == code


@pytest.mark.parametrize(
    "changes",
    [
        {"items": [{"product_key": "unrelated"}]},
        {"is_gift": True},
        {"type": "subscription.created"},
        {"type": "refunded", "amount_refunded": 100},
    ],
)
def test_no_grant_for_other_products_gifts_subscriptions_or_partial_refund(changes):
    assert parse_event(payload(**changes), API_KEY, PRODUCT) is None


def test_missing_configuration_fails_closed():
    with pytest.raises(HTTPException) as exc:
        parse_event(payload(), "", PRODUCT)
    assert exc.value.status_code == 503


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/api/study-library/access"),
        ("GET", "/api/study-library/lessons/math/download"),
        ("POST", "/api/study-library/lessons"),
        ("GET", "/api/study-library/catalog/private"),
        ("GET", "/api/study-library/payhip"),
        ("POST", "/api/study-library/lessons/math/cover"),
    ],
)
def test_private_routes_are_not_exempted_by_prefix(method, path):
    assert not study.is_public_study_request(method, path)


def test_publish_key_only_applies_to_exact_ingest_route(monkeypatch):
    monkeypatch.setenv("STUDY_LIBRARY_PUBLISH_KEY", "x" * 48)
    for path, expected in [
        ("/api/study-library/lessons", True),
        ("/api/study-library/access", False),
    ]:
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": path,
                "headers": [(b"x-study-publish-key", b"x" * 48)],
            }
        )
        assert study.is_study_publish_request(request) is expected
    monkeypatch.setenv("STUDY_LIBRARY_PUBLISH_KEY", "short")
    assert not study.is_study_publish_request(request)


@pytest.fixture
def app_and_conn(monkeypatch):
    conn = AsyncMock()

    @asynccontextmanager
    async def acquire():
        yield conn

    class Pool:
        pass

    pool = Pool()
    pool.acquire = acquire
    monkeypatch.setattr(study, "get_pool", lambda: pool)
    app = FastAPI()
    app.include_router(study.router)
    monkeypatch.setenv("STUDY_PAYHIP_API_KEY", API_KEY)
    monkeypatch.setenv("STUDY_PAYHIP_PRODUCT_KEY", PRODUCT)
    return app, conn


@pytest.mark.asyncio
async def test_anonymous_download_denied_without_reading_db(app_and_conn):
    app, conn = app_and_conn
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        res = await client.get("/api/study-library/lessons/fractions/download")
    assert res.status_code == 401
    conn.fetchval.assert_not_awaited()


@pytest.mark.asyncio
async def test_invalid_webhook_never_touches_db(app_and_conn):
    app, conn = app_and_conn
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        res = await client.post(
            "/api/study-library/payhip", json=payload(signature="forged")
        )
        oversize = await client.post("/api/study-library/payhip", content=b"x" * 65537)
    assert res.status_code == 401
    assert oversize.status_code == 413
    conn.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_nonbuyer_download_does_not_fetch_pdf(app_and_conn):
    app, conn = app_and_conn
    app.dependency_overrides[study._verified_user] = lambda: {
        "email": "other@example.com"
    }
    conn.fetchval.return_value = False
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        res = await client.get("/api/study-library/lessons/fractions/download")
    assert res.status_code == 403
    assert conn.fetchval.await_count == 1
    assert conn.fetchval.call_args.args[1:] == ("other@example.com", PRODUCT)


@pytest.mark.asyncio
async def test_buyer_download_has_no_cache_and_safe_filename(app_and_conn):
    app, conn = app_and_conn
    app.dependency_overrides[study._verified_user] = lambda: {
        "email": "learner@example.com"
    }
    writer = PdfWriter()
    writer.add_blank_page(100, 100)
    stream = io.BytesIO()
    writer.write(stream)
    conn.fetchval.side_effect = [True, stream.getvalue()]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        res = await client.get("/api/study-library/lessons/fractions/download")
    assert res.status_code == 200
    assert res.content == stream.getvalue()
    assert res.headers["cache-control"] == "private, no-store"
    assert res.headers["content-disposition"] == 'attachment; filename="fractions.pdf"'


@pytest.mark.asyncio
async def test_email_verification_and_identity_are_loaded_from_db(app_and_conn):
    _app, conn = app_and_conn
    user = {
        "id": "12345678-1234-1234-1234-123456789012",
        "email": "learner@example.com",
    }
    conn.fetchrow.return_value = dict(user, email_verified=False)
    with pytest.raises(HTTPException) as exc:
        await study._verified_user(user)
    assert exc.value.status_code == 403
    conn.fetchrow.return_value = dict(
        user, email="changed@example.com", email_verified=True
    )
    with pytest.raises(HTTPException) as exc:
        await study._verified_user(user)
    assert exc.value.status_code == 401


def test_checkout_only_uses_matching_payhip_product(monkeypatch):
    monkeypatch.setenv("STUDY_PAYHIP_PRODUCT_KEY", PRODUCT)
    for url in (
        "https://evil.example/checkout",
        "https://payhip.com/b/wrong",
        "javascript:alert(1)",
    ):
        monkeypatch.setenv("STUDY_PAYHIP_CHECKOUT_URL", url)
        assert study._checkout_url() is None
    monkeypatch.setenv("STUDY_PAYHIP_CHECKOUT_URL", f"https://payhip.com/b/{PRODUCT}")
    assert study._checkout_url() == f"https://payhip.com/b/{PRODUCT}"
