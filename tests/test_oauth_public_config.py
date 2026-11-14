import pytest
from fastapi import HTTPException, Response
from app.routers import auth_users

@pytest.mark.asyncio
async def test_canonical_origin_matches_callback_base(monkeypatch):
    monkeypatch.setattr(auth_users, "_APP_URL_BASE", "https://backend.example.test/")
    response = Response()
    assert await auth_users.oauth_public_config(response) == {"origin": "https://backend.example.test"}
    assert response.headers["cache-control"] == "no-store"

@pytest.mark.asyncio
@pytest.mark.parametrize("origin", ["http://example.test", "https://u:p@example.test", "https://example.test/path", "https://example.test?x=y"])
async def test_invalid_config_fails_closed(monkeypatch, origin):
    monkeypatch.setattr(auth_users, "_APP_URL_BASE", origin)
    with pytest.raises(HTTPException) as exc:
        await auth_users.oauth_public_config(Response())
    assert exc.value.status_code == 503
