"""Conservative BYOK key-retirement preflight.

This is an advisory guard only, not permission to remove previous keys.
Call from a privileged, read-only, REPEATABLE READ transaction after a
separately enforced write freeze. A human-approved change is still required.
"""
from __future__ import annotations
from app.ai.credential_inventory import read_rotation_coverage

async def retirement_preflight(conn) -> dict[str, int | bool]:
    coverage = await read_rotation_coverage(conn)
    expected = coverage["expected"]
    enrolled = coverage["enrolled"]
    verified = coverage["verified"]
    if any(type(x) is not int or x < 0 for x in (expected, enrolled, verified)):
        raise ValueError("invalid rotation coverage")
    if not 0 <= verified <= enrolled <= expected:
        raise ValueError("inconsistent rotation coverage")
    # Empty inventories cannot be interpreted as proof of complete migration.
    return {**coverage, "eligible_for_final_audit": expected > 0 and verified == expected}
