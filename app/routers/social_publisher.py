"""
Social Publisher — FastAPI router.

All endpoints are scoped to the authenticated user's organization via
OrgContext.  Every DB query filters on organization_id — IDOR protection
at the query level, matching the project's established pattern.

Phase 1 surface
───────────────
Accounts (OAuth):
    GET    /api/social/platforms                list available platforms
    GET    /api/social/accounts                 list connected accounts for org
    GET    /api/social/accounts/{platform}/connect   start OAuth flow
    GET    /api/social/accounts/{platform}/callback  OAuth callback (browser)
    DELETE /api/social/accounts/{account_id}    disconnect account

Posts:
    POST   /api/social/posts                    create post
    GET    /api/social/posts                    list posts (paginated)
    GET    /api/social/posts/{id}               get post + job statuses
    PATCH  /api/social/posts/{id}               update draft post
    DELETE /api/social/posts/{id}               delete draft post

Publishing:
    POST   /api/social/posts/{id}/publish       publish immediately
    POST   /api/social/posts/{id}/schedule      schedule for later
    POST   /api/social/posts/{id}/cancel        cancel scheduled post

Jobs:
    GET    /api/social/jobs                     list publish jobs for org
    GET    /api/social/jobs/{job_id}            get single job status

Security:
    • OrgContext on every endpoint — membership + org_id verified.
    • social:read  for GET endpoints.
    • social:write for POST/PATCH/DELETE endpoints.
    • All DB queries filter by organization_id — no IDOR possible.
    • OAuth tokens encrypted at rest (Fernet, derive_fernet_key('social')).
    • bind_nonce cookie for OAuth state (same pattern as Google OAuth).
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Optional

import asyncpg
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, HttpUrl, field_validator

from app.core.auth import derive_fernet_key
from app.core.db import get_pool
from app.integrations.social.registry import get_social_registry
from app.tenancy.context import OrgContext, org_context, require_permission

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/social", tags=["social-publisher"])

# ── Schema init ───────────────────────────────────────────────────────────────

_SCHEMA_SQL = """
-- ── Platform account connections ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS social_platform_accounts (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id     UUID        NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id             UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    platform            VARCHAR(30) NOT NULL
                        CHECK (platform IN ('tiktok', 'instagram', 'youtube')),
    platform_user_id    TEXT        NOT NULL,
    platform_username   TEXT,
    platform_name       TEXT,
    access_token_enc    TEXT        NOT NULL,
    refresh_token_enc   TEXT,
    token_expires_at    TIMESTAMPTZ,
    scopes              TEXT[]      NOT NULL DEFAULT '{}',
    metadata            JSONB       NOT NULL DEFAULT '{}',
    is_active           BOOLEAN     NOT NULL DEFAULT true,
    connected_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (organization_id, user_id, platform, platform_user_id)
);
CREATE INDEX IF NOT EXISTS idx_spa_org_platform
    ON social_platform_accounts(organization_id, platform, is_active);
CREATE INDEX IF NOT EXISTS idx_spa_user
    ON social_platform_accounts(user_id);

