"""Recommended-stack catalogue shown after a build is delivered.

Entries come from ``RECOMMENDED_STACK_JSON`` (inline JSON list) so referral links
can change without a deploy. Nothing is invented: with no configuration only the
neutral defaults below are served, and those carry plain official URLs with no
referral tracking. An entry is shown as a referral only when it says so, and the
client always renders a disclosure for those entries.
"""
import json
import logging
import os
import re
from urllib.parse import urlparse

log = logging.getLogger(__name__)

_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
CATEGORIES = ("hosting", "database", "domain", "email")

DEFAULTS: list[dict] = [
    {"id": "render", "category": "hosting", "name": "Render", "url": "https://render.com", "referral": False},
    {"id": "vercel", "category": "hosting", "name": "Vercel", "url": "https://vercel.com", "referral": False},
    {"id": "supabase", "category": "database", "name": "Supabase", "url": "https://supabase.com", "referral": False},
]


def _clean(entry: object) -> dict | None:
    if not isinstance(entry, dict):
        return None
    ident, category, name, url = (entry.get(k) for k in ("id", "category", "name", "url"))
    if not (isinstance(ident, str) and _ID.match(ident) and category in CATEGORIES
            and isinstance(name, str) and 0 < len(name) <= 60 and isinstance(url, str)):
        return None
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return None
    return {"id": ident, "category": category, "name": name.strip(), "url": url,
            "referral": entry.get("referral") is True}


def catalogue() -> list[dict]:
    raw = os.getenv("RECOMMENDED_STACK_JSON", "").strip()
    if not raw:
        return [dict(e) for e in DEFAULTS]
    try:
        data = json.loads(raw)
    except ValueError:
        log.warning("RECOMMENDED_STACK_JSON is not valid JSON; using defaults")
        return [dict(e) for e in DEFAULTS]
    cleaned = [c for c in (_clean(e) for e in data[:30]) if c] if isinstance(data, list) else []
    seen: set[str] = set()
    unique = [e for e in cleaned if not (e["id"] in seen or seen.add(e["id"]))]
    return unique


def find(ident: str) -> dict | None:
    return next((e for e in catalogue() if e["id"] == ident), None)
