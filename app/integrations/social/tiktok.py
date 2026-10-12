"""
TikTokProvider — Social Publisher integration for TikTok Content Posting API v2.

API reference: https://developers.tiktok.com/doc/content-posting-api-reference/
OAuth reference: https://developers.tiktok.com/doc/login-kit-web/

Environment variables required:
    TIKTOK_CLIENT_KEY    — the app's Client Key (not the same as client_id)
    TIKTOK_CLIENT_SECRET — the app's Client Secret

App approval requirements (external — not code):
    • App must be approved for "Content Posting API" on
      https://developers.tiktok.com/
    • Required scopes: video.upload, video.publish, user.info.basic
    • Redirect URI must be registered in the app dashboard

PULL_FROM_URL requirements (TikTok's documented constraints):
    • video_url must be a direct download link (no redirects, no auth required)
    • URL must be accessible from TikTok's servers (public CDN)
    • Supported codecs: H.264/H.265, AAC audio
    • Max duration: per creator's creator_info.max_video_post_duration_sec
    • Max file size: 4 GB

Token lifecycle:
    • access_token:  expires in 24 hours (86400 s)
    • refresh_token: expires in 1 year  (31536000 s)
    • Both token values are NEVER logged — only open_id / platform_user_id is safe to log.

Error handling strategy:
    TikTokTokenExpiredError  → caller should refresh the token, then retry
    TikTokRateLimitError     → caller should wait retry_after seconds, then retry
    TikTokRetryableError     → transient server-side error; safe to retry
    TikTokAPIError           → permanent error; do not retry

Idempotency / duplicate-publish prevention:
    publish_video() returns a publish_id the first time it succeeds.
    The caller (social_publish_jobs row) stores this id.  On any subsequent
    retry the caller MUST call get_publish_status(publish_id) instead of
    calling publish_video() again — TikTok does not deduplicate on its side.
    The router and job worker enforce this: publish_video() is called only
    when platform_post_id IS NULL for the job row.
"""
from __future__ import annotations

import logging
import os
import urllib.parse
from typing import Any

import httpx

from app.integrations.social.base import (
    OAuthTokenResult,
    PublishRequest,
    PublishResult,
    PublishStatus,
    PublishStatusResult,
    SocialPublisherProvider,
)

log = logging.getLogger(__name__)

# ── TikTok API base URLs ───────────────────────────────────────────────────────
_AUTH_URL         = "https://www.tiktok.com/v2/auth/authorize/"
_TOKEN_URL        = "https://open.tiktokapis.com/v2/oauth/token/"
_REVOKE_URL       = "https://open.tiktokapis.com/v2/oauth/revoke/"
_USER_INFO_URL    = "https://open.tiktokapis.com/v2/user/info/"
_CREATOR_INFO_URL = "https://open.tiktokapis.com/v2/post/publish/creator_info/query/"
_PUBLISH_INIT_URL = "https://open.tiktokapis.com/v2/post/publish/video/init/"
_STATUS_URL       = "https://open.tiktokapis.com/v2/post/publish/status/fetch/"

# Required OAuth scopes (space-separated per TikTok spec)
_SCOPES = "video.upload,video.publish,user.info.basic"

# HTTP client timeout (seconds)
_TIMEOUT = httpx.Timeout(30.0, connect=10.0)

# TikTok publish status → our PublishStatus mapping
_STATUS_MAP: dict[str, PublishStatus] = {
    "PROCESSING_DOWNLOAD":                    PublishStatus.PROCESSING,
    "PROCESSING_UPLOAD":                      PublishStatus.PROCESSING,
    "SEND_BY_AWAITING_PLATFORM_CONFIRMATION": PublishStatus.PROCESSING,
    "PUBLISHED":                              PublishStatus.COMPLETED,
    "FAILED":                                 PublishStatus.FAILED,
}

# Error codes that indicate the access_token is invalid/expired
_TOKEN_EXPIRED_CODES = frozenset({
    "access_token_invalid",
    "access_token_expired",
})

# Error codes that are safe to retry after a delay
_RETRYABLE_CODES = frozenset({
    "server_error",
    "internal_error",
    "spam_risk_too_many_pending_share",
    # spam_risk_user_banned_from_posting is permanent → TikTokAPIError, not retryable
})

# Error code for rate limiting
_RATE_LIMIT_CODE = "rate_limit_exceeded"


# ── Custom exceptions ─────────────────────────────────────────────────────────

class TikTokTokenExpiredError(Exception):
    """Access token is invalid or expired — caller should refresh and retry."""


