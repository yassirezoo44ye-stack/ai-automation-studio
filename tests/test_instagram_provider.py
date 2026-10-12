"""
Tests for InstagramProvider — Step 3: Instagram Reels via Meta Graph API.

Covers:
  • Provider identity and availability
  • Error classification (_raise_for_graph_error)
  • OAuth: get_auth_url, exchange_code, refresh_access_token, revoke_token
  • Publishing: publish_video (container creation)
  • Status polling: all container states + media_publish transition
  • Idempotency contract (publish_id lifecycle)
  • Org isolation (stateless provider)
  • Registry integration
"""
from __future__ import annotations

import asyncio
import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.integrations.social.base import (
    PublishRequest,
    PublishStatus,
)
from app.integrations.social.instagram import (
    InstagramAPIError,
    InstagramProvider,
    InstagramRateLimitError,
    InstagramRetryableError,
    InstagramTokenExpiredError,
    _GRAPH_BASE,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _run(coro):
    return asyncio.run(coro)


def _httpx_response(
    status_code: int,
    body: dict,
    url: str = "https://graph.facebook.com/",
    method: str = "GET",
) -> httpx.Response:
    """Build a mock httpx.Response with a JSON body and attached request."""
    request = httpx.Request(method, url)
    return httpx.Response(
        status_code=status_code,
        content=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        request=request,
    )


def _mock_client(*responses, method: str = "get") -> MagicMock:
    """Return a mock httpx.AsyncClient context manager that returns given responses.

    All responses are returned sequentially by the specified method.
    """
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    setattr(mock_client, method, AsyncMock(side_effect=list(responses)))
    return mock_client


def _provider_with_env() -> InstagramProvider:
    """Return an InstagramProvider with fake env vars set."""
    with patch.dict(os.environ, {"INSTAGRAM_APP_ID": "app123", "INSTAGRAM_APP_SECRET": "secret456"}):
        return InstagramProvider()


# ── Provider identity ─────────────────────────────────────────────────────────

class TestProviderIdentity:

    def test_platform_id(self):
        p = InstagramProvider()
        assert p.platform_id == "instagram"

    def test_display_name(self):
        p = InstagramProvider()
        assert p.display_name == "Instagram"

    def test_is_available_with_env_vars(self):
        with patch.dict(os.environ, {"INSTAGRAM_APP_ID": "app123", "INSTAGRAM_APP_SECRET": "sec"}):
            p = InstagramProvider()
        assert p.is_available() is True

    def test_is_available_missing_app_id(self):
        env = {"INSTAGRAM_APP_ID": "", "INSTAGRAM_APP_SECRET": "sec"}
        with patch.dict(os.environ, env):
            p = InstagramProvider()
        assert p.is_available() is False

    def test_is_available_missing_app_secret(self):
        env = {"INSTAGRAM_APP_ID": "app123", "INSTAGRAM_APP_SECRET": ""}
        with patch.dict(os.environ, env):
            p = InstagramProvider()
        assert p.is_available() is False

    def test_is_available_both_missing(self):
        with patch.dict(os.environ, {"INSTAGRAM_APP_ID": "", "INSTAGRAM_APP_SECRET": ""}):
            p = InstagramProvider()
        assert p.is_available() is False


# ── Error classification ──────────────────────────────────────────────────────

class TestErrorClassification:

    def setup_method(self):
        self.p = _provider_with_env()

    def test_empty_error_no_raise(self):
        # No error dict → returns cleanly
        self.p._raise_for_graph_error({})
        self.p._raise_for_graph_error({}, http_status=200)

    def test_token_expired_code_190(self):
        with pytest.raises(InstagramTokenExpiredError):
            self.p._raise_for_graph_error({"code": 190, "message": "Token expired"})

    def test_token_expired_code_467(self):
        with pytest.raises(InstagramTokenExpiredError):
            self.p._raise_for_graph_error({"code": 467, "message": "Token invalid"})

    def test_token_expired_code_463(self):
        with pytest.raises(InstagramTokenExpiredError):
            self.p._raise_for_graph_error({"code": 463, "message": "Token error"})

    def test_rate_limit_code_4(self):
        with pytest.raises(InstagramRateLimitError) as exc_info:
            self.p._raise_for_graph_error({"code": 4, "message": "App rate limit"})
        assert exc_info.value.retry_after == 60

    def test_rate_limit_code_17(self):
        with pytest.raises(InstagramRateLimitError):
            self.p._raise_for_graph_error({"code": 17, "message": "User rate limit"})

    def test_rate_limit_code_32(self):
        with pytest.raises(InstagramRateLimitError):
            self.p._raise_for_graph_error({"code": 32, "message": "Page rate limit"})

    def test_rate_limit_code_613(self):
        with pytest.raises(InstagramRateLimitError):
            self.p._raise_for_graph_error({"code": 613, "message": "Rate limit exceeded"})

    def test_permanent_code_368_raises_api_error(self):
        with pytest.raises(InstagramAPIError) as exc_info:
            self.p._raise_for_graph_error({"code": 368, "message": "Account blocked"})
        assert exc_info.value.error_code == 368

    def test_permanent_code_2207_raises_api_error(self):
        with pytest.raises(InstagramAPIError) as exc_info:
            self.p._raise_for_graph_error({"code": 2207, "message": "Insufficient privileges"})
        assert exc_info.value.error_code == 2207

    def test_unknown_code_raises_api_error(self):
        with pytest.raises(InstagramAPIError) as exc_info:
            self.p._raise_for_graph_error({"code": 9999, "message": "Unknown error"})
        assert exc_info.value.error_code == 9999

    def test_http_500_empty_error_raises_retryable(self):
        with pytest.raises(InstagramRetryableError):
            self.p._raise_for_graph_error({}, http_status=500)

    def test_http_503_empty_error_raises_retryable(self):
        with pytest.raises(InstagramRetryableError):
            self.p._raise_for_graph_error({}, http_status=503)

    def test_http_400_empty_error_no_raise(self):
        # 400 with no parseable error body → falls through (RuntimeError raised by caller)
        self.p._raise_for_graph_error({}, http_status=400)

    def test_error_message_preserved(self):
        try:
            self.p._raise_for_graph_error({"code": 190, "message": "Token has expired"})
        except InstagramTokenExpiredError as exc:
            assert "Token has expired" in str(exc)


# ── get_auth_url ──────────────────────────────────────────────────────────────

class TestGetAuthUrl:

    def setup_method(self):
        self.p = _provider_with_env()

    def test_contains_state(self):
        url = self.p.get_auth_url(redirect_uri="https://example.com/cb", state="csrf_xyz")
        assert "state=csrf_xyz" in url

    def test_contains_scope(self):
        url = self.p.get_auth_url(redirect_uri="https://example.com/cb", state="s")
        assert "instagram_content_publish" in url

    def test_contains_app_id(self):
        url = self.p.get_auth_url(redirect_uri="https://example.com/cb", state="s")
        assert "client_id=app123" in url

    def test_url_uses_facebook_dialog(self):
        url = self.p.get_auth_url(redirect_uri="https://example.com/cb", state="s")
        assert url.startswith("https://www.facebook.com/")
        assert "dialog/oauth" in url

    def test_contains_redirect_uri(self):
        url = self.p.get_auth_url(redirect_uri="https://example.com/cb", state="s")
        assert "redirect_uri=" in url
        assert "example.com" in url

    def test_response_type_code(self):
        url = self.p.get_auth_url(redirect_uri="https://example.com/cb", state="s")
        assert "response_type=code" in url


# ── exchange_code ─────────────────────────────────────────────────────────────

class TestExchangeCode:

    def setup_method(self):
        self.p = _provider_with_env()

    def _make_short_lived_resp(self):
        return _httpx_response(200, {"access_token": "short-token-abc"})

    def _make_long_lived_resp(self):
        return _httpx_response(200, {
            "access_token": "long-token-xyz",
            "expires_in":   5184000,
        })

    def _make_accounts_resp(self, with_ig=True):
        if with_ig:
            data = [{
                "id": "page-1",
                "instagram_business_account": {
                    "id":                  "ig_user_42",
                    "username":            "flow_studio",
                    "name":                "Flow Studio",
                    "profile_picture_url": "https://example.com/pic.jpg",
                },
            }]
        else:
            data = [{"id": "page-1"}]  # no IG account linked
        return _httpx_response(200, {"data": data})

    def test_returns_oauth_token_result(self):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=[
            self._make_short_lived_resp(),
            self._make_long_lived_resp(),
            self._make_accounts_resp(),
        ])
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = _run(self.p.exchange_code("auth_code_123", "https://example.com/cb"))

        assert result.access_token == "long-token-xyz"
        assert result.expires_in == 5184000

    def test_sets_platform_user_id(self):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=[
            self._make_short_lived_resp(),
            self._make_long_lived_resp(),
            self._make_accounts_resp(),
        ])
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = _run(self.p.exchange_code("code", "https://example.com/cb"))

        assert result.platform_user_id == "ig_user_42"
        assert result.platform_username == "flow_studio"
        assert result.platform_name == "Flow Studio"

    def test_refresh_token_equals_access_token(self):
        """Instagram long-lived tokens are refreshed by re-using the same token."""
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=[
            self._make_short_lived_resp(),
            self._make_long_lived_resp(),
            self._make_accounts_resp(),
        ])
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = _run(self.p.exchange_code("code", "https://example.com/cb"))

        assert result.refresh_token == result.access_token

    def test_no_ig_account_raises_api_error(self):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=[
            self._make_short_lived_resp(),
            self._make_long_lived_resp(),
            self._make_accounts_resp(with_ig=False),
        ])
        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(InstagramAPIError) as exc_info:
                _run(self.p.exchange_code("code", "https://example.com/cb"))

        assert exc_info.value.error_code == "no_ig_business_account"

    def test_short_lived_exchange_token_error_raises(self):
        err_resp = _httpx_response(400, {
            "error": {"code": 190, "message": "Invalid code"}
        })
        request = httpx.Request("GET", "https://graph.facebook.com/")
        err_resp = httpx.Response(400, content=json.dumps({
            "error": {"code": 190, "message": "Invalid code"}
        }).encode(), headers={"Content-Type": "application/json"}, request=request)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=httpx.HTTPStatusError(
            "400", request=request, response=err_resp
        ))
        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises((InstagramTokenExpiredError, RuntimeError)):
                _run(self.p.exchange_code("bad-code", "https://example.com/cb"))

    def test_network_error_raises_runtime_error(self):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("timeout"))
        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(RuntimeError, match="network error"):
                _run(self.p.exchange_code("code", "https://example.com/cb"))

    def test_includes_scopes(self):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=[
            self._make_short_lived_resp(),
            self._make_long_lived_resp(),
            self._make_accounts_resp(),
        ])
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = _run(self.p.exchange_code("code", "https://example.com/cb"))

        assert "instagram_content_publish" in result.scopes

    def test_does_not_log_access_token(self, caplog):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=[
            self._make_short_lived_resp(),
            self._make_long_lived_resp(),
            self._make_accounts_resp(),
        ])
        with patch("httpx.AsyncClient", return_value=mock_client):
            with caplog.at_level("DEBUG", logger="app.integrations.social.instagram"):
                _run(self.p.exchange_code("code", "https://example.com/cb"))

        log_text = " ".join(r.message for r in caplog.records)
        assert "long-token-xyz" not in log_text
        assert "short-token-abc" not in log_text


