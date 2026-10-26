"""Gmail read-only OAuth + bounded message retrieval. Tokens never leave server."""

import base64
import hashlib
import secrets
from datetime import UTC, datetime
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken

from .engine import mime_text

SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
QUERY = "newer_than:14d -in:trash -in:spam (from:jobalerts-noreply@linkedin.com OR from:jobs-noreply@linkedin.com OR from:donotreply@jobalert.indeed.com)"


class GmailUnavailable(Exception):
    """Safe public error, deliberately excludes provider response or credentials."""


def cipher():
    from app.core.auth import derive_fernet_key

    return Fernet(derive_fernet_key("career-gmail"))


def decrypt(encrypted):
    try:
        return cipher().decrypt(encrypted.encode()).decode()
    except InvalidToken:
        raise GmailUnavailable(
            "Stored Gmail consent is invalid; reconnect / أعد ربط Gmail"
        ) from None


def settings():
    from app.core.config import (
        CAREER_GOOGLE_CLIENT_ID,
        CAREER_GOOGLE_CLIENT_SECRET,
        CAREER_GOOGLE_REDIRECT_URI,
    )

    if not all(
        (
            CAREER_GOOGLE_CLIENT_ID,
            CAREER_GOOGLE_CLIENT_SECRET,
            CAREER_GOOGLE_REDIRECT_URI,
        )
    ):
        raise GmailUnavailable("Gmail OAuth is not configured / ربط Gmail غير مهيأ")
    return (
        CAREER_GOOGLE_CLIENT_ID,
        CAREER_GOOGLE_CLIENT_SECRET,
        CAREER_GOOGLE_REDIRECT_URI,
    )


def authorization():
    client_id, _, redirect = settings()
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .decode()
        .rstrip("=")
    )
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect,
            "response_type": "code",
            "scope": SCOPE,
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    return state, verifier, url


async def token_request(data):
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                "https://oauth2.googleapis.com/token", data=data
            )
            response.raise_for_status()
            return response.json()
    except (httpx.HTTPError, ValueError):
        raise GmailUnavailable(
            "Gmail authorization failed; reconnect / تعذّر التفويض؛ أعد الربط"
        ) from None


async def exchange(code, verifier):
    client_id, secret, redirect = settings()
    result = await token_request(
        {
            "client_id": client_id,
            "client_secret": secret,
            "redirect_uri": redirect,
            "code": code,
            "code_verifier": verifier,
            "grant_type": "authorization_code",
        }
    )
    if SCOPE not in result.get("scope", "").split() or not result.get("refresh_token"):
        raise GmailUnavailable(
            "Read-only offline consent required / يلزم تفويض القراءة والعمل دون اتصال"
        )
    return result["refresh_token"]


async def read_alerts(refresh_token, processed):
    client_id, secret, _ = settings()
    token = await token_request(
        {
            "client_id": client_id,
            "client_secret": secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
    )
    if not token.get("access_token"):
        raise GmailUnavailable("Reconnect Gmail / أعد ربط Gmail")
    alerts, page = [], None
    # At most 100 matching messages per run; processed IDs do not consume body calls.
    try:
        async with httpx.AsyncClient(
            timeout=20, headers={"Authorization": "Bearer " + token["access_token"]}
        ) as client:
            for _ in range(2):
                params = {"q": QUERY, "maxResults": 50}
                if page:
                    params["pageToken"] = page
                response = await client.get(
                    "https://gmail.googleapis.com/gmail/v1/users/me/messages",
                    params=params,
                )
                response.raise_for_status()
                result = response.json()
                for message in result.get("messages", []):
                    mid = message["id"]
                    if mid in processed:
                        continue
                    response = await client.get(
                        "https://gmail.googleapis.com/gmail/v1/users/me/messages/"
                        + mid,
                        params={"format": "full"},
                    )
                    response.raise_for_status()
                    body = response.json()
                    received = (
                        datetime.fromtimestamp(
                            int(body.get("internalDate", 0)) / 1000, UTC
                        ).isoformat()
                        if body.get("internalDate")
                        else None
                    )
                    alerts.append(
                        (mid, mime_text(body.get("payload", {}))[:200000], received)
                    )
                page = result.get("nextPageToken")
                if not page:
                    break
    except (httpx.HTTPError, ValueError, KeyError):
        raise GmailUnavailable(
            "Gmail sync failed; retry or reconnect / تعذّرت المزامنة؛ أعد المحاولة أو الربط"
        ) from None
    return alerts