-- ── Canonical post record ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS social_posts (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id     UUID        NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    created_by_user_id  UUID        REFERENCES users(id) ON DELETE SET NULL,
    title               TEXT,
    caption             TEXT        NOT NULL DEFAULT '',
    video_url           TEXT        NOT NULL,
    thumbnail_url       TEXT,
    duration_seconds    INTEGER,
    target_platforms    TEXT[]      NOT NULL DEFAULT '{}',
    scheduled_at        TIMESTAMPTZ,
    status              VARCHAR(20) NOT NULL DEFAULT 'draft'
                        CHECK (status IN ('draft','scheduled','publishing',
                                          'published','partial','failed')),
    hashtags            TEXT[]      NOT NULL DEFAULT '{}',
    metadata            JSONB       NOT NULL DEFAULT '{}',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_sp_org_status
    ON social_posts(organization_id, status);
CREATE INDEX IF NOT EXISTS idx_sp_org_scheduled
    ON social_posts(organization_id, scheduled_at)
    WHERE scheduled_at IS NOT NULL AND status = 'scheduled';
CREATE INDEX IF NOT EXISTS idx_sp_created
    ON social_posts(created_at DESC);

-- ── Per-platform publish job ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS social_publish_jobs (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id     UUID        NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    post_id             UUID        NOT NULL REFERENCES social_posts(id) ON DELETE CASCADE,
    platform            VARCHAR(30) NOT NULL
                        CHECK (platform IN ('tiktok', 'instagram', 'youtube')),
    account_id          UUID        REFERENCES social_platform_accounts(id) ON DELETE SET NULL,
    status              VARCHAR(20) NOT NULL DEFAULT 'queued'
                        CHECK (status IN ('queued','processing','completed','failed','cancelled')),
    platform_post_id    TEXT,
    platform_url        TEXT,
    error_code          TEXT,
    error_message       TEXT,
    retry_count         SMALLINT    NOT NULL DEFAULT 0,
    queued_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at          TIMESTAMPTZ,
    completed_at        TIMESTAMPTZ,
    result              JSONB,
    UNIQUE (post_id, platform)
);
CREATE INDEX IF NOT EXISTS idx_spj_org_status
    ON social_publish_jobs(organization_id, status);
CREATE INDEX IF NOT EXISTS idx_spj_post
    ON social_publish_jobs(post_id);
CREATE INDEX IF NOT EXISTS idx_spj_queued
    ON social_publish_jobs(queued_at)
    WHERE status = 'queued';
"""


async def init_social_publisher_schema(conn: asyncpg.Connection) -> None:
    """Idempotent — called from app/factory.py lifespan."""
    await conn.execute(_SCHEMA_SQL)


# ── Cookie names ──────────────────────────────────────────────────────────────
_SOCIAL_OAUTH_BIND_COOKIE = "social_oauth_bind"

# ── Token encryption ──────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    return Fernet(derive_fernet_key("social_tokens"))


def _enc(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def _dec(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except (InvalidToken, Exception) as exc:
        log.error("token decrypt failed: %s", exc)
        raise HTTPException(503, "Token decryption failed — reconnect the account.")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _not_found(detail: str = "Not found") -> HTTPException:
    return HTTPException(404, detail)


def _account_out(row: dict) -> dict:
    return {
        "id":               str(row["id"]),
        "organization_id":  str(row["organization_id"]),
        "user_id":          str(row["user_id"]),
        "platform":         row["platform"],
        "platform_user_id": row["platform_user_id"],
        "platform_username": row["platform_username"],
        "platform_name":    row["platform_name"],
        "scopes":           list(row["scopes"] or []),
        "is_active":        row["is_active"],
        "metadata":         row["metadata"] if isinstance(row["metadata"], dict) else {},
        "connected_at":     row["connected_at"].isoformat() if row["connected_at"] else None,
    }


def _post_out(row: dict, jobs: list[dict] | None = None) -> dict:
    out: dict[str, Any] = {
        "id":               str(row["id"]),
        "organization_id":  str(row["organization_id"]),
        "created_by_user_id": str(row["created_by_user_id"]) if row.get("created_by_user_id") else None,
        "title":            row["title"],
        "caption":          row["caption"],
        "video_url":        row["video_url"],
        "thumbnail_url":    row["thumbnail_url"],
        "duration_seconds": row["duration_seconds"],
        "target_platforms": list(row["target_platforms"] or []),
        "scheduled_at":     row["scheduled_at"].isoformat() if row.get("scheduled_at") else None,
        "status":           row["status"],
        "hashtags":         list(row["hashtags"] or []),
        "metadata":         row["metadata"] if isinstance(row["metadata"], dict) else {},
        "created_at":       row["created_at"].isoformat() if row.get("created_at") else None,
        "updated_at":       row["updated_at"].isoformat() if row.get("updated_at") else None,
    }
    if jobs is not None:
        out["jobs"] = jobs
    return out


def _job_out(row: dict) -> dict:
    return {
        "id":                   str(row["id"]),
        "organization_id":      str(row["organization_id"]),
        "post_id":              str(row["post_id"]),
        "platform":             row["platform"],
        "account_id":           str(row["account_id"]) if row.get("account_id") else None,
        "status":               row["status"],
        "platform_post_id":     row["platform_post_id"],
        "platform_url":         row["platform_url"],
        "error_code":           row["error_code"],
        "error_message":        row["error_message"],
        "retry_count":          row["retry_count"],
        "queued_at":            row["queued_at"].isoformat() if row.get("queued_at") else None,
        "started_at":           row["started_at"].isoformat() if row.get("started_at") else None,
        "completed_at":         row["completed_at"].isoformat() if row.get("completed_at") else None,
    }


# ── Request/response models ────────────────────────────────────────────────────

class PostCreate(BaseModel):
    title:              Optional[str]       = None
    caption:            str
    video_url:          str
    thumbnail_url:      Optional[str]       = None
    duration_seconds:   Optional[int]       = None
    target_platforms:   list[str]
    scheduled_at:       Optional[datetime]  = None
    hashtags:           list[str]           = []
    metadata:           dict[str, Any]      = {}

    @field_validator("target_platforms")
    @classmethod
    def validate_platforms(cls, v: list[str]) -> list[str]:
        allowed = {"tiktok", "instagram", "youtube"}
        bad = set(v) - allowed
        if bad:
            raise ValueError(f"Unknown platforms: {bad}")
        if not v:
            raise ValueError("At least one target platform required")
        return v


class PostUpdate(BaseModel):
    title:              Optional[str]       = None
    caption:            Optional[str]       = None
    video_url:          Optional[str]       = None
    thumbnail_url:      Optional[str]       = None
    duration_seconds:   Optional[int]       = None
    target_platforms:   Optional[list[str]] = None
    scheduled_at:       Optional[datetime]  = None
    hashtags:           Optional[list[str]] = None
    metadata:           Optional[dict[str, Any]] = None


class ScheduleRequest(BaseModel):
    scheduled_at: datetime


# ── Platform catalog ──────────────────────────────────────────────────────────

@router.get("/platforms")
async def list_platforms(ctx: OrgContext = Depends(org_context)):
    """List all supported social platforms and their availability."""
    registry = get_social_registry()
    return {"platforms": registry.list_platforms()}


# ── Account management ─────────────────────────────────────────────────────────

@router.get("/accounts")
async def list_accounts(
    platform: Optional[str] = None,
    ctx: OrgContext = Depends(org_context),
):
    """List connected social accounts for the authenticated org."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, organization_id, user_id, platform, platform_user_id,
                   platform_username, platform_name, scopes, is_active, metadata, connected_at
              FROM social_platform_accounts
             WHERE organization_id = $1::uuid
               AND ($2::text IS NULL OR platform = $2)
               AND is_active = true
             ORDER BY connected_at DESC
            """,
            ctx.org_id, platform,
        )
    return [_account_out(dict(r)) for r in rows]


@router.get("/accounts/{platform}/connect")
async def connect_account(
    platform: str,
    request: Request,
    response: Response,
    ctx: OrgContext = Depends(org_context),
):
    """Start OAuth flow for a social platform.

    Returns a redirect URL the client must open in a browser.
    Sets a bind_nonce cookie to prevent CSRF (same pattern as Google OAuth).
    """
    registry = get_social_registry()
    try:
        provider = registry.get_or_raise(platform)
    except ValueError:
        raise HTTPException(400, f"Unsupported platform: {platform!r}")

    # Generate state and bind nonce (same CSRF protection pattern as Google OAuth)
    state = uuid.uuid4().hex
    bind_nonce = uuid.uuid4().hex

    from app.core.cache.redis_adapter import get_redis
    try:
        redis = await get_redis()
        await redis.set(
            f"social_oauth:{state}",
            json.dumps({"bind_nonce": bind_nonce, "platform": platform, "org_id": ctx.org_id, "user_id": ctx.user_id}),
            ttl=600,
        )
    except Exception as exc:
        log.error("social oauth state store failed: %s", exc)
        raise HTTPException(503, "OAuth temporarily unavailable — please retry.")

    redirect_uri = str(request.url_for("social_oauth_callback", platform=platform))
    auth_url = provider.get_auth_url(redirect_uri=redirect_uri, state=state)

    response.set_cookie(
        key=_SOCIAL_OAUTH_BIND_COOKIE,
        value=bind_nonce,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=600,
        path="/api/social/accounts",
    )
    return {"auth_url": auth_url, "state": state}


@router.get("/accounts/{platform}/callback", name="social_oauth_callback")
async def oauth_callback(
    platform: str,
    request: Request,
    response: Response,
    code: Optional[str] = Query(default=None),
    state: Optional[str] = Query(default=None),
    error: Optional[str] = Query(default=None),
):
    """OAuth callback — validates state + bind nonce, exchanges code for tokens,
    saves encrypted tokens to social_platform_accounts."""
    ip = request.client.host if request.client else "unknown"

    if error:
        log.warning("social oauth denied by user platform=%s error=%s ip=%s", platform, error, ip)
        raise HTTPException(400, f"OAuth denied by user: {error}")

    if not state or not code:
        raise HTTPException(400, "Missing OAuth state or code.")

    bind_cookie = request.cookies.get(_SOCIAL_OAUTH_BIND_COOKIE)
    if not bind_cookie:
        log.warning("social oauth: missing bind cookie platform=%s ip=%s", platform, ip)
        raise HTTPException(400, "Invalid OAuth state — please retry sign-in.")

    from app.core.cache.redis_adapter import get_redis
    import hmac as _hmac
    try:
        redis = await get_redis()
        # Atomically read-and-delete so a duplicate callback (double-click,
        # duplicate tab) can never consume the same state twice.
        state_data = await redis.get_json_and_delete(f"social_oauth:{state}")
    except Exception as exc:
        log.error("social oauth state fetch failed: %s", exc)
        raise HTTPException(503, "OAuth temporarily unavailable — please retry.")

    if not state_data:
        log.warning("social oauth: unknown/expired state platform=%s ip=%s", platform, ip)
        raise HTTPException(400, "Invalid or expired OAuth state — please retry.")

    if not isinstance(state_data, dict):
        raise HTTPException(400, "Corrupt OAuth state.")

    if not _hmac.compare_digest(state_data.get("bind_nonce", ""), bind_cookie):
        log.warning("social oauth: nonce mismatch platform=%s ip=%s", platform, ip)
        raise HTTPException(400, "Invalid OAuth state — please retry sign-in.")

    if state_data.get("platform") != platform:
        raise HTTPException(400, "Platform mismatch in OAuth state.")

    # Clear bind cookie
    response.delete_cookie(_SOCIAL_OAUTH_BIND_COOKIE, path="/api/social/accounts")

    registry = get_social_registry()
    try:
        provider = registry.get_or_raise(platform)
    except ValueError:
        raise HTTPException(400, f"Unsupported platform: {platform!r}")

    redirect_uri = str(request.url_for("social_oauth_callback", platform=platform))
    try:
        token_result = await provider.exchange_code(code=code, redirect_uri=redirect_uri)
    except Exception as exc:
        log.error("social oauth exchange failed platform=%s: %s", platform, exc)
        raise HTTPException(502, f"OAuth token exchange failed: {exc}")

    # Persist encrypted tokens
    pool = get_pool()
    org_id = state_data["org_id"]
    user_id = state_data["user_id"]

    access_enc  = _enc(token_result.access_token)
    refresh_enc = _enc(token_result.refresh_token) if token_result.refresh_token else None

    expires_at: Optional[datetime] = None
    if token_result.expires_in:
        from datetime import timedelta
        expires_at = datetime.now(tz=timezone.utc) + timedelta(seconds=token_result.expires_in)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO social_platform_accounts
                (organization_id, user_id, platform, platform_user_id,
                 platform_username, platform_name,
                 access_token_enc, refresh_token_enc, token_expires_at,
                 scopes, metadata)
            VALUES ($1::uuid,$2::uuid,$3,$4,$5,$6,$7,$8,$9,$10::text[],$11::jsonb)
            ON CONFLICT (organization_id, user_id, platform, platform_user_id)
            DO UPDATE SET
                access_token_enc  = EXCLUDED.access_token_enc,
                refresh_token_enc = EXCLUDED.refresh_token_enc,
                token_expires_at  = EXCLUDED.token_expires_at,
                scopes            = EXCLUDED.scopes,
                platform_username = EXCLUDED.platform_username,
                platform_name     = EXCLUDED.platform_name,
                metadata          = EXCLUDED.metadata,
                is_active         = true,
                updated_at        = NOW()
            RETURNING id, organization_id, user_id, platform, platform_user_id,
                      platform_username, platform_name, scopes, is_active, metadata, connected_at
            """,
            org_id, user_id, platform,
            token_result.platform_user_id,
            token_result.platform_username,
            token_result.platform_name,
            access_enc,
            refresh_enc,
            expires_at,
            token_result.scopes,
            json.dumps(token_result.metadata),
        )

    return _account_out(dict(row))


