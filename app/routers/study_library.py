"""Study Library: public metadata; verified buyer-only PDF delivery."""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import io
import json
import os
import re
import uuid
from zoneinfo import ZoneInfo

from fastapi import (
    APIRouter,
    Depends,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    File,
)
from fastapi.security import HTTPBearer
from pypdf import PdfReader
from PIL import Image

from app.core.db import get_pool
from app.routers.auth_users import get_current_user
from app.study.payhip import parse_event, record_event

router = APIRouter(prefix="/api/study-library", tags=["study-library"])
SUBJECTS = frozenset(
    ("math", "physics", "chemistry", "biology", "english", "computing")
)
PDF_LIMIT = 8 * 1024 * 1024
COVER_LIMIT = 2 * 1024 * 1024
SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def is_public_study_request(method: str, path: str) -> bool:
    """Exact method/path allowlist. Private file/access routes stay authenticated."""
    return (
        method == "GET"
        and (
            path == "/api/study-library/catalog"
            or re.fullmatch(r"/api/study-library/lessons/[a-z0-9-]{1,80}/cover", path)
            is not None
        )
    ) or (method == "POST" and path == "/api/study-library/payhip")


def is_study_publish_request(request: Request) -> bool:
    """Check automation credentials before multipart parsing/spooling begins."""
    if request.method != "POST" or request.url.path != "/api/study-library/lessons":
        return False
    expected = os.getenv("STUDY_LIBRARY_PUBLISH_KEY", "")
    supplied = request.headers.get("X-Study-Publish-Key", "")
    return bool(
        len(expected) >= 32
        and supplied
        and hmac.compare_digest(supplied.encode(), expected.encode())
    )


def _checkout_url() -> str | None:
    url = os.getenv("STUDY_PAYHIP_CHECKOUT_URL", "").strip()
    key = os.getenv("STUDY_PAYHIP_PRODUCT_KEY", "").strip()
    if not re.fullmatch(r"[A-Za-z0-9]{1,80}", key):
        return None
    return url if url == f"https://payhip.com/b/{key}" else None


async def _verified_user(user=Depends(get_current_user)) -> dict:
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, email, email_verified FROM users WHERE id=$1",
            uuid.UUID(user["id"]),
        )
    if not row or row["email"].strip().lower() != user["email"].strip().lower():
        raise HTTPException(401, "Account identity changed; sign in again")
    if not row["email_verified"]:
        raise HTTPException(
            403, "Verify your account email before accessing the library"
        )
    return dict(row)


def _is_admin(user: dict) -> bool:
    configured = os.getenv("STUDY_LIBRARY_ADMIN_EMAIL", "").strip().lower()
    return bool(configured and user["email"].strip().lower() == configured)


async def _has_access(user: dict) -> bool:
    if _is_admin(user):
        return True
    key = os.getenv("STUDY_PAYHIP_PRODUCT_KEY", "").strip()
    if not key:
        return False
    async with get_pool().acquire() as conn:
        return bool(
            await conn.fetchval(
                """SELECT EXISTS (SELECT 1 FROM study_purchases WHERE buyer_email=$1
                AND product_key=$2 AND paid_at IS NOT NULL AND refunded_at IS NULL)""",
                user["email"].strip().lower(),
                key,
            )
        )


async def _publisher(request: Request):
    supplied = request.headers.get("X-Study-Publish-Key", "")
    if supplied:
        expected = os.getenv("STUDY_LIBRARY_PUBLISH_KEY", "")
        if len(expected) < 32 or not hmac.compare_digest(
            supplied.encode(), expected.encode()
        ):
            raise HTTPException(401, "Invalid publishing credentials")
        return
    creds = await HTTPBearer(auto_error=False)(request)
    user = await _verified_user(await get_current_user(creds))
    if not _is_admin(user):
        raise HTTPException(403, "Library publisher access required")


@router.get("/catalog")
async def catalog(
    subject: str | None = None,
    q: str = Query("", max_length=120),
    offset: int = Query(0, ge=0),
    limit: int = Query(30, ge=1, le=60),
):
    if subject and subject not in SUBJECTS:
        raise HTTPException(422, "Unknown subject")
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            """SELECT slug, title, subject, description, pages, published_at
               FROM study_lessons WHERE published_at <= NOW()
               AND ($1::text IS NULL OR subject=$1)
               AND ($2::text = '' OR STRPOS(LOWER(title || ' ' || description), LOWER($2)) > 0)
               ORDER BY published_at DESC, slug LIMIT $3 OFFSET $4""",
            subject,
            q.strip(),
            limit,
            offset,
        )
    return {
        "lessons": [dict(r, published_at=r["published_at"].isoformat()) for r in rows],
        "checkout_url": _checkout_url(),
        "limit": limit,
        "offset": offset,
    }


@router.get("/access")
async def access(user=Depends(_verified_user)):
    return {"has_access": await _has_access(user), "is_admin": _is_admin(user)}