# ── refresh_access_token ──────────────────────────────────────────────────────

class TestRefreshAccessToken:

    def setup_method(self):
        self.p = _provider_with_env()

    def test_returns_new_token(self):
        resp = _httpx_response(200, {"access_token": "new-long-token", "expires_in": 5184000})
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=resp)
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = _run(self.p.refresh_access_token("old-long-token"))

        assert result.access_token == "new-long-token"
        assert result.expires_in == 5184000
        assert result.refresh_token == "new-long-token"

    def test_expired_token_raises(self):
        request = httpx.Request("GET", "https://graph.facebook.com/")
        err_body = {"error": {"code": 190, "message": "Token expired"}}
        err_resp = httpx.Response(
            400,
            content=json.dumps(err_body).encode(),
            headers={"Content-Type": "application/json"},
            request=request,
        )
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=httpx.HTTPStatusError(
            "400", request=request, response=err_resp
        ))
        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(InstagramTokenExpiredError):
                _run(self.p.refresh_access_token("expired-token"))

    def test_network_error_raises_runtime_error(self):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("network down"))
        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(RuntimeError):
                _run(self.p.refresh_access_token("any-token"))


# ── revoke_token ──────────────────────────────────────────────────────────────

class TestRevokeToken:

    def setup_method(self):
        self.p = _provider_with_env()

    def test_no_raise_on_success(self):
        resp = _httpx_response(200, {"success": True}, method="DELETE")
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.delete = AsyncMock(return_value=resp)
        with patch("httpx.AsyncClient", return_value=mock_client):
            _run(self.p.revoke_token("some-token"))  # should not raise

    def test_no_raise_on_failure(self):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.delete = AsyncMock(side_effect=Exception("network down"))
        with patch("httpx.AsyncClient", return_value=mock_client):
            _run(self.p.revoke_token("some-token"))  # should not raise

    def test_no_raise_on_http_error(self):
        request = httpx.Request("DELETE", "https://graph.facebook.com/")
        err_resp = httpx.Response(403, content=b"{}", request=request)
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.delete = AsyncMock(side_effect=httpx.HTTPStatusError(
            "403", request=request, response=err_resp
        ))
        with patch("httpx.AsyncClient", return_value=mock_client):
            _run(self.p.revoke_token("some-token"))  # should not raise