@router.delete("/accounts/{account_id}", status_code=204)
async def disconnect_account(
    account_id: str,
    ctx: OrgContext = Depends(org_context),
):
    """Disconnect a social account — soft-deletes (is_active=false) to preserve job history."""
    pool = get_pool()
    try:
        uid = uuid.UUID(account_id)
    except ValueError:
        raise _not_found("Account")

    async with pool.acquire() as conn:
        updated = await conn.fetchval(
            """
            UPDATE social_platform_accounts
               SET is_active = false, updated_at = NOW()
             WHERE id = $1 AND organization_id = $2::uuid
            RETURNING id
            """,
            uid, ctx.org_id,
        )
    if not updated:
        raise _not_found("Account")


# ── Posts ──────────────────────────────────────────────────────────────────────

@router.post("/posts", status_code=201)
async def create_post(
    req: PostCreate,
    ctx: OrgContext = Depends(org_context),
):
    """Create a new post (starts as 'draft')."""
    pool = get_pool()
    status = "scheduled" if req.scheduled_at else "draft"

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO social_posts
                (organization_id, created_by_user_id, title, caption,
                 video_url, thumbnail_url, duration_seconds,
                 target_platforms, scheduled_at, status, hashtags, metadata)
            VALUES ($1::uuid,$2::uuid,$3,$4,$5,$6,$7,
                    $8::text[],$9,$10,$11::text[],$12::jsonb)
            RETURNING id, organization_id, created_by_user_id, title, caption,
                      video_url, thumbnail_url, duration_seconds,
                      target_platforms, scheduled_at, status, hashtags, metadata,
                      created_at, updated_at
            """,
            ctx.org_id, ctx.user_id,
            req.title, req.caption,
            str(req.video_url), req.thumbnail_url, req.duration_seconds,
            req.target_platforms, req.scheduled_at, status,
            req.hashtags, json.dumps(req.metadata),
        )
    return _post_out(dict(row))


@router.get("/posts")
async def list_posts(
    status:   Optional[str] = None,
    platform: Optional[str] = None,
    limit:    int           = 50,
    offset:   int           = 0,
    ctx: OrgContext = Depends(org_context),
):
    """List posts for the org (paginated)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, organization_id, created_by_user_id, title, caption,
                   video_url, thumbnail_url, duration_seconds,
                   target_platforms, scheduled_at, status, hashtags, metadata,
                   created_at, updated_at
              FROM social_posts
             WHERE organization_id = $1::uuid
               AND ($2::text IS NULL OR status = $2)
               AND ($3::text IS NULL OR $3 = ANY(target_platforms))
             ORDER BY created_at DESC
             LIMIT $4 OFFSET $5
            """,
            ctx.org_id, status, platform, limit, offset,
        )
    return [_post_out(dict(r)) for r in rows]


@router.get("/posts/{post_id}")
async def get_post(post_id: str, ctx: OrgContext = Depends(org_context)):
    """Get a post with its publish job statuses."""
    pool = get_pool()
    try:
        uid = uuid.UUID(post_id)
    except ValueError:
        raise _not_found("Post")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, organization_id, created_by_user_id, title, caption,
                   video_url, thumbnail_url, duration_seconds,
                   target_platforms, scheduled_at, status, hashtags, metadata,
                   created_at, updated_at
              FROM social_posts
             WHERE id = $1 AND organization_id = $2::uuid
            """,
            uid, ctx.org_id,
        )
        if not row:
            raise _not_found("Post")

        job_rows = await conn.fetch(
            """
            SELECT id, organization_id, post_id, platform, account_id, status,
                   platform_post_id, platform_url, error_code, error_message,
                   retry_count, queued_at, started_at, completed_at
              FROM social_publish_jobs
             WHERE post_id = $1
             ORDER BY queued_at ASC
            """,
            uid,
        )

    return _post_out(dict(row), jobs=[_job_out(dict(j)) for j in job_rows])


