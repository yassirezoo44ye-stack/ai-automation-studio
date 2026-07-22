"""
Org quota helpers for legacy single-tenant routers (chat.py, build.py) that
call the Anthropic SDK directly instead of going through AIGateway/
InferenceEngine (which already enforce quota — see app/ai/gateway.py).

These routers predate multi-tenancy, so org context is optional: resolve
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
    Returns the caller's org_id if present *and verified* (they're actually
    a member — see app.tenancy.context.optional_org_id), or None to skip
    enforcement entirely.

    Verifying membership (rather than trusting the X-Organization-Id header
    as-is, which the original version of this function did) matters here
    specifically because it's metering/billing-relevant: an unverified org
    id would let any authenticated caller charge their token usage against,
    or trip the quota limit of, an org they don't belong to."""
    from app.tenancy.context import optional_org_id
    org_id = await optional_org_id(request)
    if not org_id:
        return None
    from app.billing import get_usage_service, QuotaExceeded
    try:
        await get_usage_service().check_quota(org_id, "tokens", 1)
    except QuotaExceeded as e:
        raise HTTPException(429, str(e))
    return org_id


async def check_org_quota_id(org_id: Optional[str]) -> bool:
    """Non-HTTP variant of check_org_quota — for internal callers (the agent
    kernel, background self-reflection, evolution) that already hold an
    org_id value rather than a Request to read the X-Organization-Id header
    from. Returns False when the org is over quota (caller should skip the
    LLM call and degrade gracefully); True otherwise. Never raises — these
    callers have no HTTP response to attach a 429 to."""
    if not org_id:
        return True
    from app.billing import get_usage_service, QuotaExceeded
    try:
        await get_usage_service().check_quota(org_id, "tokens", 1)
    except QuotaExceeded:
        log.warning("org %s over quota — skipping internal LLM call", org_id)
        return False
    except Exception:
        log.warning("quota check failed for org=%s, allowing call", org_id, exc_info=True)
    return True


async def record_org_tokens(
    org_id: Optional[str], total_tokens: int, ref_id: str | None, *, ref_type: str = "chat",
) -> None:
    """Best-effort — never breaks the response path."""
    if not org_id or total_tokens <= 0:
        return
    try:
        from app.billing import get_usage_service
        await get_usage_service().record(
            org_id, "tokens", total_tokens, ref_type=ref_type, ref_id=ref_id,
        )
    except Exception:
        log.warning("org token usage record failed for org=%s", org_id, exc_info=True)
