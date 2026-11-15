"""SEC-02: tenant isolation through real HTTP, real auth and real PostgreSQL.

Two synthetic tenants are created through the public API exactly as a
customer would: register -> verify e-mail -> log in -> create organization.
Tenant A then creates one record of each resource type. Tenant B, holding a
perfectly valid session of its own, tries every read / write / delete path
against A's records, in two ways:

  * with B's own organization header and A's record id (IDOR), and
  * with A's organization header (membership bypass).

Every attempt must fail without revealing the record, and A's record must
be unchanged afterwards (checked through A's own session).

Resources: leads, projects, conversations, automations (+ runs), devices,
project files, notifications, invoices. Also covers org settings/members.
"""
from __future__ import annotations

import uuid

import httpx
import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio(loop_scope="module")

PASSWORD = "ValidPass123!"
DENIED = {401, 403, 404}


class Tenant:
    def __init__(self, label: str, client: httpx.AsyncClient):
        self.label = label
        self.client = client
        self.email = f"flow-e2e-{label}-{uuid.uuid4().hex[:10]}@example.com"
        self.token = ""
        self.user_id = ""
        self.org_id = ""
        self.ip = f"10.99.0.{1 if label == 'a' else 2}"

    def h(self, org_id: str | None = None) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self.token}", "X-Forwarded-For": self.ip}
        org = self.org_id if org_id is None else org_id
        if org:
            headers["X-Organization-Id"] = org
        return headers

    async def req(self, method: str, url: str, *, org_id: str | None = None, **kw) -> httpx.Response:
        return await self.client.request(method, url, headers=self.h(org_id), **kw)


