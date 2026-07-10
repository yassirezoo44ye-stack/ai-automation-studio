"""
Marketplace API — Layer 11 (Production Marketplace).

Endpoints:
  GET    /marketplace/listings                                 list (paginated, filterable, visibility-aware)
  GET    /marketplace/listings/{id}                             item detail
  POST   /marketplace/listings                                  publish new item        [marketplace:publish]
  PUT    /marketplace/listings/{id}                              update item             [marketplace:publish + ownership]
  DELETE /marketplace/listings/{id}                              remove item (soft)      [marketplace:manage + ownership]
  POST   /marketplace/listings/{id}/install                      install                 [org member]
  POST   /marketplace/listings/{id}/uninstall                    uninstall               [org member]
  POST   /marketplace/listings/{id}/rollback                     rollback to a version   [marketplace:install]
  GET    /marketplace/listings/{id}/versions                     version history
  GET    /marketplace/listings/{id}/versions/{version}/changelog structured changelog entries
  GET    /marketplace/listings/{id}/dependencies                 dependency list
  GET    /marketplace/listings/{id}/assets                       asset metadata (no raw content)
  GET    /marketplace/listings/{id}/downloads                    download stats          [marketplace:manage + ownership]
  GET    /marketplace/categories                                 categories with counts
  GET    /marketplace/search                                     full-text search
  POST   /marketplace/reviews                                    submit review           [authenticated user]
  GET    /marketplace/listings/{id}/reviews                      list reviews
  GET    /marketplace/publishers/{org_id}                        publisher profile
  POST   /api/admin/marketplace/publishers/{id}/verify            verify a publisher      [platform admin API key]

Item types: agent | plugin | theme | template | prompt_pack | workflow | dataset | model

Persistence: PostgreSQL (marketplace_items / versions / reviews / installs /
categories / publishers / dependencies / assets / changelog / downloads)
with a JSON-file fallback when no database pool is configured — see
app/marketplace/store.py. The API shape is identical on both backends.

Every mutating endpoint requires authentication. Publishing sets real
ownership (`owner_organization_id`) on every new listing — updates/deletes
of an owned listing are additionally restricted to that owning org (closing
a gap where any org with the `marketplace:publish`/`manage` RBAC permission
could edit or delete any listing, not just its own). The 4 pre-existing seed
listings have no owner and remain editable by any permitted org, preserving
today's behavior for them. Installs route through InstallationPipeline (see
app/marketplace/installer.py) — the 9-stage validate/authorize/resolve-deps/
verify-integrity/install/register/emit/rollback engine. Read endpoints stay
public for `visibility='public'` listings; a caller's own org's private/
internal listings are additionally visible when X-Organization-Id identifies
a verified membership (see app.tenancy.optional_org_id).
"""
from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.billing import QuotaExceeded
from app.core.api_keys import ApiKeyRecord, require_api_key
from app.marketplace import (
    get_marketplace_store, get_category_service, get_publisher_service,
    get_dependency_service, get_asset_service, get_changelog_service, get_download_service,
    get_installation_pipeline,
    ItemNotFoundError, MarketplacePermissionError, PlanFeatureNotEnabledError,
    IntegrityError, NotInstalledError, VersionNotFoundError,
)
from app.marketplace.dependencies import (
    MissingDependencyError, CircularDependencyError, VersionConstraintError,
)
from app.routers.auth_users import get_current_user
from app.tenancy import OrgContext, org_context, require_permission, optional_org_id

router = APIRouter(prefix="/marketplace", tags=["marketplace"])

# Separate router for the one platform-admin endpoint — it lives outside the
# /marketplace prefix (matches how POST /api/admin/plans/{id} is registered
# in the billing phase), so it needs its own APIRouter with no prefix.
admin_router = APIRouter(tags=["marketplace-admin"])


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


class Visibility(str, Enum):
    PUBLIC   = "public"
    PRIVATE  = "private"
    INTERNAL = "internal"


# ── Schemas ───────────────────────────────────────────────────────────────────

class DependencySpec(BaseModel):
    depends_on_item_id : str
    version_constraint  : str = "*"
    optional            : bool = False


class AssetSpec(BaseModel):
    content         : Optional[str] = None
    external_url    : Optional[str] = None
    checksum_sha256 : Optional[str] = None


class ChangelogEntrySpec(BaseModel):
    change_type : str = Field(..., pattern="^(added|changed|fixed|removed|security)$")
    description : str