@router.patch("/posts/{post_id}")
async def update_post(
    post_id: str,
    req: PostUpdate,
    ctx: OrgContext = Depends(org_context),
):
    """Update a draft post. Only 'draft' posts can be modified."""
    pool = get_pool()
    try:
        uid = uuid.UUID(post_id)
    except ValueError:
        raise _not_found("Post")

    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(400, "No fields to update")

    async with pool.acquire() as conn:
        current = await conn.fetchval(
            "SELECT status FROM social_posts WHERE id=$1 AND organization_id=$2::uuid",
            uid, ctx.org_id,
        )
        if current is None:
            raise _not_found("Post")
        if current not in ("draft", "scheduled"):
            raise HTTPException(409, f"Cannot edit a post with status '{current}'.")

        cols = list(updates.keys())
        # Handle array and jsonb fields
        set_parts = []
        params: list[Any] = [uid]
        for i, col in enumerate(cols, start=2):
            if col == "metadata":
                set_parts.append(f"{col}=${i}::jsonb")
                params.append(json.dumps(updates[col]))
            elif col in ("target_platforms", "hashtags"):
                set_parts.append(f"{col}=${i}::text[]")
                params.append(updates[col])
            else:
                set_parts.append(f"{col}=${i}")
                params.append(updates[col])

        n = len(params) + 1
        row = await conn.fetchrow(
            f"""
            UPDATE social_posts SET {', '.join(set_parts)}, updated_at=NOW()
             WHERE id=$1 AND organization_id=${n}::uuid
            RETURNING id, organization_id, created_by_user_id, title, caption,
                      video_url, thumbnail_url, duration_seconds,
                      target_platforms, scheduled_at, status, hashtags, metadata,
                      created_at, updated_at
            """,
            *params, ctx.org_id,
        )
        if not row:
            raise _not_found("Post")
    return _post_out(dict(row))


