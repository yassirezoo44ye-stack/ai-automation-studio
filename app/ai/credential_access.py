"""Authorization boundary for the future BYOK API.

Not registered as a route. Every call requires a verified OrgContext from
app.tenancy.context.org_context, not identifiers from request JSON.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.tenancy.context import OrgContext

from app.ai.user_credentials import ALLOWED_PROVIDERS


class CredentialAccessDenied(PermissionError):
    pass


@dataclass(frozen=True)
class CredentialScope:
    org_id: str
    user_id: str
    provider: str


def scope_for_authenticated_user(ctx: OrgContext, provider: str) -> CredentialScope:
    """Credentials are private to the authenticated user within their org.

    Never allow org administrators to read other members' BYOK secrets.
    The tenancy dependency verifies membership before constructing ctx.
    """
    if not isinstance(ctx, OrgContext):
        raise CredentialAccessDenied("Verified organization context required")
    if not ctx.org_id or not ctx.user_id or not ctx.role:
        raise CredentialAccessDenied("Incomplete organization context")
    if provider not in ALLOWED_PROVIDERS:
        raise ValueError("Unsupported BYOK provider")
    return CredentialScope(org_id=ctx.org_id, user_id=ctx.user_id, provider=provider)


async def has_credential(conn, *, scope: CredentialScope) -> bool:
    """Return only existence; never return ciphertext or secret metadata."""
    row = await conn.fetchrow(
        """SELECT 1 AS configured FROM ai_user_credentials
           WHERE org_id=$1 AND user_id=$2 AND provider=$3""",
        __import__("uuid").UUID(scope.org_id),
        __import__("uuid").UUID(scope.user_id),
        scope.provider,
    )
    return row is not None
