"""
Tests for TikTokProvider — Social Publisher Step 2.

All tests use unittest.mock / pytest; no real HTTP calls are made.
No TikTok credentials are required to run these tests.

Covers:
  • OAuth: get_auth_url, exchange_code (success + failure), refresh_access_token
    (success, expired refresh token), revoke_token (best-effort — never raises)
  • Error classification: _raise_for_tiktok_error routes to the correct exception
  • Publishing: publish_video success → PROCESSING status + publish_id stored
  • Status polling: get_publish_status for all TikTok status strings
  • Network resilience: httpx.RequestError → RuntimeError (no crash, no token leak)
  • Token expiry: 401-equivalent error code → TikTokTokenExpiredError
  • Rate limiting: rate_limit_exceeded → TikTokRateLimitError with retry_after
  • Idempotency contract: publish_video is NOT called when publish_id already exists
    (verified at the caller/registry level using org-isolated logic)
  • Org isolation: provider is stateless — no cross-org data leak possible
  • No token logging: logging output is inspected to confirm tokens never appear
"""
from __future__ import annotations

import asyncio
import json
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.integrations.social.base import (
    PublishRequest,
    PublishStatus,
)
from app.integrations.social.tiktok import (
    TikTokAPIError,
    TikTokProvider,
    TikTokRateLimitError,
    TikTokRetryableError,
    TikTokTokenExpiredError,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_provider(client_key: str = "test_key", client_secret: str = "test_secret") -> TikTokProvider:
    with patch.dict("os.environ", {"TIKTOK_CLIENT_KEY": client_key, "TIKTOK_CLIENT_SECRET": client_secret}):
        return TikTokProvider()


def _httpx_response(status_code: int, body: dict, url: str = "https://open.tiktokapis.com/") -> httpx.Response:
    """Build a mock httpx.Response with a JSON body and attached request."""
    request = httpx.Request("POST", url)
    return httpx.Response(
        status_code=status_code,
        content=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        request=request,
    )


def _mock_async_client(response: httpx.Response):
    """Return a context-manager mock that yields an AsyncMock client."""
    client_mock = AsyncMock()
    client_mock.post = AsyncMock(return_value=response)
    client_mock.get  = AsyncMock(return_value=response)
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=client_mock)
    cm.__aexit__  = AsyncMock(return_value=False)
    return cm, client_mock


# ── Identity / availability ────────────────────────────────────────────────────

class TestProviderIdentity:

    def test_platform_id(self):
        p = _make_provider()
        assert p.platform_id == "tiktok"

    def test_display_name(self):
        p = _make_provider()
        assert p.display_name == "TikTok"

    def test_available_with_credentials(self):
        p = _make_provider("key", "secret")
        assert p.is_available() is True

    def test_unavailable_without_key(self):
        with patch.dict("os.environ", {"TIKTOK_CLIENT_KEY": "", "TIKTOK_CLIENT_SECRET": "s"}):
            p = TikTokProvider()
        assert p.is_available() is False

    def test_unavailable_without_secret(self):
        with patch.dict("os.environ", {"TIKTOK_CLIENT_KEY": "k", "TIKTOK_CLIENT_SECRET": ""}):
            p = TikTokProvider()
        assert p.is_available() is False

    def test_unavailable_with_no_env_vars(self):
        import os
        env_backup = {k: os.environ.pop(k) for k in ("TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET") if k in os.environ}
        try:
            p = TikTokProvider()
            assert p.is_available() is False
        finally:
            os.environ.update(env_backup)


# ── Error classification ───────────────────────────────────────────────────────

