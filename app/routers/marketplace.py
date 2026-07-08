"""
Marketplace API — Layer 11.

Endpoints:
  GET  /marketplace/listings          list all items (paginated, filterable)
  GET  /marketplace/listings/{id}     item detail
  POST /marketplace/listings          publish new item
  PUT  /marketplace/listings/{id}     update item
  DELETE /marketplace/listings/{id}   remove item (soft delete on PG backend)
  POST /marketplace/listings/{id}/install   install / download
  GET  /marketplace/categories        all categories with counts
  GET  /marketplace/search            full-text search
  POST /marketplace/reviews           submit review
  GET  /marketplace/listings/{id}/reviews  list reviews

Item types: agent | plugin | theme | template | prompt_pack | workflow | dataset | model

Persistence: PostgreSQL (marketplace_items / versions / reviews / installs)
with a JSON-file fallback when no database pool is configured — see
app/marketplace/store.py. The API shape is identical on both backends.
"""
from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.marketplace import get_marketplace_store

router = APIRouter(prefix="/marketplace", tags=["marketplace"])


# ── Item types ────────────────────────────────────────────────────────────────

class ItemType(str, Enum):
    AGENT        = "agent"
    PLUGIN       = "plugin"
    THEME        = "theme"
    TEMPLATE     = "template"
    PROMPT_PACK  = "prompt_pack"
    WORKFLOW     = "workflow"
    DATASET      = "dataset"
    MODEL        = "model"


class PricingModel(str, Enum):
    FREE        = "free"
    ONE_TIME    = "one_time"
    SUBSCRIPTION= "subscription"
    PAY_PER_USE = "pay_per_use"


# ── Schemas ───────────────────────────────────────────────────────────────────

class PublishRequest(BaseModel):
    name        : str = Field(..., min_length=3, max_length=120)
    type        : ItemType
    description : str = Field(..., min_length=10, max_length=2000)
    version     : str = "1.0.0"
    pricing     : PricingModel = PricingModel.FREE
    price_usd   : float = Field(0.0, ge=0)
    tags        : list[str] = Field(default_factory=list)
    metadata    : dict = Field(default_factory=dict)


class ReviewRequest(BaseModel):
    listing_id : str
    rating     : float = Field(..., ge=1, le=5)
    comment    : Optional[str] = None
    reviewer   : str = "anonymous"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _paginate(items: list, page: int, per_page: int):
    total = len(items)
    start = (page - 1) * per_page
    return items[start : start + per_page], total


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/listings")
async def list_listings(
    page     : int = Query(1, ge=1),
    per_page : int = Query(20, ge=1, le=100),
    type     : Optional[str] = None,
    pricing  : Optional[str] = None,
    sort     : str = Query("installs", pattern="^(installs|rating|created_at|price_usd)$"),
    order    : str = Query("desc", pattern="^(asc|desc)$"),
):
    store = get_marketplace_store()
    items = await store.list_items()

    if type:
        items = [i for i in items if i["type"] == type]
    if pricing:
        items = [i for i in items if i["pricing"] == pricing]

    items.sort(key=lambda x: x.get(sort, 0), reverse=(order == "desc"))

    page_items, total = _paginate(items, page, per_page)
    return {
        "items"   : page_items,
        "total"   : total,
        "page"    : page,
        "per_page": per_page,
        "pages"   : max(1, -(-total // per_page)),
    }


@router.get("/listings/{listing_id}")
async def get_listing(listing_id: str):
    store = get_marketplace_store()
    item = await store.get_item(listing_id)
    if not item:
        raise HTTPException(status_code=404, detail="Listing not found")
    reviews = await store.list_reviews(listing_id)
    return {**item, "reviews": reviews}


@router.post("/listings", status_code=201)
async def publish_listing(body: PublishRequest):
    store = get_marketplace_store()
    listing_id = f"listing-{uuid.uuid4().hex[:8]}"
    now = time.time()
    item = {
        "id"         : listing_id,
        "name"       : body.name,
        "type"       : body.type.value,
        "description": body.description,
        "author"     : "anonymous",
        "version"    : body.version,
        "pricing"    : body.pricing.value,
        "price_usd"  : body.price_usd,
        "tags"       : body.tags,
        "metadata"   : body.metadata,
        "installs"   : 0,
        "rating"     : 0.0,
        "rating_count": 0,
        "verified"   : False,
        "created_at" : now,
        "updated_at" : now,
    }
    await store.upsert_item(item)
    try:
        from app.core.events import get_event_bus
        await get_event_bus().publish("marketplace.published",
                                      {"listing_id": listing_id, "name": body.name})
    except Exception:
        pass
    return item


@router.put("/listings/{listing_id}")
async def update_listing(listing_id: str, body: PublishRequest):
    store = get_marketplace_store()
    item = await store.get_item(listing_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    item.update({
        "name"       : body.name,
        "description": body.description,
        "version"    : body.version,
        "pricing"    : body.pricing.value,
        "price_usd"  : body.price_usd,
        "tags"       : body.tags,
        "metadata"   : body.metadata,
        "updated_at" : time.time(),
    })
    await store.upsert_item(item)
    return item


@router.delete("/listings/{listing_id}", status_code=204)
async def delete_listing(listing_id: str):
    store = get_marketplace_store()
    if not await store.delete_item(listing_id):
        raise HTTPException(status_code=404, detail="Listing not found")


@router.post("/listings/{listing_id}/install")
async def install_listing(listing_id: str, request: Request):
    store = get_marketplace_store()
    item = await store.record_install(
        listing_id,
        org_id=request.headers.get("X-Organization-Id"),
        user_email=request.headers.get("X-User-Email"),
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    try:
        from app.core.events import get_event_bus
        await get_event_bus().publish("marketplace.installed",
                                      {"listing_id": listing_id, "name": item["name"]})
    except Exception:
        pass
    return {
        "status"     : "installed",
        "listing_id" : listing_id,
        "name"       : item["name"],
        "version"    : item["version"],
        "installed_at": time.time(),
    }


@router.get("/categories")
async def list_categories():
    store = get_marketplace_store()
    counts: dict[str, int] = {}
    for item in await store.list_items():
        t = item.get("type", "other")
        counts[t] = counts.get(t, 0) + 1
    return [{"type": t, "count": c} for t, c in sorted(counts.items())]


@router.get("/search")
async def search_listings(
    q        : str = Query(..., min_length=1),
    page     : int = Query(1, ge=1),
    per_page : int = Query(20, ge=1, le=100),
):
    store = get_marketplace_store()
    q_lower = q.lower()
    results = [
        item for item in await store.list_items()
        if q_lower in item["name"].lower()
        or q_lower in item["description"].lower()
        or any(q_lower in tag for tag in item.get("tags", []))
    ]
    page_items, total = _paginate(results, page, per_page)
    return {
        "query"   : q,
        "items"   : page_items,
        "total"   : total,
        "page"    : page,
        "per_page": per_page,
    }


@router.post("/reviews", status_code=201)
async def submit_review(body: ReviewRequest):
    store = get_marketplace_store()
    if await store.get_item(body.listing_id) is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    review = {
        "id"        : str(uuid.uuid4()),
        "listing_id": body.listing_id,
        "rating"    : body.rating,
        "comment"   : body.comment,
        "reviewer"  : body.reviewer,
        "created_at": time.time(),
    }
    return await store.add_review(review)


@router.get("/listings/{listing_id}/reviews")
async def get_reviews(listing_id: str):
    store = get_marketplace_store()
    if await store.get_item(listing_id) is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    return await store.list_reviews(listing_id)
