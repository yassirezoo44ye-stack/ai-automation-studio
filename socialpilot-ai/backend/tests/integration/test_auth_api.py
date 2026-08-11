from __future__ import annotations

import pytest

from app.core.config import get_settings
from tests.conftest import unique_email

settings = get_settings()

pytestmark = pytest.mark.asyncio


async def _register(client, *, email=None, password="Sup3rSecret1", full_name="Founder One", org="Acme"):
    return await client.post(
        "/api/v1/auth/register",
        json={
            "email": email or unique_email(),
            "password": password,
            "full_name": full_name,
            "organization_name": org,
        },
    )


class TestRegister:
    async def test_register_creates_user_and_owner_org(self, client) -> None:
        r = await _register(client)
        assert r.status_code == 201
        body = r.json()
        assert body["user"]["email"]
        assert body["organizations"][0]["role"] == "owner"
        assert body["organizations"][0]["name"] == "Acme"
        assert "access_token" in body
        assert settings.refresh_cookie_name in r.cookies
        assert settings.csrf_cookie_name in r.cookies

    async def test_register_defaults_org_name_from_full_name(self, client) -> None:
        r = await client.post(
            "/api/v1/auth/register",
            json={
                "email": unique_email(),
                "password": "Sup3rSecret1",
                "full_name": "Jane Doe",
            },
        )
        assert r.status_code == 201
        assert r.json()["organizations"][0]["name"] == "Jane Doe's Workspace"

    async def test_register_rejects_duplicate_email(self, client) -> None:
        email = unique_email()
        first = await _register(client, email=email)
        assert first.status_code == 201
        second = await _register(client, email=email)
        assert second.status_code == 409

    async def test_register_rejects_weak_password(self, client) -> None:
        r = await client.post(
            "/api/v1/auth/register",
            json={"email": unique_email(), "password": "short", "full_name": "X"},
        )
        assert r.status_code == 422

    async def test_register_rejects_password_without_digit(self, client) -> None:
        r = await client.post(
            "/api/v1/auth/register",
            json={"email": unique_email(), "password": "alllettersnodigit", "full_name": "X"},
        )
        assert r.status_code == 422

    async def test_password_never_leaks_in_response(self, client) -> None:
        r = await _register(client)
        assert "Sup3rSecret1" not in r.text
        assert "hashed_password" not in r.text
        assert "password" not in r.json()["user"]


class TestLogin:
    async def test_login_with_correct_credentials(self, client) -> None:
        email = unique_email()
        await _register(client, email=email, password="Sup3rSecret1")
        r = await client.post("/api/v1/auth/login", json={"email": email, "password": "Sup3rSecret1"})
        assert r.status_code == 200
        assert r.json()["user"]["email"] == email

    async def test_login_with_wrong_password_fails(self, client) -> None:
        email = unique_email()
        await _register(client, email=email, password="Sup3rSecret1")
        r = await client.post("/api/v1/auth/login", json={"email": email, "password": "WrongPassw0rd"})
        assert r.status_code == 401

    async def test_login_with_unknown_email_fails(self, client) -> None:
        r = await client.post(
            "/api/v1/auth/login", json={"email": unique_email(), "password": "Sup3rSecret1"}
        )
        assert r.status_code == 401

    async def test_login_error_does_not_reveal_which_field_was_wrong(self, client) -> None:
        email = unique_email()
        await _register(client, email=email, password="Sup3rSecret1")
        wrong_password = await client.post(
            "/api/v1/auth/login", json={"email": email, "password": "WrongPassw0rd"}
        )
        unknown_email = await client.post(
            "/api/v1/auth/login", json={"email": unique_email(), "password": "Sup3rSecret1"}
        )
        assert wrong_password.json()["detail"] == unknown_email.json()["detail"]