# ── publish_video ─────────────────────────────────────────────────────────────

class TestPublishVideo:

    def setup_method(self):
        self.p = _provider_with_env()
        self.req = PublishRequest(
            video_url="https://cdn.example.com/reel.mp4",
            caption="Test Reel",
            hashtags=["reels", "test"],
            access_token="user-access-token",
            platform_user_id="ig_user_42",
        )

    def _make_container_resp(self, container_id="container_123"):
        return _httpx_response(200, {"id": container_id}, method="POST")

    def test_returns_processing_status(self):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=self._make_container_resp())
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = _run(self.p.publish_video(self.req))

        assert result.status == PublishStatus.PROCESSING

    def test_publish_id_contains_user_id_and_container_id(self):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=self._make_container_resp("cont_abc"))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = _run(self.p.publish_video(self.req))

        assert "|" in result.platform_publish_id
        user_id, container_id = result.platform_publish_id.split("|", 1)
        assert user_id == "ig_user_42"
        assert container_id == "cont_abc"

    def test_metadata_contains_container_id(self):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=self._make_container_resp("cont_xyz"))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = _run(self.p.publish_video(self.req))

        assert result.metadata.get("ig_container_id") == "cont_xyz"

    def test_caption_includes_hashtags(self):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=self._make_container_resp())
        with patch("httpx.AsyncClient", return_value=mock_client):
            _run(self.p.publish_video(self.req))

        call_kwargs = mock_client.post.call_args
        posted_data = call_kwargs[1]["data"] if "data" in call_kwargs[1] else call_kwargs[0][1]
        assert "#reels" in posted_data.get("caption", "")

    def test_caption_truncated_at_2200(self):
        long_req = PublishRequest(
            video_url="https://cdn.example.com/reel.mp4",
            caption="A" * 2300,
            access_token="tok",
            platform_user_id="ig_user_42",
        )
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=self._make_container_resp())
        with patch("httpx.AsyncClient", return_value=mock_client):
            _run(self.p.publish_video(long_req))

        call_kwargs = mock_client.post.call_args
        posted_data = call_kwargs[1]["data"] if "data" in call_kwargs[1] else call_kwargs[0][1]
        assert len(posted_data.get("caption", "")) <= 2200

    def test_media_type_is_reels(self):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=self._make_container_resp())
        with patch("httpx.AsyncClient", return_value=mock_client):
            _run(self.p.publish_video(self.req))

        call_kwargs = mock_client.post.call_args
        posted_data = call_kwargs[1]["data"] if "data" in call_kwargs[1] else call_kwargs[0][1]
        assert posted_data.get("media_type") == "REELS"

    def test_token_expired_raises(self):
        request = httpx.Request("POST", f"{_GRAPH_BASE}/ig_user_42/media")
        err_resp = httpx.Response(
            400,
            content=json.dumps({"error": {"code": 190, "message": "Token expired"}}).encode(),
            headers={"Content-Type": "application/json"},
            request=request,
        )
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=httpx.HTTPStatusError(
            "400", request=request, response=err_resp
        ))
        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(InstagramTokenExpiredError):
                _run(self.p.publish_video(self.req))

    def test_rate_limit_raises(self):
        request = httpx.Request("POST", f"{_GRAPH_BASE}/ig_user_42/media")
        err_resp = httpx.Response(
            429,
            content=json.dumps({"error": {"code": 4, "message": "Rate limit"}}).encode(),
            headers={"Content-Type": "application/json"},
            request=request,
        )
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=httpx.HTTPStatusError(
            "429", request=request, response=err_resp
        ))
        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(InstagramRateLimitError):
                _run(self.p.publish_video(self.req))

    def test_permanent_error_raises_api_error(self):
        request = httpx.Request("POST", f"{_GRAPH_BASE}/ig_user_42/media")
        err_resp = httpx.Response(
            400,
            content=json.dumps({"error": {"code": 368, "message": "Account blocked"}}).encode(),
            headers={"Content-Type": "application/json"},
            request=request,
        )
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=httpx.HTTPStatusError(
            "400", request=request, response=err_resp
        ))
        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(InstagramAPIError) as exc_info:
                _run(self.p.publish_video(self.req))
        assert exc_info.value.error_code == 368

    def test_network_error_raises_runtime_error(self):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("connection refused"))
        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(RuntimeError, match="network error"):
                _run(self.p.publish_video(self.req))

    def test_missing_container_id_raises(self):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=_httpx_response(200, {"id": ""}))
        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(InstagramAPIError) as exc_info:
                _run(self.p.publish_video(self.req))
        assert "missing_container_id" in exc_info.value.error_code

    def test_does_not_log_access_token(self, caplog):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=self._make_container_resp())
        with patch("httpx.AsyncClient", return_value=mock_client):
            with caplog.at_level("DEBUG", logger="app.integrations.social.instagram"):
                _run(self.p.publish_video(self.req))

        log_text = " ".join(r.message for r in caplog.records)
        assert "user-access-token" not in log_text


