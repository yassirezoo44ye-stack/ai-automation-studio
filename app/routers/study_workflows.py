"""Connect reviewed lessons to the existing social draft queue, not to publishing."""

from __future__ import annotations

import ipaddress
import json
import uuid
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.db import get_pool
from app.integrations.social.registry import get_social_registry
from app.routers.study_library import _is_admin, _verified_user
from app.tenancy.context import OrgContext, org_context

router = APIRouter(
    prefix="/api/study-library/workflows", tags=["study-content-workflow"]
)
PLATFORMS = ("tiktok", "instagram", "youtube")


async def editor(
    ctx: Annotated[OrgContext, Depends(org_context)],
    user: Annotated[dict, Depends(_verified_user)],
):
    if (
        not _is_admin(user)
        or ctx.role not in ("owner", "admin")
        or str(user["id"]) != ctx.user_id
    ):
        raise HTTPException(
            403, "Library administrator and organization editor access required"
        )
    return ctx


EditorContext = Annotated[OrgContext, Depends(editor)]


class Content(BaseModel):
    model_config = ConfigDict(extra="forbid")
    voiceover: str = Field(min_length=1, max_length=12000)
    tiktok: str = Field(min_length=1, max_length=2000)
    instagram: str = Field(min_length=1, max_length=2000)
    youtube: str = Field(min_length=1, max_length=2000)
    video_url: str = Field(default="", max_length=2000)

    @field_validator("voiceover", "tiktok", "instagram", "youtube")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Text cannot be blank")
        return value.strip()

    @field_validator("video_url")
    @classmethod
    def video_https(cls, value):
        value = value.strip()
        if not value:
            return value
        try:
            url = urlsplit(value)
            host = url.hostname or ""
            if (
                url.scheme != "https"
                or not host
                or url.username
                or url.password
                or url.port not in (None, 443)
                or url.fragment
            ):
                raise ValueError
            if (
                host.lower() == "localhost"
                or "." not in host
                or host.lower().endswith((".local", ".localhost", ".internal"))
            ):
                raise ValueError
            try:
                address = ipaddress.ip_address(host)
            except ValueError:
                pass
            else:
                if not address.is_global:
                    raise ValueError
        except ValueError:
            raise ValueError("Use an HTTPS video URL on a public media host") from None
        return value


class Create(Content):
    lesson_slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=80)


class Update(Content):
    revision: int = Field(ge=1)


class Revision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1)


def uid(value):
    try:
        return uuid.UUID(value)
    except ValueError:
        raise HTTPException(404, "Workflow not found") from None


def output(row):
    data = dict(row)
    for key in ("id", "organization_id", "created_by", "reviewed_by"):
        if key in data and data[key] is not None:
            data[key] = str(data[key])
    for key in ("created_at", "updated_at", "reviewed_at"):
        if key in data and data[key] is not None:
            data[key] = data[key].isoformat()
    if isinstance(data.get("content"), str):
        data["content"] = json.loads(data["content"])
    return data


async def locked(conn, workflow_id, ctx, revision):
    row = await conn.fetchrow(
        """SELECT w.*, l.title, l.pdf_sha256 AS current_sha
        FROM study_content_workflows w JOIN study_lessons l ON l.slug=w.lesson_slug
        WHERE w.id=$1 AND w.organization_id=$2::uuid FOR UPDATE OF w""",
        uid(workflow_id),
        ctx.org_id,
    )
    if not row:
        raise HTTPException(404, "Workflow not found")
    if row["revision"] != revision:
        raise HTTPException(409, "Content changed; reload before continuing")
    if row["source_sha256"] != row["current_sha"]:
        raise HTTPException(
            409, "Lesson source changed; create and review a new workflow"
        )
    return row


@router.get("")
async def listing(ctx: EditorContext):
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            """SELECT w.*, l.title FROM study_content_workflows w
            JOIN study_lessons l ON l.slug=w.lesson_slug WHERE organization_id=$1::uuid
            ORDER BY w.updated_at DESC LIMIT 60""",
            ctx.org_id,
        )
    return {"workflows": [output(r) for r in rows]}


@router.get("/connections")
async def connections(ctx: EditorContext):
    async with get_pool().acquire() as conn:
        accounts = await conn.fetch(
            """SELECT platform, platform_username FROM social_platform_accounts
            WHERE organization_id=$1::uuid AND is_active=true ORDER BY connected_at""",
            ctx.org_id,
        )
    registry = get_social_registry()
    return {
        "platforms": [
            {
                "platform": p,
                "implemented": registry.get(p) is not None,
                "configured": bool(registry.get(p) and registry.get(p).is_available()),
                "accounts": [
                    r["platform_username"] for r in accounts if r["platform"] == p
                ],
            }
            for p in PLATFORMS
        ],
        "publishing_triggered": False,
    }


@router.post("", status_code=201)
async def create(req: Create, ctx: EditorContext):
    content = req.model_dump(exclude={"lesson_slug"})
    async with get_pool().acquire() as conn, conn.transaction():
        lesson = await conn.fetchrow(
            "SELECT title, pdf_sha256 FROM study_lessons WHERE slug=$1",
            req.lesson_slug,
        )
        if not lesson:
            raise HTTPException(404, "Lesson not found; add it to the library first")
        row = await conn.fetchrow(
            """INSERT INTO study_content_workflows
                (organization_id,lesson_slug,source_sha256,created_by,content)
                VALUES ($1::uuid,$2,$3,$4::uuid,$5::jsonb) RETURNING *""",
            ctx.org_id,
            req.lesson_slug,
            lesson["pdf_sha256"],
            ctx.user_id,
            json.dumps(content),
        )
    return output(dict(row, title=lesson["title"]))