class TestRefreshAndLogout:
    async def test_refresh_rotates_token_and_issues_new_access_token(self, client) -> None:
        reg = await _register(client)
        raw_refresh = reg.cookies[settings.refresh_cookie_name]
        csrf = reg.json()["csrf_token"]

        r = await client.post(
            "/api/v1/auth/refresh",
            headers={"X-CSRF-Token": csrf},
            cookies={settings.refresh_cookie_name: raw_refresh, settings.csrf_cookie_name: csrf},
        )
        assert r.status_code == 200
        assert r.json()["access_token"] != reg.json()["access_token"]
        new_raw_refresh = r.cookies[settings.refresh_cookie_name]
        assert new_raw_refresh != raw_refresh

    async def test_refresh_without_csrf_header_is_rejected(self, client) -> None:
        reg = await _register(client)
        raw_refresh = reg.cookies[settings.refresh_cookie_name]
        r = await client.post(
            "/api/v1/auth/refresh", cookies={settings.refresh_cookie_name: raw_refresh}
        )
        assert r.status_code == 401

    async def test_refresh_with_mismatched_csrf_header_is_rejected(self, client) -> None:
        reg = await _register(client)
        raw_refresh = reg.cookies[settings.refresh_cookie_name]
        r = await client.post(
            "/api/v1/auth/refresh",
            headers={"X-CSRF-Token": "totally-wrong-token"},
            cookies={settings.refresh_cookie_name: raw_refresh},
        )
        assert r.status_code == 401

    async def test_reusing_a_rotated_refresh_token_is_rejected_and_revokes_the_session(
        self, client
    ) -> None:
        reg = await _register(client)
        old_raw_refresh = reg.cookies[settings.refresh_cookie_name]
        old_csrf = reg.json()["csrf_token"]

        first = await client.post(
            "/api/v1/auth/refresh",
            headers={"X-CSRF-Token": old_csrf},
            cookies={
                settings.refresh_cookie_name: old_raw_refresh,
                settings.csrf_cookie_name: old_csrf,
            },
        )
        assert first.status_code == 200
        new_raw_refresh = first.cookies[settings.refresh_cookie_name]
        new_csrf = first.json()["csrf_token"]

        # Replay the now-rotated-away old token: must fail...
        # NOTE: every call below pins BOTH the refresh cookie and the CSRF cookie
        # explicitly. httpx's AsyncClient otherwise persists a jar across calls,
        # and would silently substitute the *rotated* csrf cookie set by the
        # previous response — masking exactly the reuse case this test exists
        # to catch behind an unrelated CSRF-mismatch 401.
        replay = await client.post(
            "/api/v1/auth/refresh",
            headers={"X-CSRF-Token": old_csrf},
            cookies={
                settings.refresh_cookie_name: old_raw_refresh,
                settings.csrf_cookie_name: old_csrf,
            },
        )
        assert replay.status_code == 401

        # ...and the reuse must have burned the *whole chain*, including the
        # legitimately-rotated new token (theft-detection behavior).
        second = await client.post(
            "/api/v1/auth/refresh",
            headers={"X-CSRF-Token": new_csrf},
            cookies={
                settings.refresh_cookie_name: new_raw_refresh,
                settings.csrf_cookie_name: new_csrf,
            },
        )
        assert second.status_code == 401

    async def test_refresh_with_garbage_token_is_rejected(self, client) -> None:
        r = await client.post(
            "/api/v1/auth/refresh",
            headers={"X-CSRF-Token": "x"},
            cookies={settings.refresh_cookie_name: "not-a-real-token", settings.csrf_cookie_name: "x"},
        )
        assert r.status_code == 401

    async def test_logout_revokes_refresh_token(self, client) -> None:
        reg = await _register(client)
        raw_refresh = reg.cookies[settings.refresh_cookie_name]
        csrf = reg.json()["csrf_token"]

        logout = await client.post(
            "/api/v1/auth/logout",
            headers={"X-CSRF-Token": csrf},
            cookies={settings.refresh_cookie_name: raw_refresh, settings.csrf_cookie_name: csrf},
        )
        assert logout.status_code == 204

        r = await client.post(
            "/api/v1/auth/refresh",
            headers={"X-CSRF-Token": csrf},
            cookies={settings.refresh_cookie_name: raw_refresh, settings.csrf_cookie_name: csrf},
        )
        assert r.status_code == 401

    async def test_logout_without_cookie_is_a_no_op_success(self, client) -> None:
        r = await client.post("/api/v1/auth/logout")
        assert r.status_code == 204


class TestMe:
    async def test_me_requires_authentication(self, client) -> None:
        r = await client.get("/api/v1/auth/me")
        assert r.status_code == 401

    async def test_me_rejects_garbage_bearer_token(self, client) -> None:
        r = await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer garbage"})
        assert r.status_code == 401

    async def test_me_returns_current_user_and_orgs(self, client) -> None:
        reg = await _register(client)
        access = reg.json()["access_token"]
        r = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access}"})
        assert r.status_code == 200
        assert r.json()["user"]["email"] == reg.json()["user"]["email"]
        assert len(r.json()["organizations"]) == 1


class TestChangePassword:
    async def test_change_password_then_login_with_new_password(self, client) -> None:
        email = unique_email()
        reg = await _register(client, email=email, password="Sup3rSecret1")
        access = reg.json()["access_token"]

        r = await client.post(
            "/api/v1/auth/change-password",
            headers={"Authorization": f"Bearer {access}"},
            json={"current_password": "Sup3rSecret1", "new_password": "NewSecret2"},
        )
        assert r.status_code == 204

        old_login = await client.post(
            "/api/v1/auth/login", json={"email": email, "password": "Sup3rSecret1"}
        )
        assert old_login.status_code == 401

        new_login = await client.post(
            "/api/v1/auth/login", json={"email": email, "password": "NewSecret2"}
        )
        assert new_login.status_code == 200

    async def test_change_password_rejects_wrong_current_password(self, client) -> None:
        reg = await _register(client)
        access = reg.json()["access_token"]
        r = await client.post(
            "/api/v1/auth/change-password",
            headers={"Authorization": f"Bearer {access}"},
            json={"current_password": "WrongOne1", "new_password": "NewSecret2"},
        )
        assert r.status_code == 401