class PublishRequest(BaseModel):
    name              : str = Field(..., min_length=3, max_length=120)
    type              : ItemType
    description       : str = Field(..., min_length=10, max_length=2000)
    version           : str = "1.0.0"
    pricing           : PricingModel = PricingModel.FREE
    price_usd         : float = Field(0.0, ge=0)
    tags              : list[str] = Field(default_factory=list)
    metadata          : dict = Field(default_factory=dict)
    visibility        : Visibility = Visibility.PUBLIC
    dependencies      : list[DependencySpec] = Field(default_factory=list)
    assets            : list[AssetSpec] = Field(default_factory=list)
    changelog_entries : list[ChangelogEntrySpec] = Field(default_factory=list)


class ReviewRequest(BaseModel):
    listing_id : str
    rating     : float = Field(..., ge=1, le=5)
    comment    : Optional[str] = None


class RollbackRequest(BaseModel):
    target_version: str


# ── Helpers ───────────────────────────────────────────────────────────────────

def _paginate(items: list, page: int, per_page: int):
    total = len(items)
    start = (page - 1) * per_page
    return items[start : start + per_page], total


def _assert_owns(item: dict, ctx: OrgContext) -> None:
    """A listing with no owner (the 4 pre-existing seed rows, published
    before the ownership model existed) stays editable by any org holding
    the required RBAC permission — zero regression for legacy data. A
    listing WITH an owner may only be modified by that owning org, even by
    an actor who otherwise holds marketplace:publish/manage in their own
    org — RBAC permission alone is not enough once real ownership exists."""
    owner = item.get("owner_organization_id")
    if owner is not None and owner != ctx.org_id:
        raise HTTPException(status_code=403, detail="You do not own this listing")


async def _attach_publish_extras(item_id: str, version: str, body: PublishRequest) -> None:
    """Shared by publish + update: attach dependencies/assets/changelog for
    the version just written. Additive — never removes prior entries."""
    dep_svc = get_dependency_service()
    for dep in body.dependencies:
        await dep_svc.add(
            item_id, dep.depends_on_item_id,
            version_constraint=dep.version_constraint, optional=dep.optional,
        )

    asset_svc = get_asset_service()
    for asset in body.assets:
        await asset_svc.add_asset(
            item_id, version,
            content=asset.content, external_url=asset.external_url,
            checksum_sha256=asset.checksum_sha256,
        )

    if body.changelog_entries:
        store = get_marketplace_store()
        version_row = await store.get_version(item_id, version)
        if version_row is not None:
            await get_changelog_service().add_entries(
                str(version_row["id"]),
                [{"change_type": e.change_type, "description": e.description} for e in body.changelog_entries],
            )


_INSTALL_ERROR_STATUS: dict[type, int] = {
    ItemNotFoundError: 404,
    MarketplacePermissionError: 403,
    PlanFeatureNotEnabledError: 402,
    QuotaExceeded: 429,
    MissingDependencyError: 409,
    CircularDependencyError: 409,
    VersionConstraintError: 409,
    IntegrityError: 422,
    NotInstalledError: 404,
    VersionNotFoundError: 404,
}


def _raise_install_error(exc: Exception) -> None:
    status = _INSTALL_ERROR_STATUS.get(type(exc), 400)
    raise HTTPException(status_code=status, detail=str(exc))


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/listings")
async def list_listings(
    page     : int = Query(1, ge=1),
    per_page : int = Query(20, ge=1, le=100),
    type     : Optional[str] = None,
    pricing  : Optional[str] = None,
    sort     : str = Query("installs", pattern="^(installs|rating|created_at|price_usd)$"),
    order    : str = Query("desc", pattern="^(asc|desc)$"),
    viewer_org_id: Optional[str] = Depends(optional_org_id),
):
    store = get_marketplace_store()
    items = await store.list_items(viewer_org_id=viewer_org_id)

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
async def get_listing(listing_id: str, viewer_org_id: Optional[str] = Depends(optional_org_id)):
    store = get_marketplace_store()
    item = await store.get_item(listing_id, viewer_org_id=viewer_org_id)
    if not item:
        raise HTTPException(status_code=404, detail="Listing not found")
    reviews = await store.list_reviews(listing_id)
    return {**item, "reviews": reviews}