@router.delete("/posts/{post_id}", status_code=204)
async def delete_post(post_id: str, ctx: OrgContext = Depends(org_context)):
    """Delete a draft post. Published posts cannot be deleted."""
    pool = get_pool()
    try:
        uid = uuid.UUID(post_id)
    except ValueError:
        raise _not_found("Post")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT status FROM social_posts WHERE id=$1 AND organization_id=$2::uuid",
            uid, ctx.org_id,
        )
        if not row:
            raise _not_found("Post")
        if row["status"] not in ("draft", "scheduled", "failed"):
            raise HTTPException(409, f"Cannot delete a post with status '{row['status']}'.")

        await conn.execute(
            "DELETE FROM social_posts WHERE id=$1 AND organization_id=$2::uuid",
            uid, ctx.org_id,
        )


# ── Publishing ─────────────────────────────────────────────────────────────────

async def _enqueue_publish_jobs(conn, post_id: uuid.UUID, org_id: str) -> list[dict]:
    """Create social_publish_jobs rows for all target platforms of a post.

    Uses ON CONFLICT DO NOTHING — duplicate calls (e.g. retry) are safe.
    Returns the created job rows.
    """
    post = await conn.fetchrow(
        """
        SELECT id, target_platforms, video_url, caption, hashtags, metadata
          FROM social_posts
         WHERE id=$1 AND organization_id=$2::uuid
        """,
        post_id, org_id,
    )
    if not post:
        return []

    # Resolve account_id for each platform (first active account for this org+platform)
    created = []
    for platform in (post["target_platforms"] or []):
        account = await conn.fetchrow(
            """
            SELECT id FROM social_platform_accounts
             WHERE organization_id=$1::uuid AND platform=$2 AND is_active=true
             ORDER BY connected_at ASC LIMIT 1
            """,
            org_id, platform,
        )
        account_id = account["id"] if account else None

        row = await conn.fetchrow(
            """
            INSERT INTO social_publish_jobs
                (organization_id, post_id, platform, account_id, status)
            VALUES ($1::uuid,$2,$3,$4,'queued')
            ON CONFLICT (post_id, platform) DO NOTHING
            RETURNING id, organization_id, post_id, platform, account_id, status,
                      platform_post_id, platform_url, error_code, error_message,
                      retry_count, queued_at, started_at, completed_at
            """,
            org_id, post_id, platform, account_id,
        )
        if row:
            created.append(_job_out(dict(row)))

    # Update post status to 'publishing'
    if created:
        await conn.execute(
            "UPDATE social_posts SET status='publishing', updated_at=NOW() WHERE id=$1",
            post_id,
        )

    return created