# ── get_publish_status ────────────────────────────────────────────────────────

class TestGetPublishStatus:

    def setup_method(self):
        self.p = _provider_with_env()
        self.publish_id     = "ig_user_42|container_123"
        self.access_token   = "user-access-token"

    def _container_status_resp(self, status_code: str) -> httpx.Response:
        return _httpx_response(200, {"id": "container_123", "status_code": status_code})

    def _media_publish_resp(self, media_id: str = "ig_media_999") -> httpx.Response:
        return _httpx_response(200, {"id": media_id}, method="POST")

    def _permalink_resp(self, permalink: str = "https://www.instagram.com/reel/abc123/") -> httpx.Response:
        return _httpx_response(200, {"permalink": permalink, "id": "ig_media_999"})

    def test_in_progress_returns_processing(self):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=self._container_status_resp("IN_PROGRESS"))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = _run(self.p.get_publish_status(self.publish_id, self.access_token))

        assert result.status == PublishStatus.PROCESSING
        assert result.platform_publish_id == self.publish_id

    def test_not_started_returns_processing(self):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=self._container_status_resp("NOT_STARTED"))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = _run(self.p.get_publish_status(self.publish_id, self.access_token))

        assert result.status == PublishStatus.PROCESSING

    def test_container_error_returns_failed(self):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=self._container_status_resp("ERROR"))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = _run(self.p.get_publish_status(self.publish_id, self.access_token))

        assert result.status == PublishStatus.FAILED
        assert result.error_code == "error"

    def test_container_expired_returns_failed(self):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=self._container_status_resp("EXPIRED"))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = _run(self.p.get_publish_status(self.publish_id, self.access_token))

        assert result.status == PublishStatus.FAILED
        assert result.error_code == "expired"

    def test_finished_calls_media_publish_and_returns_completed(self):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        # GET container_status → GET permalink (via _fetch_media_permalink)
        mock_client.get = AsyncMock(side_effect=[
            self._container_status_resp("FINISHED"),
            self._permalink_resp(),
        ])
        mock_client.post = AsyncMock(return_value=self._media_publish_resp("ig_media_777"))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = _run(self.p.get_publish_status(self.publish_id, self.access_token))

        assert result.status == PublishStatus.COMPLETED

    def test_finished_transitions_publish_id_to_media_id(self):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=[
            self._container_status_resp("FINISHED"),
            self._permalink_resp(),
        ])
        mock_client.post = AsyncMock(return_value=self._media_publish_resp("ig_media_777"))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = _run(self.p.get_publish_status(self.publish_id, self.access_token))

        # Publish ID must transition from "user|container" to bare ig_media_id
        assert "|" not in result.platform_publish_id
        assert result.platform_publish_id == "ig_media_777"

    def test_finished_includes_platform_url(self):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=[
            self._container_status_resp("FINISHED"),
            self._permalink_resp("https://www.instagram.com/reel/XYZ123/"),
        ])
        mock_client.post = AsyncMock(return_value=self._media_publish_resp())
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = _run(self.p.get_publish_status(self.publish_id, self.access_token))

        assert result.platform_url == "https://www.instagram.com/reel/XYZ123/"

    def test_permalink_failure_is_not_fatal(self):
        """If permalink fetch fails, the post is still COMPLETED."""
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=[
            self._container_status_resp("FINISHED"),
            httpx.ConnectError("timeout"),  # permalink fetch fails
        ])
        mock_client.post = AsyncMock(return_value=self._media_publish_resp("ig_media_888"))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = _run(self.p.get_publish_status(self.publish_id, self.access_token))

        assert result.status == PublishStatus.COMPLETED
        assert result.platform_url is None  # gracefully absent

    def test_already_published_bare_media_id_returns_completed(self):
        """If publish_id is a bare ig_media_id (no '|'), return COMPLETED."""
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=self._permalink_resp(
            "https://www.instagram.com/reel/already_pub/"
        ))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = _run(self.p.get_publish_status("ig_media_already_999", self.access_token))

        assert result.status == PublishStatus.COMPLETED
        assert result.platform_publish_id == "ig_media_already_999"
        assert result.platform_url == "https://www.instagram.com/reel/already_pub/"

    def test_container_status_token_expired_propagates(self):
        request = httpx.Request("GET", f"{_GRAPH_BASE}/container_123")
        err_resp = httpx.Response(
            400,
            content=json.dumps({"error": {"code": 190, "message": "Token expired"}}).encode(),
            headers={"Content-Type": "application/json"},
            request=request,
        )
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=httpx.HTTPStatusError(
            "400", request=request, response=err_resp
        ))
        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(InstagramTokenExpiredError):
                _run(self.p.get_publish_status(self.publish_id, self.access_token))

    def test_container_status_rate_limit_propagates(self):
        request = httpx.Request("GET", f"{_GRAPH_BASE}/container_123")
        err_resp = httpx.Response(
            429,
            content=json.dumps({"error": {"code": 4, "message": "Rate limit"}}).encode(),
            headers={"Content-Type": "application/json"},
            request=request,
        )
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=httpx.HTTPStatusError(
            "429", request=request, response=err_resp
        ))
        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(InstagramRateLimitError):
                _run(self.p.get_publish_status(self.publish_id, self.access_token))

    def test_media_publish_failure_after_finished_propagates(self):
        """If media_publish fails after container FINISHED, the error must propagate."""
        request = httpx.Request("POST", f"{_GRAPH_BASE}/ig_user_42/media_publish")
        err_resp = httpx.Response(
            400,
            content=json.dumps({"error": {"code": 368, "message": "Account blocked"}}).encode(),
            headers={"Content-Type": "application/json"},
            request=request,
        )
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=self._container_status_resp("FINISHED"))
        mock_client.post = AsyncMock(side_effect=httpx.HTTPStatusError(
            "400", request=request, response=err_resp
        ))
        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(InstagramAPIError):
                _run(self.p.get_publish_status(self.publish_id, self.access_token))

    def test_metadata_tracks_container_and_media_ids(self):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=[
            self._container_status_resp("FINISHED"),
            self._permalink_resp(),
        ])
        mock_client.post = AsyncMock(return_value=self._media_publish_resp("ig_media_555"))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = _run(self.p.get_publish_status(self.publish_id, self.access_token))

        assert result.metadata.get("ig_container_id") == "container_123"
        assert result.metadata.get("ig_media_id") == "ig_media_555"


