"""Device enrollment contract (found broken by the SEC-02 E2E run).

* The Device Agent posts to /api/devices/enroll with no session; the API
  auth middleware must let exactly that request through.
* The shipped agent sends the token as "enrollment_token", the API
  documented "token"; both must be accepted.
The foreign-key ordering fix in consume_enrollment_token() is exercised
against real PostgreSQL by tests_e2e/test_org_isolation_http.py.
"""
import os

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("SESSION_SECRET", "test-secret-for-unit-tests-do-not-use-in-prod")

from app.routers.devices import EnrollRequest, is_public_device_enroll_request  # noqa: E402

TOKEN = "dev_enroll_" + "x" * 32


def test_only_post_enroll_is_public():
    assert is_public_device_enroll_request("POST", "/api/devices/enroll")
    assert not is_public_device_enroll_request("GET", "/api/devices/enroll")
    assert not is_public_device_enroll_request("POST", "/api/devices/enroll-token")
    assert not is_public_device_enroll_request("POST", "/api/devices/enroll/")
    assert not is_public_device_enroll_request("POST", "/api/devices/")


def test_enroll_accepts_agent_and_api_field_names():
    for field in ("token", "enrollment_token"):
        body = EnrollRequest.model_validate({field: TOKEN, "device_name": "pc"})
        assert body.token == TOKEN


def test_agent_payload_shape_is_accepted():
    # Mirrors agent/__main__.py cmd_enroll()'s payload.
    payload = {"enrollment_token": TOKEN, "device_name": "pc", "platform": "windows",
               "hostname": "pc", "agent_version": "1.0.0"}
    assert EnrollRequest.model_validate(payload).token == TOKEN


def _middleware_status(path: str) -> int:
    from fastapi.testclient import TestClient
    from app.factory import create_app

    # No context manager, so no lifespan and no DB pool: a request that gets
    # past the middleware fails later (500), which is what we distinguish
    # from the middleware's own 401.
    client = TestClient(create_app(), raise_server_exceptions=False)
    return client.post(path, json={"token": TOKEN, "device_name": "pc"}).status_code


def test_middleware_lets_enroll_through_but_not_enroll_token():
    # A 401 "Subscription required" comes from the auth middleware; anything
    # else means the request reached routing/validation.
    assert _middleware_status("/api/devices/enroll") != 401
    assert _middleware_status("/api/devices/enroll-token") == 401
