"""Pure BYOK rotation audit aggregation; never accepts or emits credentials.

Input rows must come from an independently authorized, exhaustive inventory.
This module cannot enumerate tenants or attest database snapshot consistency.
"""
from __future__ import annotations

def summarize_rotation_audit(results: list[dict[str, int | bool]], *, expected_scopes: int) -> dict[str, int | bool]:
    if isinstance(expected_scopes, bool) or not isinstance(expected_scopes, int) or expected_scopes < 0:
        raise ValueError("expected_scopes must be a non-negative integer")
    if len(results) > expected_scopes:
        raise ValueError("more results than expected scopes")
    scanned = old_or_unreadable = unreadable = 0
    for item in results:
        if set(item) != {"scanned", "not_primary", "unreadable", "complete"}:
            raise ValueError("invalid audit result fields")
        n, old, bad, done = (item[k] for k in ("scanned", "not_primary", "unreadable", "complete"))
        if any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in (n, old, bad)):
            raise ValueError("invalid audit counts")
        if not isinstance(done, bool) or old > n or bad > old or done != (old == 0):
            raise ValueError("inconsistent audit result")
        scanned += n
        old_or_unreadable += old
        unreadable += bad
    covered = len(results) == expected_scopes
    # Even if every inspected scope passes, incomplete inventory fails closed.
    return {
        "expected_scopes": expected_scopes,
        "checked_scopes": len(results),
        "scanned": scanned,
        "not_primary": old_or_unreadable,
        "unreadable": unreadable,
        "complete": covered and old_or_unreadable == 0,
    }
