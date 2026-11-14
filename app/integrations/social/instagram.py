"""
InstagramProvider — Social Publisher integration for Instagram Reels via Meta Graph API.

API reference:  https://developers.facebook.com/docs/instagram-api/guides/content-publishing
OAuth reference: https://developers.facebook.com/docs/facebook-login/

Environment variables required:
    INSTAGRAM_APP_ID      — Meta/Facebook App ID
    INSTAGRAM_APP_SECRET  — Meta/Facebook App Secret

App approval requirements (external — not code):
    • "instagram_content_publish" permission approved by Meta
    • Account must be Instagram Professional (Business or Creator)
    • Account must be linked to a Facebook Page

Publishing flow (two-step async):
    1. POST /{ig-user-id}/media          → container_id  (async upload)
    2. GET  /{container_id}?fields=status_code  (poll until FINISHED, ~30s)
    3. POST /{ig-user-id}/media_publish  → ig_media_id   (triggers publication)

Publish ID lifecycle:
    publish_video()      → "{ig_user_id}|{container_id}"  status: PROCESSING
    get_publish_status() → same id while container is uploading
    get_publish_status() → "{ig_media_id}"  when COMPLETED (container FINISHED + published)
    The caller (social_publish_jobs) updates platform_post_id on each status poll.

Token lifecycle:
    • Short-lived user token (~2 hours): from code exchange
    • Long-lived user token (~60 days): from fb_exchange_token grant
    • refresh_access_token() extends via fb_exchange_token (new 60-day window)
    • access_token is NEVER logged — only platform_user_id (IG user ID) is safe to log

Error handling strategy:
    InstagramTokenExpiredError  → caller should refresh the token, then retry
    InstagramRateLimitError     → caller should wait retry_after seconds
    InstagramRetryableError     → transient server-side error; safe to retry
    InstagramAPIError           → permanent error; do not retry

Idempotency / duplicate-publish prevention:
    publish_video() creates a container_id. On any subsequent retry the caller
    MUST call get_publish_status(container_id) instead of calling publish_video()
    again.  The router/worker enforces this: publish_video() is called only when
    platform_post_id IS NULL for the job row.
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

# ── Meta / Instagram Graph API constants ──────────────────────────────────────
_GRAPH_VERSION = "v18.0"
_GRAPH_BASE    = f"https://graph.facebook.com/{_GRAPH_VERSION}"
_AUTH_URL      = f"https://www.facebook.com/{_GRAPH_VERSION}/dialog/oauth"
_TOKEN_URL     = f"{_GRAPH_BASE}/oauth/access_token"

# Required OAuth scopes for Reels content publishing
_SCOPES = "instagram_basic,instagram_content_publish,pages_show_list,pages_read_engagement"

# HTTP client timeout
_TIMEOUT = httpx.Timeout(30.0, connect=10.0)

# Container upload status values from the Graph API
# FINISHED: upload complete, media_publish must still be called
_CONTAINER_TERMINAL_DONE   = frozenset({"FINISHED"})
_CONTAINER_TERMINAL_FAILED = frozenset({"ERROR", "EXPIRED"})

# Graph API error codes → exception classification
_TOKEN_EXPIRED_CODES = frozenset({190, 467, 463})   # OAuthException / expired
_RATE_LIMIT_CODES    = frozenset({4, 17, 32, 613})  # app/user/page rate limits


# ── Custom exceptions ─────────────────────────────────────────────────────────

class InstagramTokenExpiredError(Exception):
    """Access token is invalid or expired — caller should refresh and retry."""


class InstagramRateLimitError(Exception):
    """Rate limit hit — caller should wait retry_after seconds before retrying."""
    def __init__(self, message: str, retry_after: int = 60) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class InstagramRetryableError(Exception):
    """Transient server-side error — safe to retry after a short delay."""


class InstagramAPIError(Exception):
    """Permanent API error — do not retry; log error_code for diagnosis."""
    def __init__(self, code: str | int, message: str) -> None:
        super().__init__(f"Instagram API error [{code}]: {message}")
        self.error_code = code
        self.error_message = message


# ── Provider ──────────────────────────────────────────────────────────────────

class InstagramProvider(SocialPublisherProvider):
    """
    Instagram Reels publisher via Meta Graph API.

    Stateless — instantiated once in the registry.  Every method receives
    the credential it needs; nothing is stored on the instance.

    The platform_user_id is the Instagram Business/Creator account ID (numeric string),
    distinct from the Facebook user ID.
    """

    def __init__(self) -> None:
        self._app_id     = os.getenv("INSTAGRAM_APP_ID",     "")
        self._app_secret = os.getenv("INSTAGRAM_APP_SECRET", "")

    # ── Identity ──────────────────────────────────────────────────────────────

    @property
    def platform_id(self) -> str:
        return "instagram"

    @property
    def display_name(self) -> str:
        return "Instagram"

    def is_available(self) -> bool:
        return bool(self._app_id and self._app_secret)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _raise_for_graph_error(self, error: dict, http_status: int = 200) -> None:
        """Raise the appropriate exception for a Graph API error block.

        Graph API error shape:
            {"message": "...", "type": "OAuthException", "code": 190, "fbtrace_id": "..."}

        When error dict is empty but http_status >= 500, raises InstagramRetryableError.
        """
        if not error:
            if http_status >= 500:
                raise InstagramRetryableError(f"HTTP {http_status}")
            return

        try:
            code = int(error.get("code", 0))
        except (TypeError, ValueError):
            code = 0
        message = error.get("message", "")

        if code in _TOKEN_EXPIRED_CODES:
            raise InstagramTokenExpiredError(message)
        if code in _RATE_LIMIT_CODES:
            raise InstagramRateLimitError(message, retry_after=60)
        raise InstagramAPIError(code, message)

    def _auth_params(self, access_token: str) -> dict[str, str]:
        return {"access_token": access_token}

    # ── OAuth ─────────────────────────────────────────────────────────────────

    def get_auth_url(self, redirect_uri: str, state: str) -> str:
        """Build the Meta OAuth 2.0 authorization URL."""
        params = {
            "client_id":     self._app_id,
            "redirect_uri":  redirect_uri,
            "scope":         _SCOPES,
            "response_type": "code",
            "state":         state,
        }
        return f"{_AUTH_URL}?{urllib.parse.urlencode(params)}"

    async def exchange_code(self, code: str, redirect_uri: str) -> OAuthTokenResult:
        """Exchange authorization code for a long-lived access token + IG account info.

        Steps:
            1. Exchange code → short-lived token (~2 hours)
            2. Exchange short-lived → long-lived token (~60 days)
            3. GET /me/accounts → find Instagram Professional account

        Raises:
            InstagramAPIError  if no Instagram Professional account is found
            RuntimeError       on network/auth failure
        """
        short_lived = await self._exchange_code_for_short_lived(code, redirect_uri)
        long_lived, expires_in = await self._exchange_for_long_lived(short_lived)
        ig_user_id, username, display_name, avatar_url = await self._fetch_ig_user(long_lived)

        return OAuthTokenResult(
            access_token      = long_lived,
            refresh_token     = long_lived,  # Instagram: "refresh" = extend with same token
            expires_in        = expires_in,
            platform_user_id  = ig_user_id,
            platform_username = username,
            platform_name     = display_name,
            scopes            = _SCOPES.split(","),
            metadata          = {"avatar_url": avatar_url} if avatar_url else {},
        )

    async def refresh_access_token(self, refresh_token: str) -> OAuthTokenResult:
        """Extend a long-lived token before it expires (new ~60-day window).

        refresh_token here is the current long-lived access token.

        Raises:
            InstagramTokenExpiredError if the token can no longer be extended
            RuntimeError               on network error
        """
        long_lived, expires_in = await self._exchange_for_long_lived(refresh_token)
        return OAuthTokenResult(
            access_token     = long_lived,
            refresh_token    = long_lived,
            expires_in       = expires_in,
            platform_user_id = "",  # caller already has this from the stored account row
            scopes           = _SCOPES.split(","),
        )

    async def revoke_token(self, access_token: str) -> None:
        """Best-effort permission revocation — does not raise on failure."""
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                await client.delete(
                    f"{_GRAPH_BASE}/me/permissions",
                    params=self._auth_params(access_token),
                )
        except Exception:
            pass  # best-effort; failure is acceptable

    # ── Internal OAuth helpers ────────────────────────────────────────────────

    async def _exchange_code_for_short_lived(self, code: str, redirect_uri: str) -> str:
        """Exchange auth code for a short-lived user access token."""
        params = {
            "client_id":     self._app_id,
            "client_secret": self._app_secret,
            "code":          code,
            "redirect_uri":  redirect_uri,
        }
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.get(_TOKEN_URL, params=params)
                resp.raise_for_status()
                body = resp.json()
        except httpx.HTTPStatusError as exc:
            try:
                err_dict = exc.response.json().get("error", {})
            except Exception:
                err_dict = {}
            self._raise_for_graph_error(err_dict, exc.response.status_code)
            raise RuntimeError(f"Instagram token exchange HTTP {exc.response.status_code}") from exc
        except httpx.RequestError as exc:
            raise RuntimeError(f"Instagram token exchange network error: {exc}") from exc

        if "error" in body:
            self._raise_for_graph_error(body["error"])
        return body["access_token"]

    async def _exchange_for_long_lived(self, token: str) -> tuple[str, int]:
        """Exchange any token for a long-lived one via fb_exchange_token grant.

        Returns (access_token, expires_in_seconds).
        Raises InstagramTokenExpiredError if token can no longer be extended.
        """
        params = {
            "grant_type":        "fb_exchange_token",
            "client_id":         self._app_id,
            "client_secret":     self._app_secret,
            "fb_exchange_token": token,
        }
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.get(_TOKEN_URL, params=params)
                resp.raise_for_status()
                body = resp.json()
        except httpx.HTTPStatusError as exc:
            try:
                err_dict = exc.response.json().get("error", {})
            except Exception:
                err_dict = {}
            self._raise_for_graph_error(err_dict, exc.response.status_code)
            raise RuntimeError(f"Instagram token extend HTTP {exc.response.status_code}") from exc
        except httpx.RequestError as exc:
            raise RuntimeError(f"Instagram token extend network error: {exc}") from exc

        if "error" in body:
            self._raise_for_graph_error(body["error"])
        return body["access_token"], int(body.get("expires_in", 5184000))

    async def _fetch_ig_user(
        self,
        access_token: str,
    ) -> tuple[str, str | None, str | None, str | None]:
        """Fetch the Instagram Professional account linked to the user's Facebook Pages.

        Returns (ig_user_id, username, display_name, avatar_url).
        Raises InstagramAPIError if no IG Professional account is found.
        """
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.get(
                    f"{_GRAPH_BASE}/me/accounts",
                    params={
                        "fields": "instagram_business_account{id,username,name,profile_picture_url}",
                        **self._auth_params(access_token),
                    },
                )
                resp.raise_for_status()
                body = resp.json()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(f"Instagram /me/accounts HTTP {exc.response.status_code}") from exc
        except httpx.RequestError as exc:
            raise RuntimeError(f"Instagram /me/accounts network error: {exc}") from exc

        if "error" in body:
            self._raise_for_graph_error(body["error"])

        for page in body.get("data", []):
            ig = page.get("instagram_business_account")
            if ig and ig.get("id"):
                return (
                    ig["id"],
                    ig.get("username"),
                    ig.get("name"),
                    ig.get("profile_picture_url"),
                )

        raise InstagramAPIError(
            "no_ig_business_account",
            "No Instagram Professional account found linked to this Facebook account. "
            "Connect an Instagram Business or Creator account to a Facebook Page first.",
        )

    # ── Account info ──────────────────────────────────────────────────────────

    async def get_account_info(
        self,
        access_token: str,
        platform_user_id: str,
    ) -> dict[str, Any]:
        """Fetch live account metadata from the Instagram Graph API."""
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.get(
                    f"{_GRAPH_BASE}/{platform_user_id}",
                    params={
                        "fields": "id,username,name,profile_picture_url,followers_count,media_count",
                        **self._auth_params(access_token),
                    },
                )
                resp.raise_for_status()
                body = resp.json()
        except Exception as exc:
            log.warning("instagram account_info failed ig_user_id=%s: %s", platform_user_id, exc)
            return {"platform_user_id": platform_user_id}

        if "error" in body:
            log.warning("instagram account_info error ig_user_id=%s: %s", platform_user_id, body["error"])
            return {"platform_user_id": platform_user_id}

        return {
            "platform_user_id": platform_user_id,
            "username":         body.get("username"),
            "display_name":     body.get("name"),
            "avatar_url":       body.get("profile_picture_url"),
            "followers_count":  body.get("followers_count"),
            "media_count":      body.get("media_count"),
        }

    # ── Publishing ────────────────────────────────────────────────────────────

    async def publish_video(self, request: PublishRequest) -> PublishResult:
        """Create an Instagram Reels upload container (step 1 of 3).

        The container is created asynchronously — Instagram fetches the video
        from request.video_url.  Returns PROCESSING immediately with
        publish_id = "{ig_user_id}|{container_id}".

        Call get_publish_status() to advance from container → published.

        Options supported (via request.options):
            share_to_feed:  bool — also show in main feed (default True)
            cover_url:      str  — custom thumbnail URL

        Raises:
            InstagramTokenExpiredError  — token needs refresh
            InstagramRateLimitError     — rate limit; retry_after seconds
            InstagramRetryableError     — transient; safe to retry
            InstagramAPIError           — permanent; do not retry
            RuntimeError               — network error
        """
        opts = request.options or {}

        tags_str = " ".join(f"#{t.lstrip('#')}" for t in request.hashtags) if request.hashtags else ""
        caption  = f"{request.caption} {tags_str}".strip()[:2200]

        params: dict[str, Any] = {
            "media_type":    "REELS",
            "video_url":     request.video_url,
            "caption":       caption,
            "share_to_feed": str(opts.get("share_to_feed", True)).lower(),
            **self._auth_params(request.access_token),
        }
        if opts.get("cover_url"):
            params["cover_url"] = opts["cover_url"]

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(
                    f"{_GRAPH_BASE}/{request.platform_user_id}/media",
                    data=params,
                )
                resp.raise_for_status()
                body = resp.json()
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            try:
                err_dict = exc.response.json().get("error", {})
            except Exception:
                err_dict = {}
            self._raise_for_graph_error(err_dict, status_code)
            log.error("instagram container_create HTTP %s ig_user_id=%s", status_code, request.platform_user_id)
            raise RuntimeError(f"Instagram API returned HTTP {status_code}") from exc
        except httpx.RequestError as exc:
            log.error("instagram container_create network error ig_user_id=%s: %s", request.platform_user_id, exc)
            raise RuntimeError(f"Instagram network error: {exc}") from exc

        if "error" in body:
            self._raise_for_graph_error(body["error"])

        container_id = body.get("id", "")
        if not container_id:
            raise InstagramAPIError("missing_container_id", "Instagram returned no container id")

        publish_id = f"{request.platform_user_id}|{container_id}"
        log.info(
            "instagram container_created ig_user_id=%s container_id=%s",
            request.platform_user_id, container_id,
        )
        return PublishResult(
            platform_publish_id = publish_id,
            status              = PublishStatus.PROCESSING,
            metadata            = {"ig_container_id": container_id},
        )

    async def get_publish_status(
        self,
        publish_id: str,
        access_token: str,
    ) -> PublishStatusResult:
        """Poll and advance the Instagram publish workflow.

        Publish ID transitions:
            "{ig_user_id}|{container_id}" → PROCESSING while container uploads
            "{ig_user_id}|{container_id}" → calls media_publish when FINISHED
            "{ig_media_id}"               → COMPLETED after media_publish succeeds

        Raises:
            InstagramTokenExpiredError  — token needs refresh
            InstagramRateLimitError     — slow down
            InstagramRetryableError     — transient
            InstagramAPIError           — permanent error
            RuntimeError               — network error
        """
        if "|" in publish_id:
            ig_user_id, container_id = publish_id.split("|", 1)
            return await self._poll_and_publish_container(
                ig_user_id, container_id, publish_id, access_token
            )
        # Already published — bare ig_media_id
        return await self._fetch_published_status(publish_id, access_token)

    async def _poll_and_publish_container(
        self,
        ig_user_id: str,
        container_id: str,
        original_publish_id: str,
        access_token: str,
    ) -> PublishStatusResult:
        """Check container upload status and call media_publish when ready."""
        container_status = await self._get_container_status(container_id, access_token)

        if container_status in _CONTAINER_TERMINAL_FAILED:
            log.warning(
                "instagram container FAILED ig_user_id=%s container_id=%s status=%s",
                ig_user_id, container_id, container_status,
            )
            return PublishStatusResult(
                platform_publish_id = original_publish_id,
                status              = PublishStatus.FAILED,
                error_code          = container_status.lower(),
                error_message       = f"Instagram container upload {container_status.lower()}",
                metadata            = {"ig_container_status": container_status},
            )

        if container_status not in _CONTAINER_TERMINAL_DONE:
            # Still uploading (NOT_STARTED, IN_PROGRESS, SCHEDULED, …)
            return PublishStatusResult(
                platform_publish_id = original_publish_id,
                status              = PublishStatus.PROCESSING,
                metadata            = {"ig_container_status": container_status},
            )

        # FINISHED — trigger media_publish
        ig_media_id  = await self._media_publish(ig_user_id, container_id, access_token)
        platform_url = await self._fetch_media_permalink(ig_media_id, access_token)

        log.info(
            "instagram published ig_user_id=%s ig_media_id=%s",
            ig_user_id, ig_media_id,
        )
        return PublishStatusResult(
            platform_publish_id = ig_media_id,  # transitions: container_id → media_id
            status              = PublishStatus.COMPLETED,
            platform_url        = platform_url,
            metadata            = {
                "ig_container_id": container_id,
                "ig_media_id":     ig_media_id,
            },
        )

    async def _get_container_status(self, container_id: str, access_token: str) -> str:
        """Fetch the current upload status_code of a media container."""
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.get(
                    f"{_GRAPH_BASE}/{container_id}",
                    params={"fields": "status_code", **self._auth_params(access_token)},
                )
                resp.raise_for_status()
                body = resp.json()
        except httpx.HTTPStatusError as exc:
            try:
                err_dict = exc.response.json().get("error", {})
            except Exception:
                err_dict = {}
            self._raise_for_graph_error(err_dict, exc.response.status_code)
            raise RuntimeError(f"Instagram container status HTTP {exc.response.status_code}") from exc
        except httpx.RequestError as exc:
            raise RuntimeError(f"Instagram container status network error: {exc}") from exc

        if "error" in body:
            self._raise_for_graph_error(body["error"])
        return (body.get("status_code") or "IN_PROGRESS").upper()

    async def _media_publish(
        self,
        ig_user_id: str,
        container_id: str,
        access_token: str,
    ) -> str:
        """Call /{ig_user_id}/media_publish to finalize publication.

        Returns ig_media_id.
        """
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(
                    f"{_GRAPH_BASE}/{ig_user_id}/media_publish",
                    data={"creation_id": container_id, **self._auth_params(access_token)},
                )
                resp.raise_for_status()
                body = resp.json()
        except httpx.HTTPStatusError as exc:
            try:
                err_dict = exc.response.json().get("error", {})
            except Exception:
                err_dict = {}
            self._raise_for_graph_error(err_dict, exc.response.status_code)
            raise RuntimeError(f"Instagram media_publish HTTP {exc.response.status_code}") from exc
        except httpx.RequestError as exc:
            raise RuntimeError(f"Instagram media_publish network error: {exc}") from exc

        if "error" in body:
            self._raise_for_graph_error(body["error"])

        ig_media_id = body.get("id", "")
        if not ig_media_id:
            raise InstagramAPIError("missing_media_id", "Instagram media_publish returned no id")
        return ig_media_id

    async def _fetch_media_permalink(self, ig_media_id: str, access_token: str) -> str | None:
        """Fetch the public permalink for a published Instagram media item.

        Returns None on any error — non-blocking, the post is already published.
        """
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.get(
                    f"{_GRAPH_BASE}/{ig_media_id}",
                    params={"fields": "permalink", **self._auth_params(access_token)},
                )
                resp.raise_for_status()
                body = resp.json()
            return body.get("permalink")
        except Exception as exc:
            log.warning("instagram fetch_permalink failed ig_media_id=%s: %s", ig_media_id, exc)
            return None

    async def _fetch_published_status(
        self,
        ig_media_id: str,
        access_token: str,
    ) -> PublishStatusResult:
        """Return COMPLETED for an already-published media item (bare ig_media_id)."""
        platform_url = await self._fetch_media_permalink(ig_media_id, access_token)
        return PublishStatusResult(
            platform_publish_id = ig_media_id,
            status              = PublishStatus.COMPLETED,
            platform_url        = platform_url,
            metadata            = {"ig_media_id": ig_media_id},
        )
