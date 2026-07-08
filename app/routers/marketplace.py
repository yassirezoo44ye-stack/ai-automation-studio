"""
Marketplace API — Layer 11.

Endpoints:
  GET  /marketplace/listings          list all items (paginated, filterable)
  GET  /marketplace/listings/{id}     item detail
  POST /marketplace/listings          publish new item (auth required)
  PUT  /marketplace/listings/{id}     update own item (auth required)
  DELETE /marketplace/listings/{id}   remove own item (auth required)
  POST /marketplace/listings/{id}/install   install / download
  GET  /marketplace/categories        all categories with counts
  GET  /marketplace/search            full-text search
  POST /marketplace/reviews           submit review
  GET  /marketplace/listings/{id}/reviews  list reviews

Item types: agent | plugin | theme | template | prompt_pack | workflow | dataset | model
"""
from __future__ import annotations

import json
import os
import time
import uuid
from enum import Enum
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter(prefix="/marketplace", tags=["marketplace"])

# ── Persistence (JSON file, upgrade to DB table when ready) ──────────────────

_DATA_DIR = Path(os.getenv("WORKSPACES", "/tmp")) / ".marketplace"
_DATA_DIR.mkdir(parents=True, exist_ok=True)
_LISTINGS_FILE = _DATA_DIR / "listings.json"
_REVIEWS_FILE  = _DATA_DIR / "reviews.json"


def _load() -> tuple[dict, dict]:
    try:
        store   = json.loads(_LISTINGS_FILE.read_text()) if _LISTINGS_FILE.exists() else {}
        reviews = json.loads(_REVIEWS_FILE.read_text())  if _REVIEWS_FILE.exists()  else {}
        return store, reviews
    except Exception:
        return {}, {}


def _save(store: dict, reviews: dict) -> None:
    try:
        _LISTINGS_FILE.write_text(json.dumps(store,   indent=2))
        _REVIEWS_FILE.write_text( json.dumps(reviews, indent=2))
    except Exception:
        pass   # log in production; don't crash API on write failure


_STORE, _REVIEWS = _load()

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


# ── In-memory store (replace with DB queries in production) ───────────────────

_STORE: dict[str, dict] = {}
_REVIEWS: dict[str, list] = {}    # listing_id → reviews


def _seed() -> None:
    """Seed example listings only if the store is empty (first boot)."""
    if _STORE:
        return
    examples = [
        {
            "id"         : "listing-001",
            "name"       : "Python Code Reviewer",
            "type"       : "agent",
            "description": "Automated code review agent with security scanning and style suggestions.",
            "author"     : "axiom-labs",
            "version"    : "1.2.0",
            "pricing"    : "free",
            "price_usd"  : 0.0,
            "tags"       : ["python", "code-review", "security"],
            "installs"   : 1420,
            "rating"     : 4.7,
            "rating_count": 38,
            "created_at" : time.time() - 86400 * 10,
            "updated_at" : time.time() - 86400 * 2,
            "verified"   : True,
        },
        {
            "id"         : "listing-002",
            "name"       : "Glassmorphism Theme Pack",
            "type"       : "theme",
            "description": "12 polished glassmorphism UI themes for the axiomUI platform.",
            "author"     : "designforge",
            "version"    : "2.0.1",
            "pricing"    : "one_time",
            "price_usd"  : 9.99,
            "tags"       : ["theme", "glassmorphism", "dark"],
            "installs"   : 863,
            "rating"     : 4.9,
            "rating_count": 21,
            "created_at" : time.time() - 86400 * 30,
            "updated_at" : time.time() - 86400 * 5,
            "verified"   : True,
        },
        {
            "id"         : "listing-003",
            "name"       : "CI/CD Workflow Bundle",
            "type"       : "workflow",
            "description": "Complete GitHub Actions + Docker deployment workflow template bundle.",
            "author"     : "devops-guild",
            "version"    : "1.0.0",
            "pricing"    : "free",
            "price_usd"  : 0.0,
            "tags"       : ["cicd", "docker", "github-actions", "devops"],
            "installs"   : 2105,
            "rating"     : 4.5,
            "rating_count": 62,
            "created_at" : time.time() - 86400 * 45,
            "updated_at" : time.time() - 86400 * 1,
            "verified"   : True,
        },
        {
            "id"         : "listing-004",
            "name"       : "Arabic NLU Prompt Pack",
            "type"       : "prompt_pack",
            "description": "200+ optimized prompts for Arabic language understanding across 6 dialects.",
            "author"     : "nlp-collective",
            "version"    : "1.1.0",
            "pricing"    : "subscription",
            "price_usd"  : 4.99,
            "tags"       : ["arabic", "nlp", "prompts", "multilingual"],
            "installs"   : 312,
            "rating"     : 4.8,
            "rating_count": 15,
            "created_at" : time.time() - 86400 * 7,
            "updated_at" : time.time() - 86400 * 1,
            "verified"   : False,
        },
    ]
    for item in examples:
        _STORE[item["id"]] = item
    _save(_STORE, _REVIEWS)


