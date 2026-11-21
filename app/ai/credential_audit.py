"""Pure BYOK rotation audit aggregation; never accepts or emits credentials.

Input rows must come from an independently authorized, exhaustive inventory.
This module cannot enumerate tenants or attest database snapshot consistency.
"""
from __future__ import annotations

def summarize_rotation_audit(results: dict[str, dict[str, int | bool]], *, expected_scope_ids: set[str]) -> dict[str, int | bool]:
    if not isinstance(expected_scope_ids, set) or any(not isinstance(x, str) or not x for x in expected_scope_ids):
        raise ValueError("expected_scope_ids must be a set of nonempty opaque IDs")
    if not isinstance(results, dict) or not expected_scope_ids:
        raise ValueError("nonempty independently verified inventory required")
    if any(not isinstance(x, str) or not x for x in results):
        raise ValueError("invalid result scope ID")
    if not set(results).issubset(expected_scope_ids):
        raise ValueError("unexpected scope ID")
    scanned = old_or_unreadable = unreadable = 0
    for item in results.values():
        if not isinstance(item, dict):
            raise ValueError("invalid audit result")
        if set(item) != {"scanned", "not_primary", "unreadable", "complete"}:
            raise ValueError("invalid audit result fields")
        n, old, bad, done = (item[k] for k in ("scanned", "not_primary", "unreadable", "complete"))
        if any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in (n, old, bad)):
            raise ValueError("invalid audit counts")
        if not isinstance(done, bool) or old > n or bad > old or done != (old == 0):
            raise ValueError("inconsistent audit result")
        if n == 0:
            raise ValueError("expected credential scope has no rows; inventory may be stale")
        scanned += n
        old_or_unreadable += old
        unreadable += bad
    covered = set(results) == expected_scope_ids
    # Even if every inspected scope passes, incomplete inventory fails closed.
    return {
        "expected_scopes": len(expected_scope_ids),
        "checked_scopes": len(results),
        "scanned": scanned,
        "not_primary": old_or_unreadable,
        "unreadable": unreadable,
        "complete": covered and old_or_unreadable == 0,
    }
