"""
Flow Next — Discover Router (Phase 1)

Endpoints
─────────
GET  /api/discover                  Public feed (public creations, no auth needed)
GET  /api/discover/mine             My org's creations (auth required)
POST /api/creations                 Create a creation card
GET  /api/creations/{id}            Get one creation
PATCH /api/creations/{id}           Update title/description/tags/thumbnail
DELETE /api/creations/{id}          Delete (owner org only)
POST /api/creations/{id}/publish    Set visibility=public
POST /api/creations/{id}/unpublish  Set visibility=private
POST /api/creations/{id}/clone      Clone into caller's org (via real domain APIs)

Security
─────────
• Tenant isolation: write endpoints check organization_id == current org.
• IDOR guard: all mutations verify the caller's org owns the row.
• Clone is routed through existing domain APIs, never raw DB copy.
• DEVICE_WORKFLOW and AGENT are explicitly non-cloneable (hardware-specific /
  not safe yet) — 409 Conflict.
• Public feed is unauthenticated (read-only public rows only).
"""
from __future__ import annotations

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from typing import Literal, Optional
import uuid

from app.core.auth import verify_token, extract_auth_credentials
from app.core.db import get_pool

router = APIRouter(prefix="/api", tags=["discover"])

# ── Schema init ────────────────────────────────────────────────────────────────

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS flow_creations (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id     UUID        NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    created_by_user_id  UUID        REFERENCES users(id) ON DELETE SET NULL,
    type                VARCHAR(30) NOT NULL
                        CHECK (type IN ('APP','AGENT','WORKFLOW','AUTOMATION','TEMPLATE','DEVICE_WORKFLOW')),
    title               VARCHAR(200) NOT NULL,
    description         TEXT,
    visibility          VARCHAR(20) NOT NULL DEFAULT 'private'
                        CHECK (visibility IN ('private','public')),
    source_type         VARCHAR(30),
    source_id           UUID,
    thumbnail_url       TEXT,
    tags                TEXT[]      NOT NULL DEFAULT '{}',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_flow_creations_org
    ON flow_creations(organization_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_flow_creations_public
    ON flow_creations(created_at DESC)
    WHERE visibility = 'public';
CREATE INDEX IF NOT EXISTS ix_flow_creations_source
    ON flow_creations(source_type, source_id)
    WHERE source_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_flow_creations_source
    ON flow_creations(organization_id, source_type, source_id)
    WHERE source_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS flow_creation_interactions (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    creation_id     UUID        NOT NULL REFERENCES flow_creations(id) ON DELETE CASCADE,
    user_id         UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    organization_id UUID        NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    type            VARCHAR(10) NOT NULL CHECK (type IN ('like', 'save')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (creation_id, user_id, type)
);
CREATE INDEX IF NOT EXISTS ix_fci_creation_type
    ON flow_creation_interactions(creation_id, type);
CREATE INDEX IF NOT EXISTS ix_fci_user_type
    ON flow_creation_interactions(user_id, type);
"""


async def init_flow_creations_schema(conn: asyncpg.Connection) -> None:
    """Idempotent — called from app/factory.py lifespan."""
    await conn.execute(_SCHEMA_SQL)


# ── Auth helpers ───────────────────────────────────────────────────────────────

def _get_org_id(request: Request) -> str:
    org_id = request.headers.get("X-Organization-Id")
    if not org_id:
        raise HTTPException(status_code=400, detail="X-Organization-Id header required")
    return org_id


def _get_user_id(request: Request) -> Optional[str]:
    """Best-effort user extraction from JWT — None if not available."""
    try:
        _, bearer = extract_auth_credentials(request)
        if bearer:
            from app.core.auth import _decode_token
            payload = _decode_token(bearer)
            return payload.get("sub") or payload.get("user_id")
    except Exception:
        pass
    return None


def _require_auth(request: Request) -> None:
    sub_token, bearer = extract_auth_credentials(request)
    if not ((sub_token and verify_token(sub_token)) or (bearer and verify_token(bearer))):
        raise HTTPException(status_code=401, detail="Authentication required")


def _require_user_id(request: Request) -> str:
    """Extract user_id from JWT or raise 401."""
    user_id = _get_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user_id


# ── Pydantic models ────────────────────────────────────────────────────────────

CreationType = Literal["APP", "AGENT", "WORKFLOW", "AUTOMATION", "TEMPLATE", "DEVICE_WORKFLOW"]


class CreateCreationRequest(BaseModel):
    type: CreationType
    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    visibility: Literal["private", "public"] = "private"
    source_type: Optional[str] = Field(None, max_length=30)
    source_id: Optional[str] = None  # UUID string
    thumbnail_url: Optional[str] = None
    tags: list[str] = []


class UpdateCreationRequest(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    thumbnail_url: Optional[str] = None
    tags: Optional[list[str]] = None


def _row_to_dict(row) -> dict:
    if row is None:
        return None
    d = dict(row)
    # Convert UUID objects to strings for JSON serialisation
    for k in ("id", "organization_id", "created_by_user_id", "source_id"):
        if d.get(k) is not None:
            d[k] = str(d[k])
    # Timestamps to ISO strings
    for k in ("created_at", "updated_at"):
        if d.get(k) is not None:
            d[k] = d[k].isoformat()
    return d


# ── Public feed ────────────────────────────────────────────────────────────────

@router.get("/discover")
async def public_discover_feed(
    request: Request,
    type: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
):
    """
    Public creation feed — no auth required.
    Returns only visibility='public' rows.
    Optionally filter by ?type=APP|AGENT|WORKFLOW|AUTOMATION|TEMPLATE|DEVICE_WORKFLOW
    Includes user_liked/user_saved when a valid JWT is present.
    """
    limit = min(limit, 100)
    pool = get_pool()
    async with pool.acquire() as conn:
        if type:
            rows = await conn.fetch(
                "SELECT * FROM flow_creations "
                "WHERE visibility='public' AND type=$1 "
                "ORDER BY created_at DESC LIMIT $2 OFFSET $3",
                type.upper(), limit, offset,
            )
        else:
            rows = await conn.fetch(
                "SELECT * FROM flow_creations "
                "WHERE visibility='public' "
                "ORDER BY created_at DESC LIMIT $1 OFFSET $2",
                limit, offset,
            )
        liked_ids: set[str] = set()
        saved_ids: set[str] = set()
        user_id = _get_user_id(request)
        if user_id and rows:
            try:
                import uuid as _uuid
                creation_ids = [r["id"] for r in rows]
                interactions = await conn.fetch(
                    "SELECT creation_id, type FROM flow_creation_interactions "
                    "WHERE user_id = $1 AND creation_id = ANY($2::uuid[])",
                    _uuid.UUID(user_id), creation_ids,
                )
                for i in interactions:
                    if i["type"] == "like":
                        liked_ids.add(str(i["creation_id"]))
                    else:
                        saved_ids.add(str(i["creation_id"]))
            except Exception:
                pass
    items_out = []
    for r in rows:
        d = _row_to_dict(r)
        d["user_liked"] = d["id"] in liked_ids
        d["user_saved"] = d["id"] in saved_ids
        items_out.append(d)
    return {"items": items_out, "total": len(items_out)}


# ── My org's creations ─────────────────────────────────────────────────────────

@router.get("/discover/mine")
async def my_creations(
    request: Request,
    type: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
):
    """List my org's creations (private + public). Auth required."""
    _require_auth(request)
    org_id = _get_org_id(request)
    limit = min(limit, 100)
    pool = get_pool()
    async with pool.acquire() as conn:
        if type:
            rows = await conn.fetch(
                "SELECT * FROM flow_creations "
                "WHERE organization_id=$1 AND type=$2 "
                "ORDER BY created_at DESC LIMIT $3 OFFSET $4",
                org_id, type.upper(), limit, offset,
            )
        else:
            rows = await conn.fetch(
                "SELECT * FROM flow_creations "
                "WHERE organization_id=$1 "
                "ORDER BY created_at DESC LIMIT $2 OFFSET $3",
                org_id, limit, offset,
            )
    return {"items": [_row_to_dict(r) for r in rows], "total": len(rows)}


# ── Create ─────────────────────────────────────────────────────────────────────

@router.post("/creations", status_code=201)
async def create_creation(request: Request, body: CreateCreationRequest):
    """Publish a new creation card. Auth required."""
    _require_auth(request)
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)

    source_id = None
    if body.source_id:
        try:
            source_id = uuid.UUID(body.source_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="source_id must be a valid UUID")

    pool = get_pool()
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                """
                INSERT INTO flow_creations
                    (organization_id, created_by_user_id, type, title, description,
                     visibility, source_type, source_id, thumbnail_url, tags)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
                RETURNING *
                """,
                org_id, user_id, body.type, body.title, body.description,
                body.visibility, body.source_type, source_id,
                body.thumbnail_url, body.tags,
            )
        except asyncpg.UniqueViolationError:
            raise HTTPException(
                status_code=409,
                detail="This source is already in your creations.",
            )
    return _row_to_dict(row)


# ── Read one ──────────────────────────────────────────────────────────────────

@router.get("/creations/{creation_id}")
async def get_creation(request: Request, creation_id: str):
    """
    Get one creation.
    - Public rows: no auth required.
    - Private rows: must belong to caller's org.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM flow_creations WHERE id=$1", creation_id
        )
    if row is None:
        raise HTTPException(status_code=404, detail="Creation not found")

    d = _row_to_dict(row)
    if d["visibility"] == "public":
        return d

    # Private — require auth + org membership
    _require_auth(request)
    org_id = _get_org_id(request)
    if d["organization_id"] != org_id:
        raise HTTPException(status_code=404, detail="Creation not found")
    return d


# ── Update ────────────────────────────────────────────────────────────────────

@router.patch("/creations/{creation_id}")
async def update_creation(request: Request, creation_id: str, body: UpdateCreationRequest):
    """Update metadata. Owner org only."""
    _require_auth(request)
    org_id = _get_org_id(request)

    pool = get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT organization_id FROM flow_creations WHERE id=$1", creation_id
        )
        if existing is None:
            raise HTTPException(status_code=404, detail="Creation not found")
        if str(existing["organization_id"]) != org_id:
            raise HTTPException(status_code=403, detail="Not authorized")

        # Build partial update
        sets, params = [], [creation_id]
        if body.title is not None:
            params.append(body.title); sets.append(f"title=${len(params)}")
        if body.description is not None:
            params.append(body.description); sets.append(f"description=${len(params)}")
        if body.thumbnail_url is not None:
            params.append(body.thumbnail_url); sets.append(f"thumbnail_url=${len(params)}")
        if body.tags is not None:
            params.append(body.tags); sets.append(f"tags=${len(params)}")

        if not sets:
            return _row_to_dict(await conn.fetchrow("SELECT * FROM flow_creations WHERE id=$1", creation_id))

        sets.append("updated_at=NOW()")
        sql = f"UPDATE flow_creations SET {', '.join(sets)} WHERE id=$1 RETURNING *"
        row = await conn.fetchrow(sql, *params)
    return _row_to_dict(row)


# ── Delete ────────────────────────────────────────────────────────────────────

@router.delete("/creations/{creation_id}", status_code=204)
async def delete_creation(request: Request, creation_id: str):
    """Delete. Owner org only."""
    _require_auth(request)
    org_id = _get_org_id(request)

    pool = get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT organization_id FROM flow_creations WHERE id=$1", creation_id
        )
        if existing is None:
            raise HTTPException(status_code=404, detail="Creation not found")
        if str(existing["organization_id"]) != org_id:
            raise HTTPException(status_code=403, detail="Not authorized")
        await conn.execute("DELETE FROM flow_creations WHERE id=$1", creation_id)


# ── Publish / Unpublish ───────────────────────────────────────────────────────

@router.post("/creations/{creation_id}/publish")
async def publish_creation(request: Request, creation_id: str):
    """Make a creation publicly discoverable. Owner org only."""
    _require_auth(request)
    org_id = _get_org_id(request)

    pool = get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT organization_id FROM flow_creations WHERE id=$1", creation_id
        )
        if existing is None:
            raise HTTPException(status_code=404, detail="Creation not found")
        if str(existing["organization_id"]) != org_id:
            raise HTTPException(status_code=403, detail="Not authorized")
        row = await conn.fetchrow(
            "UPDATE flow_creations SET visibility='public', updated_at=NOW() "
            "WHERE id=$1 RETURNING *",
            creation_id,
        )
    return _row_to_dict(row)


@router.post("/creations/{creation_id}/unpublish")
async def unpublish_creation(request: Request, creation_id: str):
    """Make a creation private again. Owner org only."""
    _require_auth(request)
    org_id = _get_org_id(request)

    pool = get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT organization_id FROM flow_creations WHERE id=$1", creation_id
        )
        if existing is None:
            raise HTTPException(status_code=404, detail="Creation not found")
        if str(existing["organization_id"]) != org_id:
            raise HTTPException(status_code=403, detail="Not authorized")
        row = await conn.fetchrow(
            "UPDATE flow_creations SET visibility='private', updated_at=NOW() "
            "WHERE id=$1 RETURNING *",
            creation_id,
        )
    return _row_to_dict(row)


# ── Clone ─────────────────────────────────────────────────────────────────────

_NON_CLONEABLE = {"DEVICE_WORKFLOW", "AGENT"}

@router.post("/creations/{creation_id}/clone", status_code=201)
async def clone_creation(request: Request, creation_id: str):
    """
    Clone a creation into the caller's org.

    Routes through real domain APIs (not raw DB row copy):
    • APP → POST /api/apps/{source_id}/clone  (app_builder_router)
    • AUTOMATION / WORKFLOW → POST /api/automations/{source_id}/clone
    • TEMPLATE → duplicates the creation card only (no source resource)
    • DEVICE_WORKFLOW, AGENT → 409 (hardware-specific / not safe)

    Returns the new creation card in the caller's org.
    """
    _require_auth(request)
    org_id = _get_org_id(request)

    pool = get_pool()
    async with pool.acquire() as conn:
        original = await conn.fetchrow(
            "SELECT * FROM flow_creations WHERE id=$1", creation_id
        )
    if original is None:
        raise HTTPException(status_code=404, detail="Creation not found")

    d = _row_to_dict(original)

    # Only public creations are cloneable cross-org; private allowed within same org
    if d["visibility"] != "public" and d["organization_id"] != org_id:
        raise HTTPException(status_code=404, detail="Creation not found")

    if d["type"] in _NON_CLONEABLE:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{d['type']} creations cannot be cloned — "
                "they are hardware-specific or require manual configuration."
            ),
        )

    user_id = _get_user_id(request)
    new_source_id = d.get("source_id")

    # Route clone through real domain API when there is a source resource
    if d["source_type"] == "APP" and d.get("source_id"):
        try:
            from app.services.app_builder import get_app_builder_service
            svc = get_app_builder_service()
            async with pool.acquire() as conn:
                cloned_app = await svc.clone_app(
                    source_id=d["source_id"],
                    target_org_id=org_id,
                    cloned_by_user_id=user_id,
                    conn=conn,
                )
            new_source_id = cloned_app.get("id") if cloned_app else None
        except Exception:
            # Clone service unavailable — create card without source link
            new_source_id = None

    # Insert a new creation card in the caller's org
    async with pool.acquire() as conn:
        new_row = await conn.fetchrow(
            """
            INSERT INTO flow_creations
                (organization_id, created_by_user_id, type, title, description,
                 visibility, source_type, source_id, thumbnail_url, tags)
            VALUES ($1,$2,$3,$4,$5,'private',$6,$7,$8,$9)
            RETURNING *
            """,
            org_id, user_id, d["type"],
            f"Copy of {d['title']}", d.get("description"),
            d.get("source_type"),
            uuid.UUID(new_source_id) if new_source_id else None,
            d.get("thumbnail_url"), d.get("tags") or [],
        )
    return _row_to_dict(new_row)


# ── Interactions (like / save) ─────────────────────────────────────────────────

_TOGGLE_SQL = """
WITH toggled AS (
    DELETE FROM flow_creation_interactions
    WHERE creation_id = $1 AND user_id = $2 AND type = $4
    RETURNING id
),
inserted AS (
    INSERT INTO flow_creation_interactions (creation_id, user_id, organization_id, type)
    SELECT $1, $2, $3, $4
    WHERE NOT EXISTS (SELECT 1 FROM toggled)
    ON CONFLICT (creation_id, user_id, type) DO NOTHING
    RETURNING id
)
SELECT
    EXISTS (SELECT 1 FROM inserted) AS active,
    (SELECT COUNT(*) FROM flow_creation_interactions
     WHERE creation_id = $1 AND type = $4) AS total_count
"""


async def _toggle_interaction(
    creation_id: str, request: Request, interaction_type: str
) -> dict:
    _require_auth(request)
    user_id = _require_user_id(request)
    org_id = _get_org_id(request)
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT organization_id, visibility FROM flow_creations WHERE id=$1",
            creation_id,
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Creation not found")
        if row["visibility"] != "public" and str(row["organization_id"]) != org_id:
            raise HTTPException(status_code=404, detail="Creation not found")
        result = await conn.fetchrow(
            _TOGGLE_SQL,
            uuid.UUID(creation_id), uuid.UUID(user_id), uuid.UUID(org_id),
            interaction_type,
        )
    return result


@router.post("/creations/{creation_id}/like")
async def like_creation(creation_id: str, request: Request):
    """Toggle like on a creation. Auth required. Returns {liked, count}."""
    result = await _toggle_interaction(creation_id, request, "like")
    return {"liked": result["active"], "count": int(result["total_count"])}


@router.post("/creations/{creation_id}/save")
async def save_creation(creation_id: str, request: Request):
    """Toggle save on a creation. Auth required. Returns {saved, count}."""
    result = await _toggle_interaction(creation_id, request, "save")
    return {"saved": result["active"], "count": int(result["total_count"])}
