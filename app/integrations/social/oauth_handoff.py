"""Exact public OAuth surface and strict frontend-origin binding."""

import re
from urllib.parse import urlsplit


def is_public_social_oauth_request(method: str, path: str) -> bool:
    suffix = (
        "callback" if method == "GET" else "authorize" if method == "POST" else None
    )
    return bool(
        suffix
        and re.fullmatch(
            r"/api/social/accounts/(tiktok|instagram|youtube)/" + suffix, path
        )
    )


def frontend_origin(configured: str) -> str:
    url = urlsplit(configured.strip())
    if (
        url.scheme != "https"
        or not url.hostname
        or url.username
        or url.password
        or url.path not in ("", "/")
        or url.query
        or url.fragment
    ):
        raise ValueError("HTTPS frontend origin required")
    return "https://" + url.netloc.lower()