@router.post("/listings", status_code=201)
async def publish_listing(
    body: PublishRequest,
    ctx: OrgContext = Depends(require_permission("marketplace", "publish")),
):
    store = get_marketplace_store()
    listing_id = f"listing-{uuid.uuid4().hex[:8]}"
    now = time.time()

    from app.tenancy import get_tenancy_service
    org = await get_tenancy_service().get_organization(ctx.org_id)
    publisher = await get_publisher_service().get_or_create_for_org(
        ctx.org_id, (org or {}).get("name") or ctx.user_email,
    )

    item = {
        "id"         : listing_id,
        "name"       : body.name,
        "type"       : body.type.value,
        "description": body.description,
        "author"     : ctx.user_email,
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
        "visibility" : body.visibility.value,
        "owner_organization_id": ctx.org_id,
        "created_by" : ctx.user_id,
    }
    await store.upsert_item(item)
    await get_publisher_service().link_item(listing_id, publisher["id"])
    await _attach_publish_extras(listing_id, body.version, body)
    try:
        from app.core.events import get_event_bus
        await get_event_bus().publish("marketplace.published",
                                      {"listing_id": listing_id, "name": body.name},
                                      organization_id=ctx.org_id)
    except Exception:
        pass
    item["publisher_id"] = publisher["id"]
    return item


