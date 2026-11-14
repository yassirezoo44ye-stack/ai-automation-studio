"""Real PostgreSQL integration; isolated schema, no production credentials."""

import asyncio
import hashlib
import io
import os
import uuid

import asyncpg
import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from pypdf import PdfWriter
from PIL import Image

from app.routers import study_library as study
from app.core.jwt_utils import make_access_token
from app.study.payhip import PurchaseEvent, record_event
from app.study.schema import init_study_schema

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not os.getenv("STUDY_TEST_DATABASE_URL"),
        reason="Isolated STUDY_TEST_DATABASE_URL not configured",
    ),
]


@pytest_asyncio.fixture
async def db(monkeypatch):
    url = os.environ["STUDY_TEST_DATABASE_URL"]
    schema = "study_test_" + uuid.uuid4().hex
    setup = await asyncpg.connect(url)
    await setup.execute(f'CREATE SCHEMA "{schema}"')
    pool = None
    try:
        pool = await asyncpg.create_pool(
            url, min_size=1, max_size=6, server_settings={"search_path": schema}
        )
        async with pool.acquire() as conn:
            await init_study_schema(conn)
            await conn.execute(
                "CREATE TABLE users (id UUID PRIMARY KEY, email TEXT, email_verified BOOLEAN)"
            )
        monkeypatch.setattr(study, "get_pool", lambda: pool)
        monkeypatch.setenv("STUDY_PAYHIP_PRODUCT_KEY", "Study42")
        monkeypatch.setenv("STUDY_PAYHIP_API_KEY", "local-test-payhip-key")
        monkeypatch.setenv("STUDY_LIBRARY_PUBLISH_KEY", "test-only-" + "k" * 40)
        monkeypatch.delenv("STUDY_LIBRARY_ADMIN_EMAIL", raising=False)
        yield pool
    finally:
        if pool:
            await pool.close()
        await setup.execute(f'DROP SCHEMA "{schema}" CASCADE')
        await setup.close()


async def test_purchase_replay_full_refund_and_out_of_order(db):
    async with db.acquire() as conn:
        paid = PurchaseEvent("order1", "Study42", "learner@example.com", False)
        await record_event(conn, paid)
        await record_event(conn, paid)
        assert await conn.fetchval("SELECT count(*) FROM study_purchases") == 1
        assert await study._has_access({"email": paid.buyer_email})
        await record_event(
            conn, PurchaseEvent("order1", "Study42", paid.buyer_email, True)
        )
        await record_event(conn, paid)
        assert not await study._has_access({"email": paid.buyer_email})
        await record_event(
            conn, PurchaseEvent("order2", "Study42", paid.buyer_email, True)
        )
        await record_event(
            conn, PurchaseEvent("order2", "Study42", paid.buyer_email, False)
        )
        assert not await study._has_access({"email": paid.buyer_email})
        await record_event(
            conn, PurchaseEvent("order3", "Study42", paid.buyer_email, False)
        )
        assert await study._has_access({"email": paid.buyer_email})


async def test_replayed_transaction_cannot_move_access_to_another_email(db):
    async with db.acquire() as conn:
        await record_event(
            conn, PurchaseEvent("order1", "Study42", "buyer@example.com", False)
        )
        await record_event(
            conn, PurchaseEvent("order1", "Study42", "other@example.com", False)
        )
    assert not await study._has_access({"email": "other@example.com"})
    assert await study._has_access({"email": "buyer@example.com"})


def upload(index):
    writer = PdfWriter()
    writer.add_blank_page(100 + index, 100)
    pdf = io.BytesIO()
    writer.write(pdf)
    image = io.BytesIO()
    Image.new("RGB", (700, 700), "white").save(image, format="PNG")
    return {
        "pdf": ("lesson.pdf", pdf.getvalue(), "application/pdf"),
        "cover": ("cover.png", image.getvalue(), "image/png"),
    }


async def test_concurrent_publishing_is_capped_and_idempotent(db):
    app = FastAPI()
    app.include_router(study.router)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:

        async def publish(i):
            return await client.post(
                "/api/study-library/lessons",
                headers={"X-Study-Publish-Key": "test-only-" + "k" * 40},
                data={
                    "slug": f"lesson-{i}",
                    "title": f"Lesson {i}",
                    "subject": "math",
                    "description": "Reviewed summary",
                },
                files=upload(i),
            )

        results = await asyncio.gather(*(publish(i) for i in range(5)))
        assert sorted(r.status_code for r in results) == [200, 200, 200, 409, 409]
        accepted = next(i for i, r in enumerate(results) if r.status_code == 200)
        repeat = await publish(accepted)
        assert repeat.status_code == 200 and repeat.json()["created"] is False
        public = await client.get("/api/study-library/catalog")
        assert len(public.json()["lessons"]) == 3
        assert "pdf_data" not in public.text and "pdf_sha256" not in public.text
    async with db.acquire() as conn:
        assert await conn.fetchval("SELECT COUNT(*) FROM study_lessons") == 3


async def test_paid_webhook_verified_user_download_then_refund(db):
    user_id = uuid.uuid4()
    async with db.acquire() as conn:
        await conn.execute(
            "INSERT INTO users VALUES ($1,$2,true)", user_id, "buyer@example.com"
        )
    app = FastAPI()
    app.include_router(study.router)
    event = {
        "id": "flow-paid-test",
        "email": "buyer@example.com",
        "price": 1500,
        "type": "paid",
        "items": [{"product_key": "Study42"}],
        "signature": hashlib.sha256(b"local-test-payhip-key").hexdigest(),
    }
    auth = {
        "Authorization": "Bearer "
        + make_access_token(str(user_id), "buyer@example.com")
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        uploaded = await client.post(
            "/api/study-library/lessons",
            headers={"X-Study-Publish-Key": "test-only-" + "k" * 40},
            data={
                "slug": "lesson",
                "title": "Lesson",
                "subject": "math",
                "description": "Reviewed",
            },
            files=upload(1),
        )
        assert uploaded.status_code == 200
        assert (
            await client.get("/api/study-library/lessons/lesson/download", headers=auth)
        ).status_code == 403
        assert (
            await client.post("/api/study-library/payhip", json=event)
        ).status_code == 200
        downloaded = await client.get(
            "/api/study-library/lessons/lesson/download", headers=auth
        )
        assert downloaded.status_code == 200 and downloaded.content.startswith(b"%PDF-")
        assert (
            await client.get("/api/study-library/lessons/lesson/download")
        ).status_code == 401
        await client.post(
            "/api/study-library/payhip",
            json=dict(event, type="refunded", amount_refunded=1500),
        )
        await client.post("/api/study-library/payhip", json=event)
        assert (
            await client.get("/api/study-library/lessons/lesson/download", headers=auth)
        ).status_code == 403
