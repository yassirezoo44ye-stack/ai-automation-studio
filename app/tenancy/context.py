"""
Organization request context.

`OrgContext` is resolved per-request from the `X-Organization-Id` header (or
`org_id` query parameter) plus the authenticated user. Membership is verified
against the database, so a caller can never act inside an organization they
do not belong to.

Usage in routers:

    @router.get("/api/org/{org_id}/things")
    async def list_things(ctx: OrgContext = Depends(org_context)):
        ...  # ctx.org_id, ctx.user_id, ctx.role are trusted

    @router.post(...)
    async def create_thing(
        ctx: OrgContext = Depends(require_permission("things", "create")),
    ): ...
"""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request

from app.tenancy.service import get_tenancy_service


def _get_current_user_dep():
    """Late import — the routers package requires app config at import time,
    which must not be a prerequisite for importing tenancy logic (tests)."""
    from app.routers.auth_users import get_current_user
    return get_current_user


async def _current_user(request: Request) -> dict:
    dep = _get_current_user_dep()
    # Resolve the HTTPBearer credential exactly as auth_users does.
    from fastapi.security import HTTPBearer
    creds = await HTTPBearer(auto_error=False)(request)
    return await dep(creds)


# Public alias used by dependencies below.
get_current_user = _current_user


@dataclass(frozen=True)
class OrgContext:
    org_id: str
    user_id: str
    user_email: str
    role: str


def _extract_org_id(request: Request) -> str | None:
    return (
        request.headers.get("X-Organization-Id")
        or request.query_params.get("org_id")
        or request.path_params.get("org_id")
    )


async def org_context(
    request: Request,
    user: dict = Depends(get_current_user),
) -> OrgContext:
    """Resolve and verify the caller's organization context."""
    org_id = _extract_org_id(request)
    if not org_id:
        raise HTTPException(400, "Missing organization context (X-Organization-Id header)")
    svc = get_tenancy_service()
    role = await svc.get_member_role(org_id, user["id"])
    if role is None:
        # 404 (not 403) so non-members cannot probe which org ids exist.
        raise HTTPException(404, "Organization not found")
    return OrgContext(org_id=org_id, user_id=user["id"], user_email=user["email"], role=role)


def require_permission(resource: str, action: str):
    """Dependency factory: org context + resource-based permission check."""
    async def _dep(ctx: OrgContext = Depends(org_context)) -> OrgContext:
        svc = get_tenancy_service()
        if not await svc.has_permission(ctx.org_id, ctx.user_id, resource=resource, action=action):
            raise HTTPException(403, f"Missing permission: {resource}:{action}")
        return ctx
    return _dep
