"""Authorization, review gates and input validation without external services."""

import uuid
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.routers import study_workflows as w
from app.tenancy.context import OrgContext


def content(**changes):
    return dict(
        voiceover="Reviewed voice script",
        tiktok="TikTok text",
        instagram="Instagram text",
        youtube="YouTube text",
        video_url="https://media.example.com/lesson.mp4",
        **changes,
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/video.mp4",
        "https://localhost/a",
        "https://127.0.0.1/a",
        "https://[::1]/a",
        "https://10.0.0.1/a",
        "https://example.local/a",
        "https://user:pass@example.com/a",
        "https://example.com:444/a",
        "https://example.com/a#fragment",
    ],
)
def test_nonpublic_or_credentialed_media_url_rejected(url):
    data = content()
    data["video_url"] = url
    with pytest.raises(ValidationError):
        w.Content(**data)


def test_drafts_can_be_saved_before_video_is_ready_but_not_extra_metadata():
    data = content()
    data["video_url"] = ""
    assert w.Content(**data).video_url == ""
    with pytest.raises(ValidationError):
        w.Content(**data, publishing=True)
    with pytest.raises(ValidationError):
        w.Content(**{**data, "voiceover": " "})


@pytest.mark.asyncio
async def test_admin_and_workspace_editor_both_required(monkeypatch):
    uid = str(uuid.uuid4())
    ctx = OrgContext(str(uuid.uuid4()), uid, "admin@example.com", "owner")
    monkeypatch.setenv("STUDY_LIBRARY_ADMIN_EMAIL", "admin@example.com")
    user = {"id": uid, "email": "admin@example.com"}
    assert await w.editor(ctx, user) == ctx
    for invalid, person in [
        (OrgContext(ctx.org_id, uid, ctx.user_email, "viewer"), user),
        (ctx, {"id": uid, "email": "buyer@example.com"}),
        (ctx, {"id": str(uuid.uuid4()), "email": "admin@example.com"}),
    ]:
        with pytest.raises(HTTPException) as err:
            await w.editor(invalid, person)
        assert err.value.status_code == 403


@pytest.mark.asyncio
async def test_revision_and_source_change_block_review_and_handoff():
    conn = AsyncMock()
    ctx = OrgContext(str(uuid.uuid4()), str(uuid.uuid4()), "x@example.com", "owner")
    conn.fetchrow.return_value = {
        "revision": 2,
        "source_sha256": "a" * 64,
        "current_sha": "a" * 64,
    }
    with pytest.raises(HTTPException) as err:
        await w.locked(conn, str(uuid.uuid4()), ctx, 1)
    assert err.value.status_code == 409
    conn.fetchrow.return_value = {
        "revision": 2,
        "source_sha256": "a" * 64,
        "current_sha": "b" * 64,
    }
    with pytest.raises(HTTPException) as err:
        await w.locked(conn, str(uuid.uuid4()), ctx, 2)
    assert err.value.status_code == 409
    conn.fetchrow.return_value = None
    with pytest.raises(HTTPException) as err:
        await w.locked(conn, str(uuid.uuid4()), ctx, 2)
    assert err.value.status_code == 404
    assert conn.fetchrow.call_args.args[2] == ctx.org_id


@pytest.mark.asyncio
async def test_api_rejects_anonymous_and_verified_non_admin(monkeypatch):
    import httpx
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(w.router)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        assert (await client.get("/api/study-library/workflows")).status_code == 401
        uid = str(uuid.uuid4())
        app.dependency_overrides[w.org_context] = lambda: OrgContext(
            str(uuid.uuid4()), uid, "buyer@example.com", "owner"
        )
        app.dependency_overrides[w._verified_user] = lambda: {
            "id": uid,
            "email": "buyer@example.com",
        }
        monkeypatch.setenv("STUDY_LIBRARY_ADMIN_EMAIL", "admin@example.com")
        assert (await client.get("/api/study-library/workflows")).status_code == 403