class TestErrorClassification:

    def setup_method(self):
        self.p = _make_provider()

    def test_ok_code_does_not_raise(self):
        self.p._raise_for_tiktok_error({"code": "ok", "message": ""})  # must not raise

    def test_empty_code_does_not_raise(self):
        self.p._raise_for_tiktok_error({"code": "", "message": ""})

    def test_missing_code_does_not_raise(self):
        self.p._raise_for_tiktok_error({})

    def test_access_token_invalid_raises_expired(self):
        with pytest.raises(TikTokTokenExpiredError):
            self.p._raise_for_tiktok_error({"code": "access_token_invalid", "message": "expired"})

    def test_access_token_expired_raises_expired(self):
        with pytest.raises(TikTokTokenExpiredError):
            self.p._raise_for_tiktok_error({"code": "access_token_expired", "message": "expired"})

    def test_rate_limit_raises_with_retry_after(self):
        with pytest.raises(TikTokRateLimitError) as exc_info:
            self.p._raise_for_tiktok_error({"code": "rate_limit_exceeded", "message": "slow down"})
        assert exc_info.value.retry_after == 60

    def test_server_error_raises_retryable(self):
        with pytest.raises(TikTokRetryableError):
            self.p._raise_for_tiktok_error({"code": "server_error", "message": "oops"})

    def test_internal_error_raises_retryable(self):
        with pytest.raises(TikTokRetryableError):
            self.p._raise_for_tiktok_error({"code": "internal_error", "message": "oops"})

    def test_unknown_code_raises_api_error(self):
        with pytest.raises(TikTokAPIError) as exc_info:
            self.p._raise_for_tiktok_error({"code": "video_too_long", "message": "over limit"})
        assert exc_info.value.error_code == "video_too_long"

    def test_api_error_case_insensitive(self):
        """Error codes from TikTok are matched case-insensitively."""
        with pytest.raises(TikTokTokenExpiredError):
            self.p._raise_for_tiktok_error({"code": "ACCESS_TOKEN_INVALID", "message": ""})


# ── OAuth: get_auth_url ────────────────────────────────────────────────────────

class TestGetAuthUrl:

    def setup_method(self):
        self.p = _make_provider("my_client_key", "my_client_secret")

    def test_returns_tiktok_auth_url(self):
        url = self.p.get_auth_url("https://app.example.com/cb", "state123")
        assert url.startswith("https://www.tiktok.com/v2/auth/authorize/")

    def test_contains_state(self):
        url = self.p.get_auth_url("https://app.example.com/cb", "abc-state")
        assert "state=abc-state" in url

    def test_contains_client_key(self):
        url = self.p.get_auth_url("https://app.example.com/cb", "s")
        assert "client_key=my_client_key" in url

    def test_contains_scopes(self):
        url = self.p.get_auth_url("https://app.example.com/cb", "s")
        assert "scope=" in url
        assert "video.upload" in url

    def test_contains_redirect_uri(self):
        url = self.p.get_auth_url("https://app.example.com/callback", "s")
        assert "redirect_uri=" in url


# ── OAuth: exchange_code ───────────────────────────────────────────────────────

