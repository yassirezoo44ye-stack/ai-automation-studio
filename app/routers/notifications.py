"""
Notification Center — personal notification inbox for the authenticated
user (like /api/keys' personal keys, not an org-RBAC resource: your own
notifications are inherently yours to read, so no permission check beyond
authentication is needed; every mutation is additionally scoped to
user_id at the query level in NotificationService).

GET    /api/notifications                 list (filters + cursor pagination)
GET    /api/notifications/unread-count
POST   /api/notifications/{id}/read
POST   /api/notifications/read-all
POST   /api/notifications/{id}/archive
DELETE /api/notifications/{id}
GET    /api/notifications/preferences
PUT    /api/notifications/preferences
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.notifications import CATEGORIES, get_notification_service
from app.routers.auth_users import get_current_user

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("")
async def list_notifications(
    unread_only: bool = False,
    category: Optional[str] = None,
    severity: Optional[str] = None,
    search: Optional[str] = None,
    include_archived: bool = False,
    before: Optional[str] = None,
    limit: int = 30,
    user: dict = Depends(get_current_user),
):
    if category and category not in CATEGORIES:
        raise HTTPException(400, f"Unknown category {category!r}")
    svc = get_notification_service()
    items = await svc.list(
        user_id=user["id"], unread_only=unread_only, category=category, severity=severity,
        search=search, include_archived=include_archived, before=before, limit=limit,
    )
    return {"notifications": items, "has_more": len(items) == max(1, min(limit, 200))}


@router.get("/unread-count")
async def unread_count(user: dict = Depends(get_current_user)):
    svc = get_notification_service()
    return {"unread_count": await svc.unread_count(user_id=user["id"])}


@router.post("/read-all")
async def mark_all_read(user: dict = Depends(get_current_user)):
    svc = get_notification_service()
    return {"marked_read": await svc.mark_all_read(user_id=user["id"])}


@router.post("/{notification_id}/read")
async def mark_read(notification_id: str, user: dict = Depends(get_current_user)):
    svc = get_notification_service()
    if not await svc.mark_read(user_id=user["id"], notification_id=notification_id):
        raise HTTPException(404, "Notification not found")
    return {"ok": True}


@router.post("/{notification_id}/archive")
async def archive_notification(notification_id: str, user: dict = Depends(get_current_user)):
    svc = get_notification_service()
    if not await svc.archive(user_id=user["id"], notification_id=notification_id):
        raise HTTPException(404, "Notification not found")
    return {"ok": True}


@router.delete("/{notification_id}", status_code=204)
async def delete_notification(notification_id: str, user: dict = Depends(get_current_user)):
    svc = get_notification_service()
    if not await svc.delete(user_id=user["id"], notification_id=notification_id):
        raise HTTPException(404, "Notification not found")


class PreferencesRequest(BaseModel):
    muted_categories: list[str]


@router.get("/preferences")
async def get_preferences(user: dict = Depends(get_current_user)):
    svc = get_notification_service()
    return {"muted_categories": await svc.get_preferences(user_id=user["id"])}


@router.put("/preferences")
async def set_preferences(body: PreferencesRequest, user: dict = Depends(get_current_user)):
    bad = set(body.muted_categories) - set(CATEGORIES)
    if bad:
        raise HTTPException(400, f"Unknown categories: {bad}")
    svc = get_notification_service()
    return {"muted_categories": await svc.set_preferences(
        user_id=user["id"], muted_categories=body.muted_categories,
    )}