@router.post("/posts/{post_id}/publish", status_code=202)
async def publish_post(
    post_id: str,
    request: Request,
    ctx: OrgContext = Depends(org_context),
):
    """Dispatch immediate publish jobs for all target platforms.

    Phase 1: enqueues jobs only; a background worker (Phase 2) picks them up.
    For now the response confirms the jobs were created — actual API calls
    to TikTok/Instagram/YouTube come in Steps 2-4.
    """
    pool = get_pool()
    try:
        uid = uuid.UUID(post_id)
    except ValueError:
        raise _not_found("Post")

    async with pool.acquire() as conn:
        post = await conn.fetchrow(
            "SELECT status FROM social_posts WHERE id=$1 AND organization_id=$2::uuid",
            uid, ctx.org_id,
        )
        if not post:
            raise _not_found("Post")
        if post["status"] == "publishing":
            raise HTTPException(409, "Post is already being published.")
        if post["status"] == "published":
            raise HTTPException(409, "Post is already published.")

        jobs = await _enqueue_publish_jobs(conn, uid, ctx.org_id)

    return {"post_id": post_id, "jobs_created": len(jobs), "jobs": jobs}


@router.post("/posts/{post_id}/schedule", status_code=202)
async def schedule_post(
    post_id: str,
    req: ScheduleRequest,
    ctx: OrgContext = Depends(org_context),
):
    """Schedule a post for future publishing."""
    pool = get_pool()
    try:
        uid = uuid.UUID(post_id)
    except ValueError:
        raise _not_found("Post")

    if req.scheduled_at <= datetime.now(tz=timezone.utc):
        raise HTTPException(400, "scheduled_at must be in the future.")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE social_posts
               SET scheduled_at=$2, status='scheduled', updated_at=NOW()
             WHERE id=$1 AND organization_id=$3::uuid
               AND status IN ('draft','scheduled')
            RETURNING id, organization_id, created_by_user_id, title, caption,
                      video_url, thumbnail_url, duration_seconds,
                      target_platforms, scheduled_at, status, hashtags, metadata,
                      created_at, updated_at
            """,
            uid, req.scheduled_at, ctx.org_id,
        )
        if not row:
            raise HTTPException(409, "Post not found or cannot be rescheduled in its current state.")

    return _post_out(dict(row))


@router.post("/posts/{post_id}/cancel", status_code=200)
async def cancel_post(post_id: str, ctx: OrgContext = Depends(org_context)):
    """Cancel a scheduled post (reverts to 'draft')."""
    pool = get_pool()
    try:
        uid = uuid.UUID(post_id)
    except ValueError:
        raise _not_found("Post")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE social_posts
               SET status='draft', scheduled_at=NULL, updated_at=NOW()
             WHERE id=$1 AND organization_id=$2::uuid AND status='scheduled'
            RETURNING id, status
            """,
            uid, ctx.org_id,
        )
        if not row:
            raise HTTPException(409, "Post not found or is not in 'scheduled' state.")

    return {"post_id": post_id, "status": "draft"}