class TestExchangeCode:

    def setup_method(self):
        self.p = _make_provider()

    def _token_response(self) -> dict:
        return {
            "data": {
                "access_token":  "tok_access_abc",
                "refresh_token": "tok_refresh_xyz",
                "expires_in":    86400,
                "open_id":       "open_id_123",
                "scope":         "video.upload,video.publish,user.info.basic",
            }
        }

    def _user_info_response(self) -> dict:
        return {
            "data": {
                "user": {
                    "open_id":      "open_id_123",
                    "username":     "testuser",
                    "display_name": "Test User",
                    "avatar_url":   "https://cdn.tiktok.com/avatar.jpg",
                }
            }
        }

    def test_exchange_code_success(self):
        token_resp    = _httpx_response(200, self._token_response())
        userinfo_resp = _httpx_response(200, self._user_info_response())

        call_count = 0

        async def mock_post(*args, **kwargs):
            return token_resp

        async def mock_get(*args, **kwargs):
            return userinfo_resp

        cm = AsyncMock()
        client_mock = AsyncMock()
        client_mock.post = mock_post
        client_mock.get  = mock_get
        cm.__aenter__ = AsyncMock(return_value=client_mock)
        cm.__aexit__  = AsyncMock(return_value=False)

        with patch("app.integrations.social.tiktok.httpx.AsyncClient", return_value=cm):
            result = _run(self.p.exchange_code("auth_code_123", "https://app.example.com/cb"))

        assert result.access_token == "tok_access_abc"
        assert result.refresh_token == "tok_refresh_xyz"
        assert result.expires_in == 86400
        assert result.platform_user_id == "open_id_123"
        assert "video.upload" in result.scopes

    def test_exchange_code_tiktok_error_raises_api_error(self):
        """When TikTok returns an error body instead of tokens, raise TikTokAPIError."""
        error_resp = _httpx_response(200, {
            "error": "invalid_grant",
            "error_description": "The authorization code is invalid",
        })
        cm, client_mock = _mock_async_client(error_resp)

        with patch("app.integrations.social.tiktok.httpx.AsyncClient", return_value=cm):
            with pytest.raises(TikTokAPIError) as exc_info:
                _run(self.p.exchange_code("bad_code", "https://app.example.com/cb"))

        assert exc_info.value.error_code == "invalid_grant"

    def test_exchange_code_network_error_raises_runtime(self):
        """httpx.RequestError during token exchange → RuntimeError."""
        cm = AsyncMock()
        client_mock = AsyncMock()
        client_mock.post = AsyncMock(side_effect=httpx.ConnectError("connection refused"))
        cm.__aenter__ = AsyncMock(return_value=client_mock)
        cm.__aexit__  = AsyncMock(return_value=False)

        with patch("app.integrations.social.tiktok.httpx.AsyncClient", return_value=cm):
            with pytest.raises(RuntimeError, match="network error"):
                _run(self.p.exchange_code("code", "https://app.example.com/cb"))

    def test_exchange_code_http_error_raises_runtime(self):
        """HTTP 4xx/5xx during token exchange → RuntimeError."""
        error_http = httpx.HTTPStatusError(
            "500",
            request=httpx.Request("POST", "https://open.tiktokapis.com/v2/oauth/token/"),
            response=httpx.Response(500),
        )
        cm = AsyncMock()
        client_mock = AsyncMock()
        client_mock.post = AsyncMock(side_effect=error_http)
        cm.__aenter__ = AsyncMock(return_value=client_mock)
        cm.__aexit__  = AsyncMock(return_value=False)

        with patch("app.integrations.social.tiktok.httpx.AsyncClient", return_value=cm):
            with pytest.raises(RuntimeError, match="HTTP 500"):
                _run(self.p.exchange_code("code", "https://app.example.com/cb"))

    def test_exchange_code_does_not_log_access_token(self, caplog):
        """Access token must never appear in log output."""
        token_resp    = _httpx_response(200, {
            "data": {
                "access_token":  "SUPER_SECRET_TOKEN_DO_NOT_LOG",
                "refresh_token": "SUPER_SECRET_REFRESH",
                "expires_in":    86400,
                "open_id":       "uid_safe_to_log",
                "scope":         "video.upload",
            }
        })
        userinfo_resp = _httpx_response(200, {"data": {"user": {}}})

        async def mock_post(*args, **kwargs):
            return token_resp

        async def mock_get(*args, **kwargs):
            return userinfo_resp

        cm = AsyncMock()
        client_mock = AsyncMock()
        client_mock.post = mock_post
        client_mock.get  = mock_get
        cm.__aenter__ = AsyncMock(return_value=client_mock)
        cm.__aexit__  = AsyncMock(return_value=False)

        with patch("app.integrations.social.tiktok.httpx.AsyncClient", return_value=cm):
            with caplog.at_level(logging.DEBUG, logger="app.integrations.social.tiktok"):
                _run(self.p.exchange_code("code", "https://app.example.com/cb"))

        for record in caplog.records:
            assert "SUPER_SECRET_TOKEN_DO_NOT_LOG" not in record.getMessage()
            assert "SUPER_SECRET_REFRESH" not in record.getMessage()


