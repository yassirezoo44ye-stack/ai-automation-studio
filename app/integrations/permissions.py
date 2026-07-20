"""
Permission model for integration connections — mirrors marketplace's
check_permission_manifest pattern (declare-time validation against a
known allowlist; runtime enforcement is the caller's job) rather than
inventing a parallel scheme.
"""
from __future__ import annotations

from app.integrations.provider import IntegrationProvider


def validate_requested_scopes(provider: IntegrationProvider, requested_scope_ids: list[str]) -> list[str]:
    """Returns a list of problems (empty = valid). A connection request
    naming a scope the provider never declared is rejected outright —
    the caller (service.py's connect()) should refuse to store the
    credential if this returns anything."""
    known = {s.id for s in provider.scopes()}
    return [f"unknown scope for {provider.provider_id!r}: {sid!r}" for sid in requested_scope_ids if sid not in known]


def sensitive_scopes(provider: IntegrationProvider, granted_scope_ids: list[str]) -> list[str]:
    """Which of the granted scopes are flagged sensitive — callers can use
    this to require an extra confirmation step or an org-admin-only gate
    before connect() proceeds."""
    sensitive_ids = {s.id for s in provider.scopes() if s.sensitive}
    return [sid for sid in granted_scope_ids if sid in sensitive_ids]