# ── Idempotency contract ──────────────────────────────────────────────────────

class TestIdempotencyContract:

    def setup_method(self):
        self.p = _provider_with_env()

    def test_publish_id_format_allows_parsing(self):
        """publish_id must contain '|' so get_publish_status can split it."""
        req = PublishRequest(
            video_url="https://cdn.example.com/v.mp4",
            caption="Test",
            access_token="tok",
            platform_user_id="ig_user_7",
        )
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=_httpx_response(200, {"id": "cont_XYZ"}))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = _run(self.p.publish_video(req))

        assert "|" in result.platform_publish_id
        user_id, container_id = result.platform_publish_id.split("|", 1)
        assert user_id == "ig_user_7"
        assert container_id == "cont_XYZ"

    def test_same_publish_id_returned_while_in_progress(self):
        """PROCESSING status must preserve the original publish_id."""
        publish_id = "ig_user_7|cont_XYZ"
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=_httpx_response(200, {
            "id": "cont_XYZ", "status_code": "IN_PROGRESS"
        }))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = _run(self.p.get_publish_status(publish_id, "tok"))

        assert result.platform_publish_id == publish_id  # unchanged

    def test_media_id_replaces_publish_id_on_complete(self):
        """COMPLETED status must return bare ig_media_id (no '|')."""
        publish_id = "ig_user_7|cont_XYZ"
        request = httpx.Request("GET", f"{_GRAPH_BASE}/cont_XYZ")
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=[
            _httpx_response(200, {"id": "cont_XYZ", "status_code": "FINISHED"}),
            _httpx_response(200, {"permalink": "https://www.instagram.com/reel/x/"}),
        ])
        mock_client.post = AsyncMock(return_value=_httpx_response(200, {"id": "new_media_001"}))
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = _run(self.p.get_publish_status(publish_id, "tok"))

        assert result.platform_publish_id == "new_media_001"
        assert "|" not in result.platform_publish_id