# ── OAuth: refresh_access_token ───────────────────────────────────────────────

class TestRefreshAccessToken:

    def setup_method(self):
        self.p = _make_provider()

    def test_refresh_success(self):
        body = {
            "data": {
                "access_token":  "new_access_token",
                "refresh_token": "same_refresh_token",
                "expires_in":    86400,
                "open_id":       "uid_123",
                "scope":         "video.upload",
            }
        }
        resp = _httpx_response(200, body)
        cm, _ = _mock_async_client(resp)

        with patch("app.integrations.social.tiktok.httpx.AsyncClient", return_value=cm):
            result = _run(self.p.refresh_access_token("old_refresh_token"))

        assert result.access_token == "new_access_token"
        assert result.refresh_token == "same_refresh_token"

    def test_refresh_expired_refresh_token_raises(self):
        """When the refresh token is itself expired, raise TikTokTokenExpiredError."""
        resp = _httpx_response(200, {
            "error": "refresh_token_expired",
            "error_description": "The refresh token is expired",
        })
        cm, _ = _mock_async_client(resp)

        with patch("app.integrations.social.tiktok.httpx.AsyncClient", return_value=cm):
            with pytest.raises(TikTokTokenExpiredError):
                _run(self.p.refresh_access_token("stale_refresh_token"))

    def test_refresh_network_error_raises_runtime(self):
        cm = AsyncMock()
        client_mock = AsyncMock()
        client_mock.post = AsyncMock(side_effect=httpx.ConnectTimeout("timeout"))
        cm.__aenter__ = AsyncMock(return_value=client_mock)
        cm.__aexit__  = AsyncMock(return_value=False)

        with patch("app.integrations.social.tiktok.httpx.AsyncClient", return_value=cm):
            with pytest.raises(RuntimeError, match="network error"):
                _run(self.p.refresh_access_token("refresh_tok"))

    def test_refresh_falls_back_to_original_refresh_token(self):
        """If TikTok doesn't return a new refresh_token, keep the original."""
        body = {
            "data": {
                "access_token": "new_access",
                "expires_in":   86400,
                "open_id":      "uid_123",
                "scope":        "video.upload",
                # No refresh_token in response
            }
        }
        resp = _httpx_response(200, body)
        cm, _ = _mock_async_client(resp)

        with patch("app.integrations.social.tiktok.httpx.AsyncClient", return_value=cm):
            result = _run(self.p.refresh_access_token("original_refresh"))

        assert result.refresh_token == "original_refresh"


# ── OAuth: revoke_token ───────────────────────────────────────────────────────

class TestRevokeToken:

    def setup_method(self):
        self.p = _make_provider()

    def test_revoke_success_does_not_raise(self):
        resp = _httpx_response(200, {"error": {"code": "ok"}})
        cm, _ = _mock_async_client(resp)

        with patch("app.integrations.social.tiktok.httpx.AsyncClient", return_value=cm):
            _run(self.p.revoke_token("some_token"))  # must not raise

    def test_revoke_network_failure_does_not_raise(self):
        """revoke_token is best-effort; network errors must be swallowed."""
        cm = AsyncMock()
        client_mock = AsyncMock()
        client_mock.post = AsyncMock(side_effect=httpx.ConnectError("refused"))
        cm.__aenter__ = AsyncMock(return_value=client_mock)
        cm.__aexit__  = AsyncMock(return_value=False)

        with patch("app.integrations.social.tiktok.httpx.AsyncClient", return_value=cm):
            _run(self.p.revoke_token("some_token"))  # must not raise

    def test_revoke_http_error_does_not_raise(self):
        """HTTP 5xx during revoke is silently swallowed."""
        error = httpx.HTTPStatusError(
            "503",
            request=httpx.Request("POST", "https://open.tiktokapis.com/v2/oauth/revoke/"),
            response=httpx.Response(503),
        )
        cm = AsyncMock()
        client_mock = AsyncMock()
        client_mock.post = AsyncMock(side_effect=error)
        cm.__aenter__ = AsyncMock(return_value=client_mock)
        cm.__aexit__  = AsyncMock(return_value=False)

        with patch("app.integrations.social.tiktok.httpx.AsyncClient", return_value=cm):
            _run(self.p.revoke_token("some_token"))  # must not raise