@router.get("/lessons/{slug}/cover")
async def cover(slug: str):
    if len(slug) > 80 or not SLUG.fullmatch(slug):
        raise HTTPException(404, "Lesson not found")
    async with get_pool().acquire() as conn:
        data = await conn.fetchval(
            "SELECT cover_data FROM study_lessons WHERE slug=$1 AND published_at <= NOW()",
            slug,
        )
    if data is None:
        raise HTTPException(404, "Lesson not found")
    return Response(
        bytes(data),
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=300"},
    )


@router.get("/lessons/{slug}/download")
async def download(slug: str, user=Depends(_verified_user)):
    if not await _has_access(user):
        raise HTTPException(
            403, "Purchase library access using the same verified email"
        )
    if len(slug) > 80 or not SLUG.fullmatch(slug):
        raise HTTPException(404, "Lesson not found")
    async with get_pool().acquire() as conn:
        data = await conn.fetchval(
            "SELECT pdf_data FROM study_lessons WHERE slug=$1 AND published_at <= NOW()",
            slug,
        )
    if data is None:
        raise HTTPException(404, "Lesson not found")
    return Response(
        bytes(data),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{slug}.pdf"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/payhip")
async def payhip_webhook(request: Request):
    # Bound the body even when Content-Length is missing or false.
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > 65536:
            raise HTTPException(413, "Webhook body too large")
        body.extend(chunk)
    try:
        payload = json.loads(body)
        if not isinstance(payload, dict):
            raise ValueError
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise HTTPException(400, "Invalid webhook JSON") from None
    event = parse_event(
        payload,
        os.getenv("STUDY_PAYHIP_API_KEY", ""),
        os.getenv("STUDY_PAYHIP_PRODUCT_KEY", "").strip(),
    )
    if event:
        async with get_pool().acquire() as conn:
            await record_event(conn, event)
    return {"received": True}


@router.post("/lessons", dependencies=[Depends(_publisher)])
async def publish_lesson(
    slug: str = Form(..., max_length=80),
    title: str = Form(..., min_length=1, max_length=160),
    subject: str = Form(...),
    description: str = Form(..., min_length=1, max_length=1200),
    pdf: UploadFile = File(...),
    cover: UploadFile = File(...),
):
    if (
        not SLUG.fullmatch(slug)
        or subject not in SUBJECTS
        or not title.strip()
        or not description.strip()
    ):
        raise HTTPException(422, "Invalid lesson metadata")
    pdf_bytes = await pdf.read(PDF_LIMIT + 1)
    cover_bytes = await cover.read(COVER_LIMIT + 1)
    if len(pdf_bytes) > PDF_LIMIT or len(cover_bytes) > COVER_LIMIT:
        raise HTTPException(413, "PDF limit is 8 MiB; cover limit is 2 MiB")
    try:
        if not pdf_bytes.startswith(b"%PDF-"):
            raise ValueError
        reader = PdfReader(io.BytesIO(pdf_bytes), strict=True)
        if reader.is_encrypted:
            raise ValueError
        pages = len(reader.pages)
        if not 1 <= pages <= 40:
            raise ValueError
    except Exception:
        raise HTTPException(
            422, "A readable, unencrypted PDF of 1 to 40 pages is required"
        ) from None
    try:
        with Image.open(io.BytesIO(cover_bytes)) as image:
            width, height = image.size
            if image.format != "PNG" or not (
                200 <= width <= 3000 and 200 <= height <= 3000
            ):
                raise ValueError
            image.verify()
    except Exception:
        raise HTTPException(
            422, "A valid PNG cover of 200 to 3000 pixels per side is required"
        ) from None
    digest = hashlib.sha256(pdf_bytes).hexdigest()
    async with get_pool().acquire() as conn, conn.transaction():
        # Across processes/instances: concurrent publishers cannot exceed 3 releases/day.
        await conn.execute("SELECT pg_advisory_xact_lock(181941, 3)")
        existing = await conn.fetchrow(
            "SELECT slug, pdf_sha256 FROM study_lessons WHERE slug=$1 OR pdf_sha256=$2",
            slug,
            digest,
        )
        if existing:
            if existing["slug"] == slug and existing["pdf_sha256"] == digest:
                return {"slug": slug, "created": False}
            raise HTTPException(409, "Lesson slug or PDF already exists")
        now = dt.datetime.now(dt.timezone.utc)
        local_date = now.astimezone(ZoneInfo("Asia/Dubai")).date()
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM study_lessons WHERE (published_at AT TIME ZONE 'Asia/Dubai')::date=$1",
            local_date,
        )
        if count >= 3:
            raise HTTPException(
                409, "Three lessons have already been published for this Dubai date"
            )
        await conn.execute(
            """INSERT INTO study_lessons
            (slug,title,subject,description,pages,pdf_data,pdf_sha256,cover_data,published_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)""",
            slug,
            title.strip(),
            subject,
            description.strip(),
            pages,
            pdf_bytes,
            digest,
            cover_bytes,
            now,
        )
    return {"slug": slug, "created": True}