async def _sign_up(t: Tenant) -> None:
    from app.core.db import get_pool

    c = t.client
    r = await c.post("/api/auth/register", headers={"X-Forwarded-For": t.ip},
                     json={"name": f"E2E {t.label.upper()}", "email": t.email, "password": PASSWORD})
    assert r.status_code == 201, r.text
    async with get_pool().acquire() as conn:
        token = await conn.fetchval(
            "SELECT e.token FROM email_verification_tokens e JOIN users u ON u.id = e.user_id "
            "WHERE u.email = $1", t.email)
    assert (await c.get(f"/api/auth/verify-email/{token}")).status_code == 200
    r = await c.post("/api/auth/login", headers={"X-Forwarded-For": t.ip},
                     json={"email": t.email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    body = r.json()
    t.token, t.user_id = body["access_token"], str(body["user"]["id"])
    c.cookies.clear()  # identity comes only from the bearer token below
    r = await c.post("/api/orgs", headers=t.h(org_id=""), json={"name": f"E2E Org {t.label.upper()}"})
    assert r.status_code == 201, r.text
    t.org_id = r.json()["id"]


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def world():
    from app.factory import create_app, lifespan

    app = create_app()
    async with lifespan(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://e2e") as ca, \
                   httpx.AsyncClient(transport=transport, base_url="http://e2e") as cb:
            a, b = Tenant("a", ca), Tenant("b", cb)
            await _sign_up(a)
            await _sign_up(b)
            yield {"a": a, "b": b, "seed": {}}


def _denied(r: httpx.Response, what: str, secret: str = "") -> None:
    assert r.status_code in DENIED, f"{what}: expected denial, got {r.status_code} {r.text[:300]}"
    if secret:
        assert secret not in r.text, f"{what}: response leaked {secret!r}"


async def _probe_both_ways(b: Tenant, a: Tenant, method: str, url: str, what: str,
                           secret: str = "", **kw) -> None:
    _denied(await b.req(method, url, **kw), f"{what} [B org header]", secret)
    _denied(await b.req(method, url, org_id=a.org_id, **kw), f"{what} [A org header]", secret)


# ── organizations ─────────────────────────────────────────────────────────────

async def test_org_record_settings_and_members_are_private(world):
    a, b = world["a"], world["b"]
    for method, path in [("GET", ""), ("GET", "/settings"), ("GET", "/members"),
                         ("GET", "/invitations"), ("GET", "/activity"), ("GET", "/api-keys")]:
        _denied(await b.req(method, f"/api/orgs/{a.org_id}{path}", org_id=a.org_id),
                f"org {method} {path or '/'}", a.email)
    _denied(await b.req("PATCH", f"/api/orgs/{a.org_id}", org_id=a.org_id, json={"name": "pwned"}),
            "org rename")
    _denied(await b.req("POST", f"/api/orgs/{a.org_id}/invitations", org_id=a.org_id,
                        json={"email": b.email, "role": "admin"}), "invite self into A")
    _denied(await b.req("DELETE", f"/api/orgs/{a.org_id}", org_id=a.org_id), "delete org A")
    r = await a.req("GET", f"/api/orgs/{a.org_id}")
    assert r.status_code == 200 and r.json()["name"] == "E2E Org A"
    mine = (await b.req("GET", "/api/orgs", org_id="")).json()
    assert a.org_id not in str(mine)


# ── leads ─────────────────────────────────────────────────────────────────────

async def test_leads_are_isolated(world):
    a, b = world["a"], world["b"]
    secret = f"lead-{uuid.uuid4().hex[:8]}"
    r = await a.req("POST", "/api/leads", json={"name": secret, "email": "lead@example.com", "source": "e2e"})
    assert r.status_code in (200, 201), r.text
    lead_id = r.json()["id"]

    await _probe_both_ways(b, a, "GET", f"/api/leads/{lead_id}", "lead read", secret)
    await _probe_both_ways(b, a, "PATCH", f"/api/leads/{lead_id}/status", "lead status change",
                           json={"status": "lost"})
    await _probe_both_ways(b, a, "POST", f"/api/leads/{lead_id}/qualify", "lead qualify")
    _denied(await b.req("GET", "/api/leads", org_id=a.org_id), "lead list in A", secret)
    r = await b.req("GET", "/api/leads")
    assert r.status_code == 200 and secret not in r.text

    r = await a.req("GET", f"/api/leads/{lead_id}")
    assert r.status_code == 200 and r.json()["status"] == "new", r.text


# ── projects + files ──────────────────────────────────────────────────────────

async def test_projects_and_project_files_are_isolated(world):
    a, b = world["a"], world["b"]
    secret = f"proj-{uuid.uuid4().hex[:8]}"
    r = await a.req("POST", "/api/projects", json={"name": secret, "description": "e2e"})
    assert r.status_code in (200, 201), r.text
    pid = r.json()["id"]
    world["seed"]["project_id"] = pid
    r = await a.req("POST", f"/api/projects/{pid}/upload",
                    files=[("files", ("notes.txt", f"file-body-{secret}".encode(), "text/plain"))])
    assert r.status_code in (200, 201), r.text

    await _probe_both_ways(b, a, "GET", f"/api/projects/{pid}", "project read", secret)
    await _probe_both_ways(b, a, "PUT", f"/api/projects/{pid}", "project update",
                           json={"name": "pwned", "description": "x"})
    await _probe_both_ways(b, a, "GET", f"/api/projects/{pid}/files", "file list", "notes.txt")
    await _probe_both_ways(b, a, "GET", f"/api/projects/{pid}/files/notes.txt", "file read",
                           f"file-body-{secret}")
    await _probe_both_ways(b, a, "POST", f"/api/projects/{pid}/upload", "file upload",
                           files=[("files", ("evil.txt", b"x", "text/plain"))])
    await _probe_both_ways(b, a, "DELETE", f"/api/projects/{pid}/files", "file wipe")
    await _probe_both_ways(b, a, "DELETE", f"/api/projects/{pid}", "project delete")
    r = await b.req("GET", "/api/projects")
    assert r.status_code == 200 and secret not in r.text

    r = await a.req("GET", f"/api/projects/{pid}")
    assert r.status_code == 200 and r.json()["name"] == secret
    r = await a.req("GET", f"/api/projects/{pid}/files/notes.txt")
    assert r.status_code == 200 and f"file-body-{secret}" in r.text
    assert "evil.txt" not in (await a.req("GET", f"/api/projects/{pid}/files")).text


# ── conversations ─────────────────────────────────────────────────────────────

async def test_conversations_are_isolated(world):
    a, b = world["a"], world["b"]
    pid = world["seed"].get("project_id")
    if pid is None:
        pid = (await a.req("POST", "/api/projects", json={"name": "conv-host"})).json()["id"]
    secret = f"conv-{uuid.uuid4().hex[:8]}"
    r = await a.req("POST", "/api/conversations", json={"project_id": pid, "title": secret})
    assert r.status_code in (200, 201), r.text
    cid = r.json()["id"]

    await _probe_both_ways(b, a, "GET", f"/api/conversations/{cid}/messages", "conversation read")
    await _probe_both_ways(b, a, "GET", f"/api/export/conversations/{cid}", "conversation export", secret)
    await _probe_both_ways(b, a, "DELETE", f"/api/conversations/{cid}", "conversation delete")
    _denied(await b.req("POST", "/api/conversations", json={"project_id": pid, "title": "x"}),
            "create conversation in A's project")
    r = await b.req("GET", "/api/conversations")
    assert r.status_code == 200 and secret not in r.text
    r = await b.req("GET", "/api/search", params={"q": secret})
    assert secret not in r.text

    r = await a.req("GET", "/api/conversations")
    assert r.status_code == 200 and secret in r.text


# ── automations ───────────────────────────────────────────────────────────────

async def test_automations_and_runs_are_isolated(world):
    a, b = world["a"], world["b"]
    secret = f"auto-{uuid.uuid4().hex[:8]}"
    r = await a.req("POST", "/api/automations", json={
        "name": secret, "description": "e2e",
        "definition": {"steps": [{"id": "s1", "name": "noop", "tool": "noop", "args": {}}]},
    })
    assert r.status_code == 201, r.text
    def_id = r.json()["id"]

    await _probe_both_ways(b, a, "GET", f"/api/automations/{def_id}", "automation read", secret)
    await _probe_both_ways(b, a, "PUT", f"/api/automations/{def_id}", "automation update",
                           json={"name": "pwned"})
    await _probe_both_ways(b, a, "POST", f"/api/automations/{def_id}/activate", "automation activate")
    await _probe_both_ways(b, a, "POST", f"/api/automations/{def_id}/run", "automation run", json={})
    await _probe_both_ways(b, a, "DELETE", f"/api/automations/{def_id}", "automation delete")
    _denied(await b.req("GET", "/api/automations", org_id=a.org_id), "automation list in A", secret)
    r = await b.req("GET", "/api/automations")
    assert r.status_code == 200 and secret not in r.text

    r = await a.req("GET", f"/api/automations/{def_id}")
    assert r.status_code == 200 and r.json()["name"] == secret and r.json()["is_active"] is False

    # A run owned by A.
    r = await a.req("POST", f"/api/automations/{def_id}/run", json={})
    assert r.status_code == 202, r.text
    run_id = r.json()["run_id"]
    await _probe_both_ways(b, a, "GET", f"/api/automation-runs/{run_id}", "run read")
    await _probe_both_ways(b, a, "POST", f"/api/automation-runs/{run_id}/cancel", "run cancel")
    for decision in ("approve", "reject"):
        await _probe_both_ways(b, a, "POST", f"/api/automation-runs/{run_id}/steps/s1/{decision}",
                               f"run step {decision}")
    r = await b.req("GET", "/api/automation-runs")
    assert r.status_code == 200 and run_id not in r.text
    assert run_id not in (await b.req("GET", "/api/automation-runs/pending-approvals")).text
    r = await a.req("GET", f"/api/automation-runs/{run_id}")
    assert r.status_code == 200 and r.json()["status"] != "cancelled", r.text


# ── devices ───────────────────────────────────────────────────────────────────

async def test_devices_are_isolated(world):
    a, b = world["a"], world["b"]
    r = await a.req("POST", "/api/devices/enroll-token", json={})
    if r.status_code == 503:
        pytest.skip("Device Control disabled on this server")
    assert r.status_code == 200, r.text
    secret = f"dev-{uuid.uuid4().hex[:8]}"
    r = await a.client.post("/api/devices/enroll", json={
        "token": r.json()["enrollment_token"], "device_name": secret, "platform": "windows"})
    assert r.status_code == 200, r.text
    device_id = str(r.json().get("device_id") or r.json().get("id"))

    await _probe_both_ways(b, a, "GET", f"/api/devices/{device_id}", "device read", secret)
    await _probe_both_ways(b, a, "POST", f"/api/devices/{device_id}/rotate-credential", "device rotate")
    await _probe_both_ways(b, a, "GET", f"/api/devices/{device_id}/session-token", "device session token",
                           params={"session_id": str(uuid.uuid4())})
    await _probe_both_ways(b, a, "POST", f"/api/devices/{device_id}/revoke", "device revoke")
    await _probe_both_ways(b, a, "DELETE", f"/api/devices/{device_id}", "device delete")
    r = await b.req("GET", "/api/devices/")
    assert r.status_code == 200 and secret not in r.text

    r = await a.req("GET", f"/api/devices/{device_id}")
    assert r.status_code == 200 and secret in r.text and "revoked" not in r.json().get("status", "")


# ── notifications ─────────────────────────────────────────────────────────────

async def test_notifications_are_isolated(world):
    from app.core.notifications import get_notification_service

    a, b = world["a"], world["b"]
    secret = f"notif-{uuid.uuid4().hex[:8]}"
    note = await get_notification_service().create(
        user_id=a.user_id, organization_id=a.org_id, type_="e2e", title=secret, message=secret)
    nid = str(note["id"])

    for method, path in [("POST", f"/{nid}/read"), ("POST", f"/{nid}/archive"), ("DELETE", f"/{nid}")]:
        _denied(await b.req(method, f"/api/notifications{path}"), f"notification {method} {path}")
    r = await b.req("GET", "/api/notifications", params={"include_archived": "true"})
    assert r.status_code == 200 and secret not in r.text
    await b.req("POST", "/api/notifications/read-all")

    r = await a.req("GET", "/api/notifications", params={"unread_only": "true"})
    assert r.status_code == 200 and secret in r.text, "B's actions changed A's notification"


# ── invoices ──────────────────────────────────────────────────────────────────

async def test_invoices_are_isolated(world):
    from app.core.db import get_pool

    a, b = world["a"], world["b"]
    stripe_id = f"in_e2e_{uuid.uuid4().hex[:12]}"
    async with get_pool().acquire() as conn:
        inv_id = await conn.fetchval(
            "INSERT INTO invoices (organization_id, stripe_invoice_id, stripe_customer_id, status, "
            "amount_due_cents) VALUES ($1, $2, 'cus_e2e', 'open', 4242) RETURNING id",
            uuid.UUID(a.org_id), stripe_id)

    for path in ["/invoices", f"/invoices/{inv_id}", "", "/payments", "/payment-methods", "/credits"]:
        url = f"/api/orgs/{a.org_id}/billing{path}"
        _denied(await b.req("GET", url, org_id=a.org_id), f"billing GET {path or '/'} [A org header]", stripe_id)
        r = await b.req("GET", url)  # B's own org header, A's org in the path
        assert stripe_id not in r.text, f"billing GET {path or '/'} leaked A's invoice: {r.text[:300]}"
    r = await b.req("GET", f"/api/orgs/{b.org_id}/billing/invoices/{inv_id}")
    _denied(r, "invoice by id from B's org", stripe_id)

    r = await a.req("GET", f"/api/orgs/{a.org_id}/billing/invoices")
    assert r.status_code == 200 and stripe_id in r.text