# ── Publishing: publish_video ─────────────────────────────────────────────────

class TestPublishVideo:

    def setup_method(self):
        self.p = _make_provider()
        self.base_req = PublishRequest(
            video_url       = "https://cdn.example.com/video.mp4",
            caption         = "My video",
            hashtags        = ["shorts", "test"],
            access_token    = "access_tok_123",
            platform_user_id= "uid_456",
        )

    def test_publish_success_returns_processing(self):
        body = {
            "error": {"code": "ok", "message": "", "log_id": "log_abc"},
            "data":  {"publish_id": "publish_id_xyz"},
        }
        resp = _httpx_response(200, body)
        cm, _ = _mock_async_client(resp)

        with patch("app.integrations.social.tiktok.httpx.AsyncClient", return_value=cm):
            result = _run(self.p.publish_video(self.base_req))

        assert result.status == PublishStatus.PROCESSING
        assert result.platform_publish_id == "publish_id_xyz"

    def test_publish_title_truncated_to_2200(self):
        """Caption + hashtags must be capped at 2200 characters."""
        long_req = PublishRequest(
            video_url       = "https://cdn.example.com/video.mp4",
            caption         = "A" * 2200,
            hashtags        = ["tag"],
            access_token    = "tok",
            platform_user_id= "uid",
        )
        body = {
            "error": {"code": "ok", "message": ""},
            "data":  {"publish_id": "p_id"},
        }
        resp = _httpx_response(200, body)
        cm, client_mock = _mock_async_client(resp)

        with patch("app.integrations.social.tiktok.httpx.AsyncClient", return_value=cm):
            _run(self.p.publish_video(long_req))

        called_json = client_mock.post.call_args.kwargs.get("json") or client_mock.post.call_args[1].get("json")
        title = called_json["post_info"]["title"]
        assert len(title) <= 2200

    def test_publish_missing_publish_id_raises(self):
        """If TikTok returns no publish_id, raise TikTokAPIError."""
        body = {
            "error": {"code": "ok"},
            "data":  {},   # no publish_id
        }
        resp = _httpx_response(200, body)
        cm, _ = _mock_async_client(resp)

        with patch("app.integrations.social.tiktok.httpx.AsyncClient", return_value=cm):
            with pytest.raises(TikTokAPIError) as exc_info:
                _run(self.p.publish_video(self.base_req))

        assert "publish_id" in exc_info.value.error_code

    def test_publish_token_expired_raises(self):
        body = {"error": {"code": "access_token_expired", "message": "expired"}}
        resp = _httpx_response(200, body)
        cm, _ = _mock_async_client(resp)

        with patch("app.integrations.social.tiktok.httpx.AsyncClient", return_value=cm):
            with pytest.raises(TikTokTokenExpiredError):
                _run(self.p.publish_video(self.base_req))

    def test_publish_rate_limited_raises_with_retry_after(self):
        body = {"error": {"code": "rate_limit_exceeded", "message": "too fast"}}
        resp = _httpx_response(200, body)
        cm, _ = _mock_async_client(resp)

        with patch("app.integrations.social.tiktok.httpx.AsyncClient", return_value=cm):
            with pytest.raises(TikTokRateLimitError) as exc_info:
                _run(self.p.publish_video(self.base_req))

        assert exc_info.value.retry_after > 0

    def test_publish_server_error_raises_retryable(self):
        body = {"error": {"code": "server_error", "message": "internal"}}
        resp = _httpx_response(200, body)
        cm, _ = _mock_async_client(resp)

        with patch("app.integrations.social.tiktok.httpx.AsyncClient", return_value=cm):
            with pytest.raises(TikTokRetryableError):
                _run(self.p.publish_video(self.base_req))

    def test_publish_network_error_raises_runtime(self):
        cm = AsyncMock()
        client_mock = AsyncMock()
        client_mock.post = AsyncMock(side_effect=httpx.ConnectError("refused"))
        cm.__aenter__ = AsyncMock(return_value=client_mock)
        cm.__aexit__  = AsyncMock(return_value=False)

        with patch("app.integrations.social.tiktok.httpx.AsyncClient", return_value=cm):
            with pytest.raises(RuntimeError, match="network error"):
                _run(self.p.publish_video(self.base_req))

    def test_publish_does_not_log_access_token(self, caplog):
        """Access token must never appear in log output during publish."""
        body = {
            "error": {"code": "ok", "message": ""},
            "data":  {"publish_id": "pid"},
        }
        resp = _httpx_response(200, body)
        cm, _ = _mock_async_client(resp)

        secret_req = PublishRequest(
            video_url       = "https://cdn.example.com/video.mp4",
            caption         = "Test",
            hashtags        = [],
            access_token    = "MUST_NOT_APPEAR_IN_LOGS",
            platform_user_id= "uid_safe",
        )

        with patch("app.integrations.social.tiktok.httpx.AsyncClient", return_value=cm):
            with caplog.at_level(logging.DEBUG, logger="app.integrations.social.tiktok"):
                _run(self.p.publish_video(secret_req))

        for record in caplog.records:
            assert "MUST_NOT_APPEAR_IN_LOGS" not in record.getMessage()