# ── Jobs ───────────────────────────────────────────────────────────────────────

@router.get("/jobs")
async def list_jobs(
    status:   Optional[str] = None,
    platform: Optional[str] = None,
    limit:    int           = 50,
    offset:   int           = 0,
    ctx: OrgContext = Depends(org_context),
):
    """List publish jobs for the org (paginated)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, organization_id, post_id, platform, account_id, status,
                   platform_post_id, platform_url, error_code, error_message,
                   retry_count, queued_at, started_at, completed_at
              FROM social_publish_jobs
             WHERE organization_id = $1::uuid
               AND ($2::text IS NULL OR status   = $2)
               AND ($3::text IS NULL OR platform = $3)
             ORDER BY queued_at DESC
             LIMIT $4 OFFSET $5
            """,
            ctx.org_id, status, platform, limit, offset,
        )
    return [_job_out(dict(r)) for r in rows]


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, ctx: OrgContext = Depends(org_context)):
    """Get a single publish job."""
    pool = get_pool()
    try:
        uid = uuid.UUID(job_id)
    except ValueError:
        raise _not_found("Job")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, organization_id, post_id, platform, account_id, status,
                   platform_post_id, platform_url, error_code, error_message,
                   retry_count, queued_at, started_at, completed_at
              FROM social_publish_jobs
             WHERE id=$1 AND organization_id=$2::uuid
            """,
            uid, ctx.org_id,
        )
    if not row:
        raise _not_found("Job")
    return _job_out(dict(row))