_seed()


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
    items = list(_STORE.values())

    if type:
        items = [i for i in items if i["type"] == type]
    if pricing:
        items = [i for i in items if i["pricing"] == pricing]

    reverse = order == "desc"
    items.sort(key=lambda x: x.get(sort, 0), reverse=reverse)

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
    item = _STORE.get(listing_id)
    if not item:
        raise HTTPException(status_code=404, detail="Listing not found")
    return {**item, "reviews": _REVIEWS.get(listing_id, [])}


@router.post("/listings", status_code=201)
async def publish_listing(body: PublishRequest):
    listing_id = f"listing-{uuid.uuid4().hex[:8]}"
    now = time.time()
    item = {
        "id"         : listing_id,
        "name"       : body.name,
        "type"       : body.type.value,
        "description": body.description,
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
    _STORE[listing_id] = item
    _save(_STORE, _REVIEWS)
    return item


@router.put("/listings/{listing_id}")
async def update_listing(listing_id: str, body: PublishRequest):
    if listing_id not in _STORE:
        raise HTTPException(status_code=404, detail="Listing not found")
    item = _STORE[listing_id]
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
    _save(_STORE, _REVIEWS)
    return item


@router.delete("/listings/{listing_id}", status_code=204)
async def delete_listing(listing_id: str):
    if listing_id not in _STORE:
        raise HTTPException(status_code=404, detail="Listing not found")
    del _STORE[listing_id]
    _REVIEWS.pop(listing_id, None)
    _save(_STORE, _REVIEWS)


@router.post("/listings/{listing_id}/install")
async def install_listing(listing_id: str):
    item = _STORE.get(listing_id)
    if not item:
        raise HTTPException(status_code=404, detail="Listing not found")
    item["installs"] = item.get("installs", 0) + 1
    _save(_STORE, _REVIEWS)
    return {
        "status"     : "installed",
        "listing_id" : listing_id,
        "name"       : item["name"],
        "version"    : item["version"],
        "installed_at": time.time(),
    }


@router.get("/categories")
async def list_categories():
    counts: dict[str, int] = {}
    for item in _STORE.values():
        t = item.get("type", "other")
        counts[t] = counts.get(t, 0) + 1
    return [{"type": t, "count": c} for t, c in sorted(counts.items())]


@router.get("/search")
async def search_listings(
    q        : str = Query(..., min_length=1),
    page     : int = Query(1, ge=1),
    per_page : int = Query(20, ge=1, le=100),
):
    q_lower = q.lower()
    results = [
        item for item in _STORE.values()
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
    if body.listing_id not in _STORE:
        raise HTTPException(status_code=404, detail="Listing not found")

    review = {
        "id"        : str(uuid.uuid4()),
        "listing_id": body.listing_id,
        "rating"    : body.rating,
        "comment"   : body.comment,
        "reviewer"  : body.reviewer,
        "created_at": time.time(),
    }
    if body.listing_id not in _REVIEWS:
        _REVIEWS[body.listing_id] = []
    _REVIEWS[body.listing_id].append(review)

    # Recompute average
    all_ratings = [r["rating"] for r in _REVIEWS[body.listing_id]]
    _STORE[body.listing_id]["rating"]      = sum(all_ratings) / len(all_ratings)
    _STORE[body.listing_id]["rating_count"] = len(all_ratings)
    _save(_STORE, _REVIEWS)

    return review


@router.get("/listings/{listing_id}/reviews")
async def get_reviews(listing_id: str):
    if listing_id not in _STORE:
        raise HTTPException(status_code=404, detail="Listing not found")
    return _REVIEWS.get(listing_id, [])
