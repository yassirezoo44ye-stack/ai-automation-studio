"""
API Key management endpoints — personal (non-org) keys.

POST /api/keys              create a personal key owned by the caller
GET  /api/keys              list your own keys
DELETE /api/keys/{key_id}   revoke one of your own keys

Org-scoped keys (organization_id set, managed by org admins) live under
/api/orgs/{org_id}/api-keys — see app/routers/organizations.py.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.api_keys import (
    create_api_key, revoke_api_key, list_api_keys,
)
from app.routers.auth_users import get_current_user

router = APIRouter(prefix="/api/keys", tags=["api-keys"])


class CreateKeyRequest(BaseModel):
    name            : str
    scopes          : list[str] = ["read"]
    expires_in_days : Optional[int] = None


@router.post("", status_code=201)
async def create_key(body: CreateKeyRequest, user: dict = Depends(get_current_user)):
    """
    Create a new personal API key owned by the caller. The raw key is
    returned ONCE — store it securely.
    """
    if not body.scopes:
        raise HTTPException(400, "At least one scope required")
    valid_scopes = {"read", "write", "admin", "agents", "marketplace"}
    bad = set(body.scopes) - valid_scopes
    if bad:
        raise HTTPException(400, f"Unknown scopes: {bad}. Valid: {valid_scopes}")

    raw, rec = await create_api_key(
        name            = body.name,
        scopes          = body.scopes,
        owner_id        = user["id"],
        expires_in_days = body.expires_in_days,
        actor_id        = user["id"],
    )
    return {
        "api_key" : raw,               # shown ONCE
        "key_id"  : rec.key_id,
        "name"    : rec.name,
        "scopes"  : rec.scopes,
        "expires_at": rec.expires_at,
        "warning" : "Store this key securely — it will not be shown again.",
    }


@router.get("")
async def list_keys(user: dict = Depends(get_current_user)):
    return {"keys": [r.to_dict(redact=True) for r in await list_api_keys(owner_id=user["id"])]}


@router.delete("/{key_id}", status_code=204)
async def revoke_key(key_id: str, user: dict = Depends(get_current_user)):
    if not await revoke_api_key(key_id, owner_id=user["id"]):
        raise HTTPException(404, f"Key {key_id!r} not found")
