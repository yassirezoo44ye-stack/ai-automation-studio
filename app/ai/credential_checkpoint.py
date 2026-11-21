"""Pure checkpoint planning for an authorized BYOK credential migration.

No database access or secrets. The caller must persist the checkpoint and
obtain the inventory from a trusted source before using these helpers.
"""
from __future__ import annotations

ALLOWED = frozenset({"pending", "running", "verified", "failed"})

def plan_next_scopes(inventory: set[str], checkpoint: dict[str, str], *, limit: int = 50) -> list[str]:
    if not isinstance(inventory, set) or not inventory or any(not isinstance(x, str) or not x for x in inventory):
        raise ValueError("nonempty verified inventory required")
    if not isinstance(checkpoint, dict) or not set(checkpoint).issubset(inventory):
        raise ValueError("checkpoint contains unknown scopes")
    if any(status not in ALLOWED for status in checkpoint.values()):
        raise ValueError("invalid checkpoint status")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    # A running scope is treated as interrupted and eligible for retry.
    # Failed scopes require explicit operator review; never retry automatically.
    return sorted(scope for scope in inventory if checkpoint.get(scope, "pending") in {"pending", "running"})[:limit]


def mark_scope(checkpoint: dict[str, str], scope: str, status: str) -> dict[str, str]:
    if not isinstance(checkpoint, dict) or scope not in checkpoint:
        raise ValueError("scope must already exist in checkpoint")
    old = checkpoint[scope]
    if old not in ALLOWED or status not in ALLOWED:
        raise ValueError("invalid checkpoint status")
    allowed = {
        "pending": {"running"},
        "running": {"verified", "failed"},
        "failed": {"pending"},
        "verified": set(),
    }
    if status not in allowed[old]:
        raise ValueError("invalid checkpoint transition")
    return {**checkpoint, scope: status}
