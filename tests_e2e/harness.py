"""Shared E2E harness: boot the real app and sign up synthetic tenants
through the public API (register -> verify e-mail -> login -> create org)."""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

import httpx

PASSWORD = "ValidPass123!"


class Tenant:
    def __init__(self, label: str, client: httpx.AsyncClient, ip: str):
        self.label = label
        self.client = client
        self.email = f"flow-e2e-{label}-{uuid.uuid4().hex[:10]}@example.com"
        self.token = ""
        self.user_id = ""
        self.org_id = ""
        self.ip = ip

    def h(self, org_id: str | None = None) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self.token}", "X-Forwarded-For": self.ip}
        org = self.org_id if org_id is None else org_id
        if org:
            headers["X-Organization-Id"] = org
        return headers

    async def req(self, method: str, url: str, *, org_id: str | None = None, **kw) -> httpx.Response:
        return await self.client.request(method, url, headers=self.h(org_id), **kw)


async def sign_up(t: Tenant) -> None:
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
    c.cookies.clear()  # identity comes only from the bearer token
    r = await c.post("/api/orgs", headers=t.h(org_id=""), json={"name": f"E2E Org {t.label.upper()}"})
    assert r.status_code == 201, r.text
    t.org_id = r.json()["id"]


@asynccontextmanager
async def tenants(transport: httpx.AsyncBaseTransport, *labels: str, ip_prefix: str):
    """Yield {label: Tenant}, each signed up through the public API."""
    clients = [httpx.AsyncClient(transport=transport, base_url="http://e2e") for _ in labels]
    try:
        out = {}
        for i, (label, client) in enumerate(zip(labels, clients, strict=True), start=1):
            out[label] = Tenant(label, client, f"{ip_prefix}.{i}")
            await sign_up(out[label])
        yield out
    finally:
        for client in clients:
            await client.aclose()
