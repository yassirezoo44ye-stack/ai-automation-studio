"""
Organization management API — Layer 12 (Enterprise multi-tenancy).

POST   /api/orgs                                  create organization
GET    /api/orgs                                  list my organizations
GET    /api/orgs/{org_id}                         organization details
DELETE /api/orgs/{org_id}                         soft-delete (owner only)
GET    /api/orgs/{org_id}/members                 list members
PATCH  /api/orgs/{org_id}/members/{user_id}       change member role
DELETE /api/orgs/{org_id}/members/{user_id}       remove member
POST   /api/orgs/{org_id}/invitations             invite by email
POST   /api/orgs/invitations/accept               accept an invitation token
GET    /api/orgs/{org_id}/activity                activity log
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field

from app.routers.auth_users import get_current_user
from app.tenancy import (
    OrgContext, TenancyError, get_tenancy_service, org_context, require_permission,
)

router = APIRouter(prefix="/api/orgs", tags=["organizations"])


def _raise(e: TenancyError):
    raise HTTPException(e.status, str(e))


# ── Models ────────────────────────────────────────────────────────────────────

class CreateOrgRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    kind: str = Field(default="organization", pattern="^(personal|organization|enterprise)$")


class InviteRequest(BaseModel):
    email: EmailStr
    role: str = Field(default="viewer", pattern="^(admin|manager|developer|operator|viewer)$")
    ttl_hours: int = Field(default=72, ge=1, le=720)


class AcceptInviteRequest(BaseModel):
    token: str = Field(min_length=16)


class ChangeRoleRequest(BaseModel):
    role: str = Field(pattern="^(owner|admin|manager|developer|operator|viewer)$")


def _org_out(o: dict) -> dict:
    return {
        "id": str(o["id"]), "name": o["name"], "slug": o["slug"],
        "kind": o["kind"], "plan": o["plan"],
        "created_at": o["created_at"].isoformat(),
        **({"my_role": o["my_role"]} if "my_role" in o else {}),
    }


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("", status_code=201)
async def create_org(body: CreateOrgRequest, user: dict = Depends(get_current_user)):
    svc = get_tenancy_service()
    try:
        org = await svc.create_organization(name=body.name, kind=body.kind, creator_id=user["id"])
    except TenancyError as e:
        _raise(e)
    return _org_out(org)


@router.get("")
async def list_my_orgs(user: dict = Depends(get_current_user)):
    svc = get_tenancy_service()
    orgs = await svc.list_organizations_for_user(user["id"])
    return {"organizations": [_org_out(o) for o in orgs]}


@router.get("/{org_id}")
async def get_org(ctx: OrgContext = Depends(org_context)):
    svc = get_tenancy_service()
    org = await svc.get_organization(ctx.org_id)
    if org is None:
        raise HTTPException(404, "Organization not found")
    return {**_org_out(org), "my_role": ctx.role}


@router.delete("/{org_id}", status_code=204)
async def delete_org(ctx: OrgContext = Depends(org_context)):
    svc = get_tenancy_service()
    try:
        await svc.soft_delete_organization(ctx.org_id, ctx.user_id)
    except TenancyError as e:
        _raise(e)


@router.get("/{org_id}/members")
async def list_members(ctx: OrgContext = Depends(require_permission("members", "read"))):
    svc = get_tenancy_service()
    members = await svc.list_members(ctx.org_id)
    return {"members": [
        {"user_id": str(m["user_id"]), "email": m["email"], "name": m["name"],
         "role": m["role"], "joined_at": m["created_at"].isoformat()}
        for m in members
    ]}


@router.patch("/{org_id}/members/{member_user_id}")
async def change_role(
    member_user_id: str,
    body: ChangeRoleRequest,
    ctx: OrgContext = Depends(org_context),
):
    svc = get_tenancy_service()
    try:
        await svc.change_member_role(
            ctx.org_id, actor_id=ctx.user_id,
            member_user_id=member_user_id, new_role=body.role,
        )
    except TenancyError as e:
        _raise(e)
    return {"status": "updated", "role": body.role}


@router.delete("/{org_id}/members/{member_user_id}", status_code=204)
async def remove_member(member_user_id: str, ctx: OrgContext = Depends(org_context)):
    svc = get_tenancy_service()
    try:
        await svc.remove_member(ctx.org_id, actor_id=ctx.user_id, member_user_id=member_user_id)
    except TenancyError as e:
        _raise(e)


@router.post("/{org_id}/invitations", status_code=201)
async def invite(body: InviteRequest, ctx: OrgContext = Depends(org_context)):
    svc = get_tenancy_service()
    try:
        inv = await svc.create_invitation(
            ctx.org_id, actor_id=ctx.user_id,
            email=body.email, role=body.role, ttl_hours=body.ttl_hours,
        )
    except TenancyError as e:
        _raise(e)
    return {
        "id": str(inv["id"]), "email": inv["email"], "role": inv["role"],
        "token": inv["token"],  # delivered out-of-band (email) in production
        "expires_at": inv["expires_at"].isoformat(),
    }


@router.post("/invitations/accept")
async def accept_invite(body: AcceptInviteRequest, user: dict = Depends(get_current_user)):
    svc = get_tenancy_service()
    try:
        result = await svc.accept_invitation(
            token=body.token, user_id=user["id"], user_email=user["email"],
        )
    except TenancyError as e:
        _raise(e)
    return result


@router.get("/{org_id}/activity")
async def activity(
    limit: int = 100,
    ctx: OrgContext = Depends(require_permission("activity", "read")),
):
    svc = get_tenancy_service()
    rows = await svc.list_activity(ctx.org_id, limit=limit)
    return {"activity": [
        {"action": r["action"], "resource": r["resource"], "resource_id": r["resource_id"],
         "actor_id": str(r["actor_id"]) if r["actor_id"] else None,
         "created_at": r["created_at"].isoformat()}
        for r in rows
    ]}