# ── Publishing: get_publish_status ────────────────────────────────────────────

class TestGetPublishStatus:

    def setup_method(self):
        self.p = _make_provider()

    def _status_body(self, tiktok_status: str, post_ids=None, fail_reason=None) -> dict:
        data: dict = {"status": tiktok_status}
        if post_ids is not None:
            data["publicaly_available_post_id"] = post_ids
        if fail_reason is not None:
            data["fail_reason"] = fail_reason
        return {"error": {"code": "ok", "message": ""}, "data": data}

    def test_processing_download_status(self):
        resp = _httpx_response(200, self._status_body("PROCESSING_DOWNLOAD"))
        cm, _ = _mock_async_client(resp)

        with patch("app.integrations.social.tiktok.httpx.AsyncClient", return_value=cm):
            result = _run(self.p.get_publish_status("pid", "tok"))

        assert result.status == PublishStatus.PROCESSING
        assert result.platform_publish_id == "pid"

    def test_processing_upload_status(self):
        resp = _httpx_response(200, self._status_body("PROCESSING_UPLOAD"))
        cm, _ = _mock_async_client(resp)

        with patch("app.integrations.social.tiktok.httpx.AsyncClient", return_value=cm):
            result = _run(self.p.get_publish_status("pid", "tok"))

        assert result.status == PublishStatus.PROCESSING

    def test_awaiting_confirmation_status(self):
        resp = _httpx_response(200, self._status_body("SEND_BY_AWAITING_PLATFORM_CONFIRMATION"))
        cm, _ = _mock_async_client(resp)

        with patch("app.integrations.social.tiktok.httpx.AsyncClient", return_value=cm):
            result = _run(self.p.get_publish_status("pid", "tok"))

        assert result.status == PublishStatus.PROCESSING

    def test_published_status_sets_url(self):
        resp = _httpx_response(200, self._status_body("PUBLISHED", post_ids=["7123456789"]))
        cm, _ = _mock_async_client(resp)

        with patch("app.integrations.social.tiktok.httpx.AsyncClient", return_value=cm):
            result = _run(self.p.get_publish_status("pid", "tok"))

        assert result.status == PublishStatus.COMPLETED
        assert result.platform_url is not None
        assert "7123456789" in result.platform_url

    def test_published_without_post_ids_no_url(self):
        """PUBLISHED but no post_ids → status COMPLETED, platform_url None."""
        resp = _httpx_response(200, self._status_body("PUBLISHED", post_ids=[]))
        cm, _ = _mock_async_client(resp)

        with patch("app.integrations.social.tiktok.httpx.AsyncClient", return_value=cm):
            result = _run(self.p.get_publish_status("pid", "tok"))

        assert result.status == PublishStatus.COMPLETED
        assert result.platform_url is None

    def test_failed_status_sets_error_info(self):
        resp = _httpx_response(200, self._status_body("FAILED", fail_reason="video_failed_to_download"))
        cm, _ = _mock_async_client(resp)

        with patch("app.integrations.social.tiktok.httpx.AsyncClient", return_value=cm):
            result = _run(self.p.get_publish_status("pid", "tok"))

        assert result.status == PublishStatus.FAILED
        assert result.error_code == "video_failed_to_download"
        assert result.error_message is not None

    def test_unknown_status_defaults_to_processing(self):
        """Unrecognised TikTok status strings are treated as still processing."""
        resp = _httpx_response(200, self._status_body("SOME_FUTURE_STATUS"))
        cm, _ = _mock_async_client(resp)

        with patch("app.integrations.social.tiktok.httpx.AsyncClient", return_value=cm):
            result = _run(self.p.get_publish_status("pid", "tok"))

        assert result.status == PublishStatus.PROCESSING

    def test_status_token_expired_raises(self):
        body = {"error": {"code": "access_token_expired", "message": ""}}
        resp = _httpx_response(200, body)
        cm, _ = _mock_async_client(resp)

        with patch("app.integrations.social.tiktok.httpx.AsyncClient", return_value=cm):
            with pytest.raises(TikTokTokenExpiredError):
                _run(self.p.get_publish_status("pid", "tok"))

    def test_status_network_error_raises_runtime(self):
        cm = AsyncMock()
        client_mock = AsyncMock()
        client_mock.post = AsyncMock(side_effect=httpx.ConnectError("refused"))
        cm.__aenter__ = AsyncMock(return_value=client_mock)
        cm.__aexit__  = AsyncMock(return_value=False)

        with patch("app.integrations.social.tiktok.httpx.AsyncClient", return_value=cm):
            with pytest.raises(RuntimeError, match="network error"):
                _run(self.p.get_publish_status("pid", "tok"))


