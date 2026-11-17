"""HTTP contract for the trusted gateway; only fixture HTTP servers are started."""
import importlib.util
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import httpx
import pytest


@pytest.fixture
def gateway(monkeypatch):
    monkeypatch.setenv("FLOW_PREVIEW_TOKEN", "test-only-capability")
    path = Path(__file__).parents[1] / "app/execution/preview_gateway.py"
    spec = importlib.util.spec_from_file_location("fixture_gateway", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    class App(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass
        def do_GET(self):
            body = json.dumps(dict(self.headers)).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            if self.path == "/folded-header":
                self.send_header("X-Preview", "safe\r\n\tX-Injected: yes")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    upstream = ThreadingHTTPServer(("127.0.0.1", 0), App)
    module.UPSTREAM_PORT = upstream.server_port
    server = ThreadingHTTPServer(("127.0.0.1", 0), module.Gateway)
    threads = [Thread(target=s.serve_forever, daemon=True) for s in (upstream, server)]
    for thread in threads:
        thread.start()
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{server.server_port}", trust_env=False) as client:
            yield client
    finally:
        for s in (server, upstream):
            s.shutdown()
            s.server_close()
        for thread in threads:
            thread.join(timeout=2)


def test_preview_requires_its_own_capability(gateway):
    assert gateway.get("/").status_code == 401
    assert gateway.get("/", headers={"Cookie": "__Host-flow_preview=wrong"}).status_code == 401
    assert gateway.get("/_flow_preview/wrong").status_code == 401
    assert gateway.post("/_flow_preview/test-only-capability").status_code == 401


def test_bootstrap_issues_short_lived_http_only_cookie_without_leaking_token(gateway):
    response = gateway.get("/_flow_preview/test-only-capability")
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    cookie = response.headers["set-cookie"]
    for attribute in ("Secure", "HttpOnly", "SameSite=None", "Partitioned", "Max-Age=300", "Path=/"):
        assert attribute in cookie
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cache-control"] == "no-store"


def test_platform_headers_and_capability_never_reach_generated_application(gateway):
    response = gateway.get("/", headers={
        "Cookie": "__Host-flow_preview=test-only-capability; app_session=fixture",
        "Authorization": "Bearer platform-token", "X-Sub-Token": "subscription-token",
        "X-Organization-Id": "private-org", "X-API-Key": "platform-key",
    })
    assert response.status_code == 200
    headers = {key.lower(): value for key, value in response.json().items()}
    assert headers["cookie"] == "app_session=fixture"
    for key in ("authorization", "x-sub-token", "x-organization-id", "x-api-key"):
        assert key not in headers
    assert "test-only-capability" not in response.text
    assert response.headers["cache-control"] == "no-store"


def test_other_session_capability_cannot_open_preview(gateway):
    response = gateway.get("/", headers={"Cookie": "__Host-flow_preview=another-project-token"})
    assert response.status_code == 401


def test_upstream_folded_header_cannot_split_gateway_response(gateway):
    response = gateway.get("/folded-header", headers={"Cookie": "__Host-flow_preview=test-only-capability"})
    assert response.status_code == 200
    assert "\r" not in response.headers["x-preview"]
    assert "\n" not in response.headers["x-preview"]
    assert "x-injected" not in response.headers