class TikTokRateLimitError(Exception):
    """Rate limit hit — caller should wait retry_after seconds before retrying."""
    def __init__(self, message: str, retry_after: int = 60) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class TikTokRetryableError(Exception):
    """Transient server-side error — safe to retry after a short delay."""


class TikTokAPIError(Exception):
    """Permanent API error — do not retry; log error_code for diagnosis."""
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"TikTok API error [{code}]: {message}")
        self.error_code = code
        self.error_message = message


# ── Provider ──────────────────────────────────────────────────────────────────

class TikTokProvider(SocialPublisherProvider):
    """
    TikTok Content Posting API v2 provider.

    Stateless — instantiated once in the registry.  Every method receives
    the credential it needs; nothing is stored on the instance.
    """

    def __init__(self) -> None:
        self._client_key    = os.getenv("TIKTOK_CLIENT_KEY",    "")
        self._client_secret = os.getenv("TIKTOK_CLIENT_SECRET", "")

    # ── Identity ──────────────────────────────────────────────────────────────

    @property
    def platform_id(self) -> str:
        return "tiktok"

    @property
    def display_name(self) -> str:
        return "TikTok"

    def is_available(self) -> bool:
        return bool(self._client_key and self._client_secret)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _raise_for_tiktok_error(self, error: dict) -> None:
        """Raise the appropriate exception for a TikTok error block.

        TikTok error responses look like:
            {"code": "access_token_invalid", "message": "...", "log_id": "..."}
        An "ok" code means success.
        """
        code    = (error.get("code") or "").lower()
        message = error.get("message") or ""
        if code in ("ok", ""):
            return
        if code in _TOKEN_EXPIRED_CODES:
            raise TikTokTokenExpiredError(message)
        if code == _RATE_LIMIT_CODE:
            raise TikTokRateLimitError(message, retry_after=60)
        if code in _RETRYABLE_CODES:
            raise TikTokRetryableError(f"[{code}] {message}")
        raise TikTokAPIError(code, message)

    def _auth_header(self, access_token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {access_token}"}

    # ── OAuth ─────────────────────────────────────────────────────────────────

    def get_auth_url(self, redirect_uri: str, state: str) -> str:
        """Build the TikTok OAuth 2.0 authorization URL."""
        params = {
            "client_key":     self._client_key,
            "scope":          _SCOPES,
            "response_type":  "code",
            "redirect_uri":   redirect_uri,
            "state":          state,
        }
        return f"{_AUTH_URL}?{urllib.parse.urlencode(params)}"

    async def exchange_code(self, code: str, redirect_uri: str) -> OAuthTokenResult:
        """Exchange authorization code for access + refresh tokens.

        Also fetches basic user info (open_id, username, display_name) so the
        caller can store the account identity without a second round-trip.

        Raises:
            TikTokAPIError      if the exchange fails permanently
            RuntimeError        on network errors
        """
        payload = {
            "client_key":    self._client_key,
            "client_secret": self._client_secret,
            "code":          code,
            "grant_type":    "authorization_code",
            "redirect_uri":  redirect_uri,
        }
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(_TOKEN_URL, data=payload)
                resp.raise_for_status()
                body = resp.json()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(f"TikTok token exchange HTTP {exc.response.status_code}") from exc
        except httpx.RequestError as exc:
            raise RuntimeError(f"TikTok token exchange network error: {exc}") from exc

        if "error" in body and body["error"] != "ok":
            raise TikTokAPIError(body["error"], body.get("error_description", ""))

        data    = body.get("data", body)   # v2 wraps in "data"; v1 returns flat
        open_id = data.get("open_id", "")
        scopes  = [s.strip() for s in data.get("scope", "").split(",") if s.strip()]

        # Fetch user info to get username/display_name
        access_token = data.get("access_token", "")
        username, display_name, avatar_url = await self._fetch_user_basic_info(
            access_token, open_id
        )

        return OAuthTokenResult(
            access_token       = access_token,
            refresh_token      = data.get("refresh_token"),
            expires_in         = data.get("expires_in"),
            platform_user_id   = open_id,
            platform_username  = username,
            platform_name      = display_name,
            scopes             = scopes,
            metadata           = {"avatar_url": avatar_url} if avatar_url else {},
        )

    async def refresh_access_token(self, refresh_token: str) -> OAuthTokenResult:
        """Refresh an expired access token using the refresh token.

        Raises:
            TikTokTokenExpiredError if the refresh token is also expired
            RuntimeError            on network errors
        """
        payload = {
            "client_key":     self._client_key,
            "client_secret":  self._client_secret,
            "grant_type":     "refresh_token",
            "refresh_token":  refresh_token,
        }
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(_TOKEN_URL, data=payload)
                resp.raise_for_status()
                body = resp.json()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(f"TikTok token refresh HTTP {exc.response.status_code}") from exc
        except httpx.RequestError as exc:
            raise RuntimeError(f"TikTok token refresh network error: {exc}") from exc

        if "error" in body and body["error"] != "ok":
            err = body["error"]
            if err in _TOKEN_EXPIRED_CODES or err == "refresh_token_expired":
                raise TikTokTokenExpiredError(body.get("error_description", "Refresh token expired"))
            raise TikTokAPIError(err, body.get("error_description", ""))

        data    = body.get("data", body)
        open_id = data.get("open_id", "")
        scopes  = [s.strip() for s in data.get("scope", "").split(",") if s.strip()]

        return OAuthTokenResult(
            access_token      = data.get("access_token", ""),
            refresh_token     = data.get("refresh_token", refresh_token),
            expires_in        = data.get("expires_in"),
            platform_user_id  = open_id,
            scopes            = scopes,
        )

    async def revoke_token(self, access_token: str) -> None:
        """Best-effort token revocation — does not raise on failure."""
        payload = {
            "client_key":    self._client_key,
            "client_secret": self._client_secret,
            "token":         access_token,
        }
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                await client.post(_REVOKE_URL, data=payload)
        except Exception:
            pass  # best-effort; failure is acceptable

    # ── Account info ──────────────────────────────────────────────────────────

    async def _fetch_user_basic_info(
        self,
        access_token: str,
        open_id: str,
    ) -> tuple[str | None, str | None, str | None]:
        """Fetch username, display_name, avatar_url from TikTok.

        Returns (username, display_name, avatar_url) — all may be None on error.
        Never raises (used in exchange_code which already has its own error handling).
        """
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.get(
                    _USER_INFO_URL,
                    params={"fields": "open_id,avatar_url,display_name,username"},
                    headers=self._auth_header(access_token),
                )
                resp.raise_for_status()
                body = resp.json()
            data = body.get("data", {}).get("user", {})
            return (
                data.get("username"),
                data.get("display_name"),
                data.get("avatar_url"),
            )
        except Exception as exc:
            log.warning("tiktok user info fetch failed open_id=%s: %s", open_id, exc)
            return None, None, None

    async def get_account_info(
        self,
        access_token: str,
        platform_user_id: str,
    ) -> dict[str, Any]:
        """Fetch live account info including creator posting capabilities."""
        username, display_name, avatar_url = await self._fetch_user_basic_info(
            access_token, platform_user_id
        )
        creator_info = await self._fetch_creator_info(access_token, platform_user_id)
        return {
            "platform_user_id":   platform_user_id,
            "username":           username,
            "display_name":       display_name,
            "avatar_url":         avatar_url,
            **creator_info,
        }

    async def _fetch_creator_info(
        self,
        access_token: str,
        platform_user_id: str,
    ) -> dict[str, Any]:
        """Fetch creator posting constraints (privacy options, max duration, etc.).

        Used before publishing to validate video requirements and available
        privacy levels.  Returns empty dict on failure — non-blocking.
        """
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(
                    _CREATOR_INFO_URL,
                    headers={**self._auth_header(access_token), "Content-Type": "application/json; charset=UTF-8"},
                )
                resp.raise_for_status()
                body = resp.json()
            err = body.get("error", {})
            self._raise_for_tiktok_error(err)
            return body.get("data", {})
        except (TikTokTokenExpiredError, TikTokAPIError) as exc:
            log.warning("tiktok creator_info failed open_id=%s: %s", platform_user_id, exc)
            return {}
        except Exception as exc:
            log.warning("tiktok creator_info network error open_id=%s: %s", platform_user_id, exc)
            return {}

    # ── Publishing ────────────────────────────────────────────────────────────

    async def publish_video(self, request: PublishRequest) -> PublishResult:
        """Initiate a TikTok video post via PULL_FROM_URL.

        TikTok fetches the video from request.video_url asynchronously.
        The publish_id returned must be stored and polled via get_publish_status().

        Options supported (via request.options):
            privacy_level:    str  — PUBLIC_TO_EVERYONE (default), SELF_ONLY,
                                     MUTUAL_FOLLOW_FRIENDS, FOLLOWER_OF_CREATOR
            disable_duet:     bool — default False
            disable_stitch:   bool — default False
            disable_comment:  bool — default False
            cover_ms:         int  — video_cover_timestamp_ms in ms (default 0)

        Raises:
            TikTokTokenExpiredError  — token needs refresh
            TikTokRateLimitError     — rate limit; retry_after seconds
            TikTokRetryableError     — transient; safe to retry
            TikTokAPIError           — permanent; do not retry
            RuntimeError             — network error
        """
        opts = request.options or {}

        # Build caption: TikTok calls this "title" (max 2200 chars including hashtags)
        tags_str = " ".join(f"#{t.lstrip('#')}" for t in request.hashtags) if request.hashtags else ""
        title = f"{request.caption} {tags_str}".strip()[:2200]

        payload: dict[str, Any] = {
            "post_info": {
                "title":                    title,
                "privacy_level":            opts.get("privacy_level", "PUBLIC_TO_EVERYONE"),
                "disable_duet":             bool(opts.get("disable_duet",    False)),
                "disable_comment":          bool(opts.get("disable_comment", False)),
                "disable_stitch":           bool(opts.get("disable_stitch",  False)),
                "video_cover_timestamp_ms": int(opts.get("cover_ms", 0)),
            },
            "source_info": {
                "source":    "PULL_FROM_URL",
                "video_url": request.video_url,
            },
        }

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(
                    _PUBLISH_INIT_URL,
                    json=payload,
                    headers={**self._auth_header(request.access_token), "Content-Type": "application/json; charset=UTF-8"},
                )
                resp.raise_for_status()
                body = resp.json()
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            log.error("tiktok publish_init HTTP %s open_id=%s", status_code, request.platform_user_id)
            raise RuntimeError(f"TikTok API returned HTTP {status_code}") from exc
        except httpx.RequestError as exc:
            log.error("tiktok publish_init network error open_id=%s: %s", request.platform_user_id, exc)
            raise RuntimeError(f"TikTok network error: {exc}") from exc

        err = body.get("error", {})
        self._raise_for_tiktok_error(err)

        data       = body.get("data", {})
        publish_id = data.get("publish_id", "")
        if not publish_id:
            raise TikTokAPIError("missing_publish_id", "TikTok returned no publish_id")

        log.info("tiktok publish_init ok open_id=%s publish_id=%s", request.platform_user_id, publish_id)

        return PublishResult(
            platform_publish_id = publish_id,
            status              = PublishStatus.PROCESSING,
            metadata            = {"tiktok_log_id": err.get("log_id", "")},
        )

    async def get_publish_status(
        self,
        publish_id: str,
        access_token: str,
    ) -> PublishStatusResult:
        """Poll TikTok for the current status of a publish job.

        TikTok status values:
            PROCESSING_DOWNLOAD                    → PROCESSING
            PROCESSING_UPLOAD                      → PROCESSING
            SEND_BY_AWAITING_PLATFORM_CONFIRMATION → PROCESSING
            PUBLISHED                              → COMPLETED (platform_url set)
            FAILED                                 → FAILED    (error details set)

        Raises:
            TikTokTokenExpiredError  — token needs refresh
            TikTokRateLimitError     — slow down
            TikTokRetryableError     — transient
            TikTokAPIError           — permanent error
            RuntimeError             — network error
        """
        payload = {"publish_id": publish_id}

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(
                    _STATUS_URL,
                    json=payload,
                    headers={**self._auth_header(access_token), "Content-Type": "application/json; charset=UTF-8"},
                )
                resp.raise_for_status()
                body = resp.json()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(f"TikTok status check HTTP {exc.response.status_code}") from exc
        except httpx.RequestError as exc:
            raise RuntimeError(f"TikTok status check network error: {exc}") from exc

        err = body.get("error", {})
        self._raise_for_tiktok_error(err)

        data        = body.get("data", {})
        tiktok_stat = (data.get("status") or "").upper()
        our_status  = _STATUS_MAP.get(tiktok_stat, PublishStatus.PROCESSING)

        # Build platform URL when published
        platform_url: str | None = None
        if our_status == PublishStatus.COMPLETED:
            post_ids = data.get("publicaly_available_post_id") or []
            if post_ids:
                platform_url = f"https://www.tiktok.com/@_/video/{post_ids[0]}"

        # Failure details
        error_code:    str | None = None
        error_message: str | None = None
        if our_status == PublishStatus.FAILED:
            error_code    = data.get("fail_reason") or "unknown"
            error_message = f"TikTok publish failed: {error_code}"
            log.warning("tiktok publish FAILED publish_id=%s reason=%s", publish_id, error_code)

        return PublishStatusResult(
            platform_publish_id = publish_id,
            status              = our_status,
            platform_url        = platform_url,
            error_code          = error_code,
            error_message       = error_message,
            metadata            = {"tiktok_status": tiktok_stat},
        )
