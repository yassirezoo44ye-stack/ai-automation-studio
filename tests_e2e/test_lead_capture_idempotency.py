"""SEC-03: re-sending the same lead-capture request must not create a second
lead or a second follow-up, including when the copies arrive concurrently.

Real app, real API key, real PostgreSQL. The org has an active
lead-follow-up automation so follow-up runs are observable as rows in
automation_runs.
"""
from __future__ import annotations

import asyncio
import uuid

import pytest
import pytest_asyncio

from tests_e2e.harness import tenants

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def org(e2e_transport):
    async with tenants(e2e_transport, "c", "d", ip_prefix="10.98.0") as tenants_:
        c = tenants_["c"]
        r = await c.req("POST", f"/api/orgs/{c.org_id}/api-keys",
                        json={"name": "website form", "scopes": ["write"]})
        assert r.status_code == 201, r.text
        c.api_key = r.json()["api_key"]
        r = await c.req("POST", "/api/automations", json={
            "name": "lead follow-up", "is_active": True,
            "definition": {"lead_followup": "true",
                           "steps": [{"id": "s1", "name": "noop", "tool": "noop", "args": {}}]},
        })
        assert r.status_code == 201, r.text
        d = tenants_["d"]
        r = await d.req("POST", f"/api/orgs/{d.org_id}/api-keys",
                        json={"name": "other org form", "scopes": ["write"]})
        d.api_key = r.json()["api_key"]
        yield tenants_


async def _capture(t, body: dict, key: str | None = None, ip: str = "203.0.113.7"):
    headers = {"X-API-Key": t.api_key, "X-Forwarded-For": ip}
    if key:
        headers["Idempotency-Key"] = key
    return await t.client.post("/api/leads/capture", json=body, headers=headers)


async def _counts(org_id: str, email: str) -> tuple[int, int]:
    from app.core.db import get_pool

    async with get_pool().acquire() as conn:
        leads = await conn.fetchval(
            "SELECT count(*) FROM leads WHERE organization_id = $1 AND lower(email) = lower($2)",
            uuid.UUID(org_id), email)
        runs = await conn.fetchval(
            "SELECT count(*) FROM automation_runs r JOIN leads l "
            "  ON l.id::text = r.context->>'lead_id' "
            "WHERE r.organization_id = $1 AND lower(l.email) = lower($2) "
            "  AND r.triggered_by = 'lead_capture'",
            uuid.UUID(org_id), email)
    return leads, runs


def _body(email: str) -> dict:
    return {"name": "Synthetic Prospect", "email": email, "phone": "+971500000000",
            "source": "landing-page"}


async def test_sequential_resend_without_key_is_deduplicated(org):
    c = org["c"]
    email = f"p-{uuid.uuid4().hex[:8]}@example.com"
    first = await _capture(c, _body(email))
    second = await _capture(c, _body(email))
    assert first.status_code == 201, first.text
    assert second.status_code in (200, 201), second.text
    assert second.json()["id"] == first.json()["id"]
    assert await _counts(c.org_id, email) == (1, 1)


async def test_concurrent_resend_without_key_is_deduplicated(org):
    c = org["c"]
    email = f"p-{uuid.uuid4().hex[:8]}@example.com"
    results = await asyncio.gather(*[_capture(c, _body(email)) for _ in range(6)])
    ok = [r for r in results if r.status_code in (200, 201)]
    assert ok, [r.text for r in results]
    assert all(r.status_code in (200, 201, 409) for r in results), [r.status_code for r in results]
    assert len({r.json()["id"] for r in ok}) == 1
    assert await _counts(c.org_id, email) == (1, 1)


async def test_idempotency_key_replays_and_runs_once(org):
    c = org["c"]
    email = f"p-{uuid.uuid4().hex[:8]}@example.com"
    key = str(uuid.uuid4())
    results = await asyncio.gather(*[_capture(c, _body(email), key=key) for _ in range(5)])
    ok = [r for r in results if r.status_code in (200, 201)]
    assert ok and len({r.json()["id"] for r in ok}) == 1, [r.text for r in results]
    again = await _capture(c, _body(email), key=key)
    assert again.status_code in (200, 201) and again.json()["id"] == ok[0].json()["id"]
    assert again.headers.get("Idempotent-Replayed") == "true"
    assert await _counts(c.org_id, email) == (1, 1)


async def test_same_key_with_different_body_is_rejected(org):
    c = org["c"]
    key = str(uuid.uuid4())
    first = await _capture(c, _body(f"p-{uuid.uuid4().hex[:8]}@example.com"), key=key)
    assert first.status_code == 201, first.text
    other = await _capture(c, _body(f"p-{uuid.uuid4().hex[:8]}@example.com"), key=key)
    assert other.status_code == 422, other.text


async def test_deduplication_is_per_organization(org):
    c, d = org["c"], org["d"]
    email = f"p-{uuid.uuid4().hex[:8]}@example.com"
    key = str(uuid.uuid4())
    rc = await _capture(c, _body(email), key=key)
    rd = await _capture(d, _body(email), key=key)
    assert rc.status_code == 201 and rd.status_code == 201, (rc.text, rd.text)
    assert rc.json()["id"] != rd.json()["id"]
    assert (await _counts(c.org_id, email))[0] == 1
    assert (await _counts(d.org_id, email))[0] == 1


async def test_different_people_are_not_merged(org):
    c = org["c"]
    e1, e2 = (f"p-{uuid.uuid4().hex[:8]}@example.com" for _ in range(2))
    r1, r2 = await _capture(c, _body(e1)), await _capture(c, _body(e2))
    assert r1.status_code == r2.status_code == 201
    assert r1.json()["id"] != r2.json()["id"]