@router.put("/{workflow_id}")
async def update(workflow_id: str, req: Update, ctx: EditorContext):
    async with get_pool().acquire() as conn, conn.transaction():
        row = await locked(conn, workflow_id, ctx, req.revision)
        if row["state"] == "handed_off":
            raise HTTPException(
                409, "Already handed off; create a new workflow for a new edition"
            )
        result = await conn.fetchrow(
            """UPDATE study_content_workflows SET content=$3::jsonb,
            revision=revision+1, state='draft', reviewed_by=NULL, reviewed_at=NULL, updated_at=NOW()
            WHERE id=$1 AND organization_id=$2::uuid RETURNING *""",
            uid(workflow_id),
            ctx.org_id,
            json.dumps(req.model_dump(exclude={"revision"})),
        )
    return output(dict(result, title=row["title"]))


@router.post("/{workflow_id}/review")
async def review(workflow_id: str, req: Revision, ctx: EditorContext):
    async with get_pool().acquire() as conn, conn.transaction():
        row = await locked(conn, workflow_id, ctx, req.revision)
        if row["state"] == "handed_off":
            raise HTTPException(409, "Already handed off")
        data = Content.model_validate(
            json.loads(row["content"])
            if isinstance(row["content"], str)
            else row["content"]
        )
        if not data.video_url:
            raise HTTPException(
                422, "Add the final video URL before approving this revision"
            )
        result = await conn.fetchrow(
            """UPDATE study_content_workflows SET state='reviewed',
                reviewed_by=$3::uuid, reviewed_at=NOW(), updated_at=NOW()
                WHERE id=$1 AND organization_id=$2::uuid RETURNING *""",
            uid(workflow_id),
            ctx.org_id,
            ctx.user_id,
        )
    return output(dict(result, title=row["title"]))


@router.post("/{workflow_id}/handoff")
async def handoff(workflow_id: str, req: Revision, ctx: EditorContext):
    async with get_pool().acquire() as conn, conn.transaction():
        row = await locked(conn, workflow_id, ctx, req.revision)
        if row["state"] not in ("reviewed", "handed_off"):
            raise HTTPException(
                409, "Approve this revision before creating social drafts"
            )
        if row["state"] == "handed_off":
            return {"state": "handed_off", "publishing_triggered": False}
        data = Content.model_validate(
            json.loads(row["content"])
            if isinstance(row["content"], str)
            else row["content"]
        )
        if not data.video_url:
            raise HTTPException(409, "Final video URL missing")
        for platform in PLATFORMS:
            exists = await conn.fetchval(
                "SELECT post_id FROM study_content_workflow_posts WHERE workflow_id=$1 AND platform=$2",
                uid(workflow_id),
                platform,
            )
            if exists:
                continue
            post_id = await conn.fetchval(
                """INSERT INTO social_posts
                (organization_id,created_by_user_id,title,caption,video_url,target_platforms,status,metadata)
                VALUES ($1::uuid,$2::uuid,$3,$4,$5,$6::text[],'draft',$7::jsonb) RETURNING id""",
                ctx.org_id,
                ctx.user_id,
                row["title"],
                getattr(data, platform),
                data.video_url,
                [platform],
                json.dumps(
                    {
                        "study_workflow_id": workflow_id,
                        "study_lesson_slug": row["lesson_slug"],
                        "reviewed_revision": req.revision,
                    }
                ),
            )
            await conn.execute(
                "INSERT INTO study_content_workflow_posts (workflow_id,platform,post_id) VALUES ($1,$2,$3)",
                uid(workflow_id),
                platform,
                post_id,
            )
        await conn.execute(
            "UPDATE study_content_workflows SET state='handed_off',updated_at=NOW() WHERE id=$1 AND organization_id=$2::uuid",
            uid(workflow_id),
            ctx.org_id,
        )
    return {"state": "handed_off", "publishing_triggered": False}


@router.get("/{workflow_id}/posts")
async def posts(workflow_id: str, ctx: EditorContext):
    async with get_pool().acquire() as conn:
        exists = await conn.fetchval(
            "SELECT id FROM study_content_workflows WHERE id=$1 AND organization_id=$2::uuid",
            uid(workflow_id),
            ctx.org_id,
        )
        if not exists:
            raise HTTPException(404, "Workflow not found")
        rows = await conn.fetch(
            """SELECT link.platform,p.id,p.status,p.updated_at FROM study_content_workflow_posts link
            JOIN social_posts p ON p.id=link.post_id WHERE link.workflow_id=$1 AND p.organization_id=$2::uuid ORDER BY link.platform""",
            uid(workflow_id),
            ctx.org_id,
        )
    return {
        "posts": [
            {
                "id": str(r["id"]),
                "platform": r["platform"],
                "status": r["status"],
                "updated_at": r["updated_at"].isoformat(),
            }
            for r in rows
        ]
    }