@router.put("/listings/{listing_id}")
async def update_listing(
    listing_id: str, body: PublishRequest,
    ctx: OrgContext = Depends(require_permission("marketplace", "publish")),
):
    store = get_marketplace_store()
    item = await store.get_item(listing_id, viewer_org_id=ctx.org_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    _assert_owns(item, ctx)
    item.update({
        "name"       : body.name,
        "description": body.description,
        "version"    : body.version,
        "pricing"    : body.pricing.value,
        "price_usd"  : body.price_usd,
        "tags"       : body.tags,
        "metadata"   : body.metadata,
        "visibility" : body.visibility.value,
        "updated_at" : time.time(),
    })
    await store.upsert_item(item)
    await _attach_publish_extras(listing_id, body.version, body)
    return item


@router.delete("/listings/{listing_id}", status_code=204)
async def delete_listing(
    listing_id: str,
    ctx: OrgContext = Depends(require_permission("marketplace", "manage")),
):
    store = get_marketplace_store()
    item = await store.get_item(listing_id, viewer_org_id=ctx.org_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    _assert_owns(item, ctx)
    await store.delete_item(listing_id)


@router.post("/listings/{listing_id}/install")
async def install_listing(listing_id: str, ctx: OrgContext = Depends(org_context)):
    try:
        item = await get_installation_pipeline().install(
            listing_id, org_id=ctx.org_id, actor_id=ctx.user_id, actor_email=ctx.user_email,
        )
    except tuple(_INSTALL_ERROR_STATUS.keys()) as exc:
        _raise_install_error(exc)
    return {
        "status"      : "installed",
        "listing_id"  : listing_id,
        "name"        : item["name"],
        "version"     : item["version"],
        "installed_at": time.time(),
    }


@router.post("/listings/{listing_id}/uninstall")
async def uninstall_listing(listing_id: str, ctx: OrgContext = Depends(org_context)):
    try:
        await get_installation_pipeline().uninstall(listing_id, org_id=ctx.org_id, actor_id=ctx.user_id)
    except tuple(_INSTALL_ERROR_STATUS.keys()) as exc:
        _raise_install_error(exc)
    return {"status": "uninstalled", "listing_id": listing_id}


@router.post("/listings/{listing_id}/rollback")
async def rollback_listing(
    listing_id: str, body: RollbackRequest,
    ctx: OrgContext = Depends(require_permission("marketplace", "install")),
):
    try:
        item = await get_installation_pipeline().rollback_version(
            listing_id, org_id=ctx.org_id, actor_id=ctx.user_id, actor_email=ctx.user_email,
            target_version=body.target_version,
        )
    except tuple(_INSTALL_ERROR_STATUS.keys()) as exc:
        _raise_install_error(exc)
    return {
        "status"      : "rolled_back",
        "listing_id"  : listing_id,
        "version"     : item["version"],
        "installed_at": time.time(),
    }


@router.get("/listings/{listing_id}/versions")
async def get_versions(listing_id: str, viewer_org_id: Optional[str] = Depends(optional_org_id)):
    store = get_marketplace_store()
    if await store.get_item(listing_id, viewer_org_id=viewer_org_id) is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    return await store.list_versions(listing_id)


@router.get("/listings/{listing_id}/versions/{version}/changelog")
async def get_version_changelog(
    listing_id: str, version: str, viewer_org_id: Optional[str] = Depends(optional_org_id),
):
    store = get_marketplace_store()
    # get_version() itself has no visibility check (it queries
    # marketplace_versions directly, not marketplace_items) — gate on the
    # parent listing's visibility first so a private listing's changelog
    # can't be read by guessing listing_id + version.
    if await store.get_item(listing_id, viewer_org_id=viewer_org_id) is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    version_row = await store.get_version(listing_id, version)
    if version_row is None:
        raise HTTPException(status_code=404, detail="Version not found")
    return await get_changelog_service().list_for_version(str(version_row["id"]))


@router.get("/listings/{listing_id}/dependencies")
async def get_dependencies(listing_id: str, viewer_org_id: Optional[str] = Depends(optional_org_id)):
    store = get_marketplace_store()
    if await store.get_item(listing_id, viewer_org_id=viewer_org_id) is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    return await get_dependency_service().list_for_item(listing_id)


@router.get("/listings/{listing_id}/assets")
async def get_assets(
    listing_id: str, version: Optional[str] = None,
    viewer_org_id: Optional[str] = Depends(optional_org_id),
):
    store = get_marketplace_store()
    if await store.get_item(listing_id) is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    assets = await get_asset_service().get_assets(listing_id, version)
    try:
        await get_download_service().record_download(listing_id, version, org_id=viewer_org_id)
    except Exception:
        pass
    # Metadata only — raw content/external_url is not exposed here; the
    # actual payload is delivered through the install pipeline.
    return [
        {k: v for k, v in a.items() if k not in ("content", "external_url")}
        for a in assets
    ]


@router.get("/listings/{listing_id}/downloads")
async def get_download_stats(
    listing_id: str,
    ctx: OrgContext = Depends(require_permission("marketplace", "manage")),
):
    store = get_marketplace_store()
    item = await store.get_item(listing_id, viewer_org_id=ctx.org_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    _assert_owns(item, ctx)
    return await get_download_service().stats_for_item(listing_id)


@router.get("/categories")
async def list_categories():
    return await get_category_service().list_categories()


@router.get("/search")
async def search_listings(
    q        : str = Query(..., min_length=1),
    page     : int = Query(1, ge=1),
    per_page : int = Query(20, ge=1, le=100),
    viewer_org_id: Optional[str] = Depends(optional_org_id),
):
    store = get_marketplace_store()
    q_lower = q.lower()
    results = [
        item for item in await store.list_items(viewer_org_id=viewer_org_id)
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
async def submit_review(body: ReviewRequest, user: dict = Depends(get_current_user)):
    store = get_marketplace_store()
    if await store.get_item(body.listing_id) is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    review = {
        "id"        : str(uuid.uuid4()),
        "listing_id": body.listing_id,
        "rating"    : body.rating,
        "comment"   : body.comment,
        "reviewer"  : user["email"],
        "created_at": time.time(),
    }
    return await store.add_review(review)


@router.get("/listings/{listing_id}/reviews")
async def get_reviews(listing_id: str):
    store = get_marketplace_store()
    if await store.get_item(listing_id) is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    return await store.list_reviews(listing_id)


@router.get("/publishers/{org_id}")
async def get_publisher_profile(org_id: str):
    publisher = await get_publisher_service().get_by_org(org_id)
    if publisher is None:
        raise HTTPException(status_code=404, detail="Publisher not found")
    store = get_marketplace_store()
    items = [i for i in await store.list_items() if i.get("owner_organization_id") == org_id]
    return {**publisher, "item_count": len(items)}


@admin_router.post("/api/admin/marketplace/publishers/{publisher_id}/verify")
async def verify_publisher(
    publisher_id: str,
    key: ApiKeyRecord = Depends(require_api_key(scopes=["admin"])),
):
    """Manual admin verification — no automated KYC this phase, matching
    the same require_api_key(scopes=["admin"]) gate used for the billing
    phase's admin-plan-edit endpoint. `admin_actor` stays None: an API
    key's owner_id is a free-text field (default 'system'), not guaranteed
    to be a UUID, matching update_plan()'s actor_id=None precedent."""
    publisher = await get_publisher_service().verify(publisher_id, admin_actor=None)
    if publisher is None:
        raise HTTPException(status_code=404, detail="Publisher not found")
    try:
        from app.core.events import get_event_bus
        await get_event_bus().publish(
            "marketplace.publisher_verified", {"publisher_id": publisher_id},
        )
    except Exception:
        pass
    return publisher
