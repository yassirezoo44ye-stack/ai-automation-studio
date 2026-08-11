from __future__ import annotations

import re
import secrets

_slug_strip_re = re.compile(r"[^a-z0-9]+")


def slugify(value: str) -> str:
    """ASCII-ish slug. Non-latin input (e.g. Arabic org names) collapses to
    nothing useful, so callers must always fall back to a random suffix —
    handled by `unique_slug`."""
    value = value.strip().lower()
    value = _slug_strip_re.sub("-", value).strip("-")
    return value[:80]


def unique_slug(base: str) -> str:
    base_slug = slugify(base) or "workspace"
    return f"{base_slug}-{secrets.token_hex(3)}"
