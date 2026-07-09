"""
Org quota helpers for legacy single-tenant routers (chat.py, build.py) that
call the Anthropic SDK directly instead of going through AIGateway/
InferenceEngine (which already enforce quota — see app/ai/gateway.py).

These routers predate multi-tenancy, so org context is optional: read
X-Organization-Id (the same header apiFetch() already sends when an org is
selected — see src/renderer/shared/utils/api.ts) and only enforce/meter
when it's present. Callers with no org header keep working exactly as
before — this is purely additive.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import HTTPException, Request

log = logging.getLogger(__name__)


async def check_org_quota(request: Request) -> Optional[str]:
    """Quota-check up front, before spending money on a provider call.
    Returns the org_id if present, or None to skip enforcement entirely."""
    org_id = request.headers.get("X-Organization-Id")
    if not org_id:
        return None
    from app.billing import get_usage_service, QuotaExceeded
    try:
        await get_usage_service().check_quota(org_id, "tokens", 1)
    except QuotaExceeded as e:
        raise HTTPException(429, str(e))
    return org_id


async def record_org_tokens(org_id: Optional[str], total_tokens: int, ref_id: str | None) -> None:
    """Best-effort — never breaks the response path."""
    if not org_id or total_tokens <= 0:
        return
    try:
        from app.billing import get_usage_service
        await get_usage_service().record(
            org_id, "tokens", total_tokens, ref_type="chat", ref_id=ref_id,
        )
    except Exception:
        log.warning("org token usage record failed for org=%s", org_id, exc_info=True)
