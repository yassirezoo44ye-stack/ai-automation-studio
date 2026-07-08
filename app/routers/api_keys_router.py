"""
API Key management endpoints.

POST /api/keys              create a new key (admin only via JWT)
GET  /api/keys              list your keys
DELETE /api/keys/{key_id}   revoke a key
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.api_keys import (
    create_api_key, revoke_api_key, list_api_keys, require_api_key,
)

router = APIRouter(prefix="/api/keys", tags=["api-keys"])


class CreateKeyRequest(BaseModel):
    name            : str
    scopes          : list[str] = ["read"]
    expires_in_days : Optional[int] = None


@router.post("", status_code=201)
async def create_key(body: CreateKeyRequest):
    """
    Create a new API key. The raw key is returned ONCE — store it securely.
    """
    if not body.scopes:
        raise HTTPException(400, "At least one scope required")
    valid_scopes = {"read", "write", "admin", "agents", "marketplace"}
    bad = set(body.scopes) - valid_scopes
    if bad:
        raise HTTPException(400, f"Unknown scopes: {bad}. Valid: {valid_scopes}")

    raw, rec = create_api_key(
        name            = body.name,
        scopes          = body.scopes,
        expires_in_days = body.expires_in_days,
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
async def list_keys():
    return {"keys": [r.to_dict(redact=True) for r in list_api_keys()]}


@router.delete("/{key_id}", status_code=204)
async def revoke_key(key_id: str):
    if not revoke_api_key(key_id):
        raise HTTPException(404, f"Key {key_id!r} not found")