# ── Org isolation ─────────────────────────────────────────────────────────────

class TestOrgIsolation:

    def setup_method(self):
        self.p = _provider_with_env()

    def test_provider_is_stateless(self):
        """InstagramProvider must store only app credentials, never org-specific data."""
        p1 = _provider_with_env()
        p2 = _provider_with_env()
        # Both share the same app credentials from env but have no per-org state
        assert p1.platform_id == p2.platform_id
        # No instance variables beyond app credentials
        assert not hasattr(p1, "_access_token")
        assert not hasattr(p1, "_org_id")

    def test_publish_uses_request_access_token(self):
        """Access token from request must be passed to the API — not stored in provider."""
        token_a = "token-org-a-secret"
        req = PublishRequest(
            video_url="https://cdn.example.com/v.mp4",
            caption="Test",
            access_token=token_a,
            platform_user_id="ig_user_A",
        )
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=_httpx_response(200, {"id": "cont_A"}))
        with patch("httpx.AsyncClient", return_value=mock_client):
            _run(self.p.publish_video(req))

        call_kwargs = mock_client.post.call_args
        posted_data = call_kwargs[1]["data"] if "data" in call_kwargs[1] else call_kwargs[0][1]
        assert posted_data.get("access_token") == token_a

    def test_two_orgs_cannot_cross_contaminate(self):
        """Verifies the publish_id encodes the ig_user_id, scoping status polls."""
        req_a = PublishRequest(
            video_url="https://cdn.example.com/a.mp4",
            caption="A",
            access_token="token_a",
            platform_user_id="ig_user_A",
        )
        req_b = PublishRequest(
            video_url="https://cdn.example.com/b.mp4",
            caption="B",
            access_token="token_b",
            platform_user_id="ig_user_B",
        )
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=[
            _httpx_response(200, {"id": "cont_A"}),
            _httpx_response(200, {"id": "cont_B"}),
        ])
        with patch("httpx.AsyncClient", return_value=mock_client):
            result_a = _run(self.p.publish_video(req_a))
            result_b = _run(self.p.publish_video(req_b))

        assert result_a.platform_publish_id.startswith("ig_user_A|")
        assert result_b.platform_publish_id.startswith("ig_user_B|")
        assert result_a.platform_publish_id != result_b.platform_publish_id


