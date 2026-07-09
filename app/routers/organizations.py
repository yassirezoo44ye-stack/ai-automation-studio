"""
Organization management API — Layer 12 (Enterprise multi-tenancy).

POST   /api/orgs                                  create organization
GET    /api/orgs                                  list my organizations
GET    /api/orgs/{org_id}                         organization details
PATCH  /api/orgs/{org_id}                         rename organization
GET    /api/orgs/{org_id}/settings                get organization settings
PATCH  /api/orgs/{org_id}/settings                merge-patch organization settings
DELETE /api/orgs/{org_id}                         soft-delete (owner only)
GET    /api/orgs/{org_id}/members                 list members
PATCH  /api/orgs/{org_id}/members/{user_id}       change member role
DELETE /api/orgs/{org_id}/members/{user_id}       remove member
POST   /api/orgs/{org_id}/invitations             invite by email
POST   /api/orgs/invitations/accept               accept an invitation token
GET    /api/orgs/{org_id}/activity                activity log
POST   /api/orgs/{org_id}/teams                   create team
GET    /api/orgs/{org_id}/teams                   list teams
GET    /api/orgs/{org_id}/teams/{team_id}         team details
PATCH  /api/orgs/{org_id}/teams/{team_id}         update team
DELETE /api/orgs/{org_id}/teams/{team_id}         delete team
POST   /api/orgs/{org_id}/teams/{team_id}/members         add team member
GET    /api/orgs/{org_id}/teams/{team_id}/members         list team members
DELETE /api/orgs/{org_id}/teams/{team_id}/members/{user_id} remove team member
POST   /api/orgs/{org_id}/api-keys                create an org-scoped API key
GET    /api/orgs/{org_id}/api-keys                list org-scoped API keys
DELETE /api/orgs/{org_id}/api-keys/{key_id}       revoke an org-scoped API key
GET    /api/orgs/{org_id}/invitations             list pending invitations
DELETE /api/orgs/{org_id}/invitations/{invitation_id} revoke a pending invitation
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field

from app.routers.auth_users import _client_ip, get_current_user
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


class CreateTeamRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: Optional[str] = Field(default=None, max_length=2000)


class UpdateTeamRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    description: Optional[str] = Field(default=None, max_length=2000)


class AddTeamMemberRequest(BaseModel):
    user_id: str


class CreateApiKeyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    scopes: list[str] = Field(default_factory=lambda: ["read"])
    expires_in_days: Optional[int] = Field(default=None, ge=1, le=3650)


class UpdateOrgRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=120)


def _org_out(o: dict) -> dict:
    import json as _json
    settings = o.get("settings")
    if isinstance(settings, str):
        settings = _json.loads(settings)
    return {
        "id": str(o["id"]), "name": o["name"], "slug": o["slug"],
        "kind": o["kind"], "plan": o["plan"], "settings": settings or {},
        "created_at": o["created_at"].isoformat(),
        **({"my_role": o["my_role"]} if "my_role" in o else {}),
    }


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("", status_code=201)
async def create_org(body: CreateOrgRequest, request: Request, user: dict = Depends(get_current_user)):
    svc = get_tenancy_service()
    try:
        org = await svc.create_organization(
            name=body.name, kind=body.kind, creator_id=user["id"], ip_address=_client_ip(request),
        )
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


@router.patch("/{org_id}")
async def update_org(
    body: UpdateOrgRequest,
    request: Request,
    ctx: OrgContext = Depends(require_permission("organization", "update")),
):
    svc = get_tenancy_service()
    try:
        org = await svc.update_organization(
            ctx.org_id, actor_id=ctx.user_id, name=body.name, ip_address=_client_ip(request),
        )
    except TenancyError as e:
        _raise(e)
    return _org_out(org)


@router.get("/{org_id}/settings")
async def get_settings(ctx: OrgContext = Depends(require_permission("organization", "read"))):
    svc = get_tenancy_service()
    try:
        settings = await svc.get_settings(ctx.org_id)
    except TenancyError as e:
        _raise(e)
    return {"settings": settings}


@router.patch("/{org_id}/settings")
async def update_settings(
    request: Request,
    patch: dict[str, Any] = Body(...),
    ctx: OrgContext = Depends(require_permission("organization", "update")),
):
    svc = get_tenancy_service()
    try:
        settings = await svc.update_settings(
            ctx.org_id, actor_id=ctx.user_id, patch=patch, ip_address=_client_ip(request),
        )
    except TenancyError as e:
        _raise(e)
    return {"settings": settings}


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
    request: Request,
    ctx: OrgContext = Depends(org_context),
):
    svc = get_tenancy_service()
    try:
        await svc.change_member_role(
            ctx.org_id, actor_id=ctx.user_id,
            member_user_id=member_user_id, new_role=body.role,
            ip_address=_client_ip(request),
        )
    except TenancyError as e:
        _raise(e)
    return {"status": "updated", "role": body.role}


@router.delete("/{org_id}/members/{member_user_id}", status_code=204)
async def remove_member(member_user_id: str, request: Request, ctx: OrgContext = Depends(org_context)):
    svc = get_tenancy_service()
    try:
        await svc.remove_member(
            ctx.org_id, actor_id=ctx.user_id, member_user_id=member_user_id,
            ip_address=_client_ip(request),
        )
    except TenancyError as e:
        _raise(e)


@router.post("/{org_id}/invitations", status_code=201)
async def invite(body: InviteRequest, request: Request, ctx: OrgContext = Depends(org_context)):
    svc = get_tenancy_service()
    try:
        inv = await svc.create_invitation(
            ctx.org_id, actor_id=ctx.user_id,
            email=body.email, role=body.role, ttl_hours=body.ttl_hours,
            ip_address=_client_ip(request),
        )
    except TenancyError as e:
        _raise(e)
    return {
        "id": str(inv["id"]), "email": inv["email"], "role": inv["role"],
        "token": inv["token"],  # delivered out-of-band (email) in production
        "expires_at": inv["expires_at"].isoformat(),
    }


@router.get("/{org_id}/invitations")
async def list_invitations(
    status: str = "pending",
    ctx: OrgContext = Depends(require_permission("members", "read")),
):
    svc = get_tenancy_service()
    invs = await svc.list_invitations(ctx.org_id, status=status)
    return {"invitations": [
        {"id": str(i["id"]), "email": i["email"], "role": i["role"], "status": i["status"],
         "expires_at": i["expires_at"].isoformat(), "created_at": i["created_at"].isoformat()}
        for i in invs
    ]}


@router.delete("/{org_id}/invitations/{invitation_id}", status_code=204)
async def revoke_invitation(
    invitation_id: str,
    ctx: OrgContext = Depends(org_context),
):
    svc = get_tenancy_service()
    try:
        await svc.revoke_invitation(ctx.org_id, invitation_id, actor_id=ctx.user_id)
    except TenancyError as e:
        _raise(e)


@router.post("/invitations/accept")
async def accept_invite(body: AcceptInviteRequest, request: Request, user: dict = Depends(get_current_user)):
    svc = get_tenancy_service()
    try:
        result = await svc.accept_invitation(
            token=body.token, user_id=user["id"], user_email=user["email"],
            ip_address=_client_ip(request),
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


# ── Teams ─────────────────────────────────────────────────────────────────────

def _team_out(t: dict) -> dict:
    return {
        "id": str(t["id"]), "organization_id": str(t["organization_id"]),
        "name": t["name"], "description": t["description"],
        "created_at": t["created_at"].isoformat(),
        "updated_at": t["updated_at"].isoformat(),
    }


@router.post("/{org_id}/teams", status_code=201)
async def create_team(
    body: CreateTeamRequest,
    ctx: OrgContext = Depends(require_permission("teams", "manage")),
):
    svc = get_tenancy_service()
    try:
        team = await svc.create_team(
            ctx.org_id, actor_id=ctx.user_id, name=body.name, description=body.description,
        )
    except TenancyError as e:
        _raise(e)
    return _team_out(team)


@router.get("/{org_id}/teams")
async def list_teams(ctx: OrgContext = Depends(require_permission("teams", "read"))):
    svc = get_tenancy_service()
    teams = await svc.list_teams(ctx.org_id)
    return {"teams": [_team_out(t) for t in teams]}


@router.get("/{org_id}/teams/{team_id}")
async def get_team(team_id: str, ctx: OrgContext = Depends(require_permission("teams", "read"))):
    svc = get_tenancy_service()
    team = await svc.get_team(ctx.org_id, team_id)
    if team is None:
        raise HTTPException(404, "Team not found")
    return _team_out(team)


@router.patch("/{org_id}/teams/{team_id}")
async def update_team(
    team_id: str,
    body: UpdateTeamRequest,
    ctx: OrgContext = Depends(require_permission("teams", "manage")),
):
    svc = get_tenancy_service()
    try:
        team = await svc.update_team(
            ctx.org_id, team_id, actor_id=ctx.user_id,
            name=body.name, description=body.description,
        )
    except TenancyError as e:
        _raise(e)
    return _team_out(team)


@router.delete("/{org_id}/teams/{team_id}", status_code=204)
async def delete_team(team_id: str, ctx: OrgContext = Depends(require_permission("teams", "manage"))):
    svc = get_tenancy_service()
    try:
        await svc.delete_team(ctx.org_id, team_id, actor_id=ctx.user_id)
    except TenancyError as e:
        _raise(e)


@router.post("/{org_id}/teams/{team_id}/members", status_code=201)
async def add_team_member(
    team_id: str,
    body: AddTeamMemberRequest,
    ctx: OrgContext = Depends(require_permission("teams", "manage")),
):
    svc = get_tenancy_service()
    try:
        member = await svc.add_team_member(
            ctx.org_id, team_id, actor_id=ctx.user_id, member_user_id=body.user_id,
        )
    except TenancyError as e:
        _raise(e)
    return {"team_id": str(member["team_id"]), "user_id": str(member["user_id"])}


@router.get("/{org_id}/teams/{team_id}/members")
async def list_team_members(
    team_id: str, ctx: OrgContext = Depends(require_permission("teams", "read")),
):
    svc = get_tenancy_service()
    members = await svc.list_team_members(ctx.org_id, team_id)
    return {"members": [
        {"user_id": str(m["user_id"]), "email": m["email"], "name": m["name"],
         "joined_at": m["created_at"].isoformat()}
        for m in members
    ]}


@router.delete("/{org_id}/teams/{team_id}/members/{member_user_id}", status_code=204)
async def remove_team_member(
    team_id: str, member_user_id: str,
    ctx: OrgContext = Depends(require_permission("teams", "manage")),
):
    svc = get_tenancy_service()
    try:
        await svc.remove_team_member(
            ctx.org_id, team_id, actor_id=ctx.user_id, member_user_id=member_user_id,
        )
    except TenancyError as e:
        _raise(e)


# ── API Keys (org-scoped) ────────────────────────────────────────────────────

@router.post("/{org_id}/api-keys", status_code=201)
async def create_org_api_key(
    body: CreateApiKeyRequest,
    ctx: OrgContext = Depends(require_permission("api_keys", "manage")),
):
    from app.core.api_keys import create_api_key
    valid_scopes = {"read", "write", "admin", "agents", "marketplace"}
    bad = set(body.scopes) - valid_scopes
    if bad:
        raise HTTPException(400, f"Unknown scopes: {bad}. Valid: {valid_scopes}")
    raw, rec = await create_api_key(
        name=body.name, scopes=body.scopes, owner_id=ctx.user_id,
        expires_in_days=body.expires_in_days,
        organization_id=ctx.org_id, actor_id=ctx.user_id,
    )
    return {
        "api_key": raw,  # shown ONCE
        "key_id": rec.key_id, "name": rec.name, "scopes": rec.scopes,
        "organization_id": rec.organization_id, "expires_at": rec.expires_at,
        "warning": "Store this key securely — it will not be shown again.",
    }


@router.get("/{org_id}/api-keys")
async def list_org_api_keys(ctx: OrgContext = Depends(require_permission("api_keys", "manage"))):
    from app.core.api_keys import list_api_keys
    keys = await list_api_keys(organization_id=ctx.org_id)
    return {"keys": [k.to_dict(redact=True) for k in keys]}


@router.delete("/{org_id}/api-keys/{key_id}", status_code=204)
async def revoke_org_api_key(
    key_id: str, ctx: OrgContext = Depends(require_permission("api_keys", "manage")),
):
    from app.core.api_keys import revoke_api_key
    if not await revoke_api_key(key_id, organization_id=ctx.org_id):
        raise HTTPException(404, f"Key {key_id!r} not found")