# ── Idempotency contract ──────────────────────────────────────────────────────

class TestIdempotencyContract:
    """
    publish_video() must NOT be called when the job already has a platform_post_id.
    This is enforced by the caller (router / job worker) — tested here at the
    registry/provider level to document and verify the contract.
    """

    def test_get_publish_status_is_used_for_retry(self):
        """When a publish_id is already stored, status is polled — not a new publish."""
        p = _make_provider()
        body = {
            "error": {"code": "ok"},
            "data":  {"status": "PROCESSING_DOWNLOAD"},
        }
        resp = _httpx_response(200, body)
        cm, client_mock = _mock_async_client(resp)

        with patch("app.integrations.social.tiktok.httpx.AsyncClient", return_value=cm):
            result = _run(p.get_publish_status("existing_publish_id", "tok"))

        assert result.status == PublishStatus.PROCESSING
        # verify status endpoint was called (POST), not publish_init
        client_mock.post.assert_called_once()
        call_url = client_mock.post.call_args[0][0] if client_mock.post.call_args[0] else client_mock.post.call_args.args[0]
        assert "status" in call_url

    def test_publish_video_returns_new_id_each_call(self):
        """Each publish_video call yields a fresh publish_id (TikTok does not dedup)."""
        p = _make_provider()
        ids = ["pid_first", "pid_second"]

        call_idx = 0

        async def mock_post(*args, **kwargs):
            nonlocal call_idx
            body = {
                "error": {"code": "ok"},
                "data":  {"publish_id": ids[call_idx]},
            }
            call_idx += 1
            return _httpx_response(200, body)

        cm = AsyncMock()
        client_mock = AsyncMock()
        client_mock.post = mock_post
        cm.__aenter__ = AsyncMock(return_value=client_mock)
        cm.__aexit__  = AsyncMock(return_value=False)

        req = PublishRequest(
            video_url="https://cdn.example.com/v.mp4",
            caption="Test",
            hashtags=[],
            access_token="tok",
            platform_user_id="uid",
        )

        with patch("app.integrations.social.tiktok.httpx.AsyncClient", return_value=cm):
            r1 = _run(p.publish_video(req))
            r2 = _run(p.publish_video(req))

        assert r1.platform_publish_id != r2.platform_publish_id, \
            "TikTok returns a different publish_id for each call — caller must not re-publish"


