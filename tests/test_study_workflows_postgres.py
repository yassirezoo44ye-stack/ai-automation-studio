"""Actual transactional integration in an isolated schema (CI PostgreSQL)."""

import asyncio
import os
import uuid

import asyncpg
import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from app.routers import study_workflows as w
from app.study.schema import init_study_schema
from app.study.workflows import init_study_workflow_schema
from app.tenancy.context import OrgContext

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not os.getenv("STUDY_TEST_DATABASE_URL"),
        reason="Isolated PostgreSQL not configured",
    ),
]


@pytest_asyncio.fixture
async def db(monkeypatch):
    url = os.environ["STUDY_TEST_DATABASE_URL"]
    schema = "workflow_test_" + uuid.uuid4().hex
    setup = await asyncpg.connect(url)
    await setup.execute(f'CREATE SCHEMA "{schema}"')
    pool = None
    try:
        pool = await asyncpg.create_pool(
            url, min_size=1, max_size=5, server_settings={"search_path": schema}
        )
        org, user, other = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        async with pool.acquire() as c:
            await c.execute(
                "CREATE TABLE organizations(id UUID PRIMARY KEY); CREATE TABLE users(id UUID PRIMARY KEY)"
            )
            await init_study_schema(c)
            await c.execute("""CREATE TABLE social_posts(id UUID PRIMARY KEY DEFAULT gen_random_uuid(), organization_id UUID NOT NULL,
                created_by_user_id UUID,title TEXT,caption TEXT,video_url TEXT,target_platforms TEXT[],status TEXT,metadata JSONB,updated_at TIMESTAMPTZ DEFAULT NOW());
                CREATE TABLE social_platform_accounts(platform TEXT,platform_username TEXT,organization_id UUID,is_active BOOLEAN,connected_at TIMESTAMPTZ)""")
            await init_study_workflow_schema(c)
            await init_study_workflow_schema(c)
            await c.execute("INSERT INTO organizations VALUES($1),($2)", org, other)
            await c.execute("INSERT INTO users VALUES($1)", user)
            await c.execute(
                "INSERT INTO study_lessons(slug,title,subject,description,pages,pdf_data,pdf_sha256,cover_data) VALUES('lesson','Lesson','math','Description',2,$1,$2,$3)",
                b"private-pdf",
                "a" * 64,
                b"cover",
            )
        monkeypatch.setattr(w, "get_pool", lambda: pool)
        app = FastAPI()
        app.include_router(w.router)
        context = {"org": str(org)}
        app.dependency_overrides[w.editor] = lambda: OrgContext(
            context["org"], str(user), "admin@example.com", "owner"
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            yield client, pool, context, str(other)
    finally:
        if pool:
            await pool.close()
        await setup.execute(f'DROP SCHEMA "{schema}" CASCADE')
        await setup.close()


def body(**changes):
    return dict(
        lesson_slug="lesson",
        voiceover="Full reviewed script",
        tiktok="TikTok caption",
        instagram="Instagram caption",
        youtube="YouTube caption",
        video_url="",
        **changes,
    )


async def test_review_reset_atomic_handoff_replay_and_tenant_isolation(db):
    client, pool, context, other = db
    result = await client.post("/api/study-library/workflows", json=body())
    assert result.status_code == 201
    item = result.json()
    url = "/api/study-library/workflows/" + item["id"]
    assert (await client.post(url + "/review", json={"revision": 1})).status_code == 422
    data = body()
    data.pop("lesson_slug")
    data.update(revision=1, video_url="https://media.example.com/final.mp4")
    assert (await client.put(url, json=data)).json()["revision"] == 2
    assert (await client.post(url + "/review", json={"revision": 2})).json()[
        "state"
    ] == "reviewed"
    data.update(revision=2, tiktok="Edited caption")
    updated = (await client.put(url, json=data)).json()
    assert (
        updated["revision"] == 3
        and updated["state"] == "draft"
        and updated["reviewed_at"] is None
    )
    assert (
        await client.post(url + "/handoff", json={"revision": 3})
    ).status_code == 409
    assert (await client.post(url + "/review", json={"revision": 3})).status_code == 200
    first, second = await asyncio.gather(
        client.post(url + "/handoff", json={"revision": 3}),
        client.post(url + "/handoff", json={"revision": 3}),
    )
    assert first.status_code == second.status_code == 200
    assert first.json()["publishing_triggered"] is False
    async with pool.acquire() as c:
        assert await c.fetchval("SELECT count(*) FROM social_posts") == 3
        assert (
            await c.fetchval("SELECT count(*) FROM social_posts WHERE status='draft'")
            == 3
        )
        assert (
            await c.fetchval(
                "SELECT caption FROM social_posts WHERE target_platforms=ARRAY['tiktok']"
            )
            == "Edited caption"
        )
    posts = (await client.get(url + "/posts")).json()["posts"]
    assert len(posts) == 3
    data["revision"] = 3
    assert (await client.put(url, json=data)).status_code == 409
    context["org"] = other
    assert (await client.get("/api/study-library/workflows")).json()["workflows"] == []
    assert (await client.get(url + "/posts")).status_code == 404
    assert (await client.post(url + "/review", json={"revision": 3})).status_code == 404
    assert (
        await client.post(url + "/handoff", json={"revision": 3})
    ).status_code == 404


async def test_stale_revision_and_changed_lesson_cannot_be_approved(db):
    client, pool, _context, _other = db
    data = body()
    data["video_url"] = "https://media.example.com/final.mp4"
    result = await client.post("/api/study-library/workflows", json=data)
    url = "/api/study-library/workflows/" + result.json()["id"]
    assert (await client.post(url + "/review", json={"revision": 9})).status_code == 409
    async with pool.acquire() as c:
        await c.execute(
            "UPDATE study_lessons SET pdf_sha256=$1 WHERE slug='lesson'", "b" * 64
        )
    assert (await client.post(url + "/review", json={"revision": 1})).status_code == 409
    assert (
        await client.post(url + "/handoff", json={"revision": 1})
    ).status_code == 409
