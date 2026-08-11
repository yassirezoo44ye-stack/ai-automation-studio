"""Cookie helpers for the refresh-token / CSRF double-submit flow.

Refresh cookie: httpOnly, Secure, SameSite=Strict, scoped to the refresh/logout
paths only (`path=/api/v1/auth`) so it is never sent on unrelated requests.
CSRF cookie: readable by JS (not httpOnly) so the frontend can mirror its value
into an `X-CSRF-Token` header; the two must match for state-changing,
cookie-authenticated requests (see api/v1/auth.py).
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Response

from app.core.config import get_settings

settings = get_settings()

_AUTH_COOKIE_PATH = "/api/v1/auth"


def set_refresh_cookie(response: Response, *, token: str, expires_at: datetime) -> None:
    max_age = max(0, int((expires_at - datetime.now(timezone.utc)).total_seconds()))
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=token,
        max_age=max_age,
        expires=max_age,
        path=_AUTH_COOKIE_PATH,
        domain=settings.cookie_domain,
        secure=settings.cookie_secure,
        httponly=True,
        samesite="strict",
    )


def clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.refresh_cookie_name,
        path=_AUTH_COOKIE_PATH,
        domain=settings.cookie_domain,
    )


def set_csrf_cookie(response: Response, *, token: str, expires_at: datetime) -> None:
    max_age = max(0, int((expires_at - datetime.now(timezone.utc)).total_seconds()))
    response.set_cookie(
        key=settings.csrf_cookie_name,
        value=token,
        max_age=max_age,
        expires=max_age,
        path="/",
        domain=settings.cookie_domain,
        secure=settings.cookie_secure,
        httponly=False,
        samesite="strict",
    )


def clear_csrf_cookie(response: Response) -> None:
    response.delete_cookie(key=settings.csrf_cookie_name, path="/", domain=settings.cookie_domain)