# ── Registry integration ──────────────────────────────────────────────────────

class TestRegistryIntegration:

    def test_instagram_registered_in_registry(self):
        from app.integrations.social.registry import SocialPublisherRegistry
        reg = SocialPublisherRegistry()
        provider = reg.get("instagram")
        assert provider is not None
        assert provider.platform_id == "instagram"

    def test_instagram_in_list_platforms(self):
        from app.integrations.social.registry import SocialPublisherRegistry
        reg = SocialPublisherRegistry()
        platforms = reg.list_platforms()
        ids = {p["platform_id"] for p in platforms}
        assert "instagram" in ids

    def test_list_platforms_excludes_mock(self):
        from app.integrations.social.registry import SocialPublisherRegistry
        reg = SocialPublisherRegistry()
        platforms = reg.list_platforms()
        ids = {p["platform_id"] for p in platforms}
        assert "mock" not in ids

    def test_list_platforms_has_both_tiktok_and_instagram(self):
        from app.integrations.social.registry import SocialPublisherRegistry
        reg = SocialPublisherRegistry()
        platforms = reg.list_platforms()
        ids = {p["platform_id"] for p in platforms}
        assert "tiktok" in ids
        assert "instagram" in ids

    def test_instagram_platform_entry_shape(self):
        from app.integrations.social.registry import SocialPublisherRegistry
        reg = SocialPublisherRegistry()
        platforms = reg.list_platforms()
        ig = next(p for p in platforms if p["platform_id"] == "instagram")
        assert ig["display_name"] == "Instagram"
        assert "available" in ig

    def test_get_or_raise_returns_instagram_provider(self):
        from app.integrations.social.registry import SocialPublisherRegistry
        reg = SocialPublisherRegistry()
        provider = reg.get_or_raise("instagram")
        assert provider.platform_id == "instagram"