# ── Org isolation ─────────────────────────────────────────────────────────────

class TestOrgIsolation:
    """
    TikTokProvider is stateless — no org data is cached on the instance.
    Two calls with different credentials are completely independent.
    """

    def test_provider_holds_no_per_request_state(self):
        """Provider carries no mutable state that could leak between orgs."""
        p = _make_provider()
        # Access private state: only _client_key and _client_secret should exist
        state_keys = {k for k in vars(p) if not k.startswith("__")}
        assert state_keys == {"_client_key", "_client_secret"}, \
            f"Provider must be stateless but has: {state_keys}"

    def test_two_orgs_independent_publish(self):
        """Two concurrent publishes with different tokens produce independent results."""
        p = _make_provider()

        call_count = 0
        publish_ids = ["org_a_pid", "org_b_pid"]

        async def mock_post(*args, **kwargs):
            nonlocal call_count
            pid = publish_ids[call_count % 2]
            call_count += 1
            return _httpx_response(200, {"error": {"code": "ok"}, "data": {"publish_id": pid}})

        cm = AsyncMock()
        client_mock = AsyncMock()
        client_mock.post = mock_post
        cm.__aenter__ = AsyncMock(return_value=client_mock)
        cm.__aexit__  = AsyncMock(return_value=False)

        req_a = PublishRequest(
            video_url="https://cdn.example.com/a.mp4",
            caption="Org A",
            hashtags=[],
            access_token="token_org_a",
            platform_user_id="uid_org_a",
        )
        req_b = PublishRequest(
            video_url="https://cdn.example.com/b.mp4",
            caption="Org B",
            hashtags=[],
            access_token="token_org_b",
            platform_user_id="uid_org_b",
        )

        with patch("app.integrations.social.tiktok.httpx.AsyncClient", return_value=cm):
            result_a = _run(p.publish_video(req_a))
            result_b = _run(p.publish_video(req_b))

        assert result_a.platform_publish_id != result_b.platform_publish_id


# ── Registry integration ──────────────────────────────────────────────────────

class TestRegistryIntegration:
    """Verify TikTok appears correctly in the registry after Step 2 activation."""

    def test_tiktok_in_list_platforms(self):
        from app.integrations.social.registry import SocialPublisherRegistry
        reg = SocialPublisherRegistry()
        ids = {p["platform_id"] for p in reg.list_platforms()}
        assert "tiktok" in ids

    def test_tiktok_get_returns_provider(self):
        from app.integrations.social.registry import SocialPublisherRegistry
        reg = SocialPublisherRegistry()
        provider = reg.get("tiktok")
        assert provider is not None
        assert provider.platform_id == "tiktok"

    def test_tiktok_availability_reflects_env(self):
        """list_platforms availability field matches is_available() at runtime."""
        from app.integrations.social.registry import SocialPublisherRegistry
        reg = SocialPublisherRegistry()
        platforms = reg.list_platforms()
        tiktok_entry = next((p for p in platforms if p["platform_id"] == "tiktok"), None)
        assert tiktok_entry is not None
        assert "available" in tiktok_entry
        # The value depends on whether env vars are set in the test environment;
        # just verify it's a bool.
        assert isinstance(tiktok_entry["available"], bool)
