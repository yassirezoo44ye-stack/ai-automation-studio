"""Section 6: the twelve user journeys, end to end.

Real app (lifespan), real auth, real PostgreSQL, real HTTP through ASGI.
Synthetic data only (example.com addresses, generated names). External
vendors are replaced by sinks so nothing leaves the process:

  * e-mail: no SMTP_HOST, so the app logs instead of sending; the
    verification and invitation tokens are read from the database, which
    is what the e-mail would have carried;
  * AI: the "anthropic" provider is swapped for the offline DevMockProvider
    (see ``ai_sink``), so every AI code path runs except the vendor call;
  * payments: no STRIPE_SECRET_KEY, so checkout must refuse cleanly.

Each test is one journey, and each step asserts what the person would see.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
import uuid

import httpx
import pytest

from tests_e2e.harness import PASSWORD, tenants

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _db(sql: str, *args):
    from app.core.db import get_pool

    async with get_pool().acquire() as conn:
        return await conn.fetch(sql, *args)


def _ok(r: httpx.Response, what: str, codes=(200, 201)) -> dict:
    assert r.status_code in codes, f"{what}: {r.status_code} {r.text[:400]}"
    try:
        return r.json()
    except ValueError:
        return {}


# ── 1. Account ────────────────────────────────────────────────────────────────

async def test_journey_01_account(e2e_transport):
    """Visit -> register -> verify e-mail -> log in -> manage session -> log out."""
    async with httpx.AsyncClient(transport=e2e_transport, base_url="http://e2e") as c:
        ip = {"X-Forwarded-For": "10.97.1.1"}
        email = f"flow-e2e-j1-{uuid.uuid4().hex[:8]}@example.com"

        # Visit: the public endpoints the landing/sign-in page needs.
        assert (await c.get("/health")).status_code == 200
        _ok(await c.get("/api/auth/oauth-config"), "oauth config")

        # Register. Logging in before verifying must be refused.
        _ok(await c.post("/api/auth/register", headers=ip,
                         json={"name": "Journey One", "email": email, "password": PASSWORD}),
            "register", (201,))
        r = await c.post("/api/auth/login", headers=ip, json={"email": email, "password": PASSWORD})
        assert r.status_code in (401, 403), f"unverified login allowed: {r.status_code}"

        # Registering the same address again must not create a second account.
        r = await c.post("/api/auth/register", headers=ip,
                         json={"name": "Journey One", "email": email.upper(), "password": PASSWORD})
        assert r.status_code in (201, 400, 409), r.text
        assert len(await _db("SELECT 1 FROM users WHERE lower(email)=lower($1)", email)) == 1

        # Verify (the token is what the e-mail would carry); a token works once.
        token = (await _db("SELECT e.token FROM email_verification_tokens e JOIN users u "
                           "ON u.id=e.user_id WHERE u.email=$1", email))[0]["token"]
        _ok(await c.get(f"/api/auth/verify-email/{token}"), "verify")
        assert (await c.get(f"/api/auth/verify-email/{token}")).status_code == 400

        # Log in: wrong password refused, right one accepted.
        r = await c.post("/api/auth/login", headers=ip, json={"email": email, "password": "Wrong-pass-1"})
        assert r.status_code == 401
        body = _ok(await c.post("/api/auth/login", headers=ip,
                                json={"email": email, "password": PASSWORD}), "login")
        access, refresh = body["access_token"], body["refresh_token"]
        c.cookies.clear()
        auth = {"Authorization": f"Bearer {access}", **ip}
        me = _ok(await c.get("/api/auth/me", headers=auth), "me")
        assert me["email"] == email

        # Session management: the session is listed, refresh rotates the token.
        sessions = _ok(await c.get("/api/auth/sessions", headers=auth), "sessions")
        assert len(sessions["sessions"] if isinstance(sessions, dict) else sessions) >= 1
        rotated = _ok(await c.post("/api/auth/refresh", headers=ip,
                                   json={"refresh_token": refresh}), "refresh")
        assert rotated["access_token"] and rotated["refresh_token"] != refresh
        # The old refresh token must be dead after rotation.
        assert (await c.post("/api/auth/refresh", headers=ip,
                             json={"refresh_token": refresh})).status_code == 401
        c.cookies.clear()

        # Log out: the refresh token stops working.
        _ok(await c.post("/api/auth/logout", headers=ip,
                         json={"refresh_token": rotated["refresh_token"]}), "logout")
        assert (await c.post("/api/auth/refresh", headers=ip,
                             json={"refresh_token": rotated["refresh_token"]})).status_code == 401

        # Log out everywhere also revokes access tokens already issued.
        body = _ok(await c.post("/api/auth/login", headers=ip,
                                json={"email": email, "password": PASSWORD}), "login 2")
        c.cookies.clear()
        auth2 = {"Authorization": f"Bearer {body['access_token']}", **ip}
        _ok(await c.post("/api/auth/logout-all", headers=auth2), "logout-all")
        assert (await c.get("/api/auth/me", headers=auth2)).status_code == 401


# ── 2. Organization ───────────────────────────────────────────────────────────

async def test_journey_02_organization(e2e_transport):
    """Create org -> add member -> set role -> permissions -> data isolation."""
    async with tenants(e2e_transport, "own", "mem", "out", ip_prefix="10.97.2") as t:
        own, mem, out = t["own"], t["mem"], t["out"]

        # A new org is on the Free plan (1 seat), so inviting is refused with
        # a clear message. Payment is out of scope here (journey 10), so the
        # org is moved to Starter (3 seats) directly, as a paid checkout would.
        r = await own.req("POST", f"/api/orgs/{own.org_id}/invitations",
                          json={"email": mem.email, "role": "viewer"})
        assert r.status_code == 409 and "seat limit" in r.text, r.text
        await _db("UPDATE organizations SET plan='starter' WHERE id=$1", uuid.UUID(own.org_id))

        # Invite the second person as a viewer and accept with the e-mailed token.
        inv = _ok(await own.req("POST", f"/api/orgs/{own.org_id}/invitations",
                                json={"email": mem.email, "role": "viewer"}), "invite")
        _ok(await mem.req("POST", "/api/orgs/invitations/accept", org_id="",
                          json={"token": inv["token"]}), "accept")
        members = _ok(await own.req("GET", f"/api/orgs/{own.org_id}/members"), "members")
        rows = members["members"] if isinstance(members, dict) else members
        assert any(str(m.get("user_id")) == mem.user_id and m.get("role") == "viewer" for m in rows)

        # The invitation cannot be used twice.
        r = await out.req("POST", "/api/orgs/invitations/accept", org_id="", json={"token": inv["token"]})
        assert r.status_code in (400, 403, 404, 409, 410), r.text

        # Viewer: may read, may not write.
        lead = _ok(await own.req("POST", "/api/leads", json={"name": "Synthetic Lead J2"}), "lead")
        _ok(await mem.req("GET", "/api/leads", org_id=own.org_id), "viewer reads leads")
        r = await mem.req("POST", "/api/leads", org_id=own.org_id, json={"name": "should fail"})
        assert r.status_code == 403, f"viewer created a lead: {r.status_code}"
        r = await mem.req("POST", f"/api/orgs/{own.org_id}/invitations", org_id=own.org_id,
                          json={"email": "x@example.com", "role": "admin"})
        assert r.status_code == 403, f"viewer invited: {r.status_code}"
        r = await mem.req("PATCH", f"/api/orgs/{own.org_id}/members/{mem.user_id}", org_id=own.org_id,
                          json={"role": "owner"})
        assert r.status_code == 403, f"viewer promoted itself: {r.status_code}"

        # Promote to developer: now writes are allowed where the role says so.
        _ok(await own.req("PATCH", f"/api/orgs/{own.org_id}/members/{mem.user_id}",
                          json={"role": "developer"}), "set role")
        _ok(await mem.req("POST", "/api/automations", org_id=own.org_id,
                          json={"name": "dev workflow", "definition": {"steps": []}}), "developer creates")

        # Isolation: the outsider sees nothing of the org.
        for path in ("", "/members", "/settings"):
            r = await out.req("GET", f"/api/orgs/{own.org_id}{path}", org_id=own.org_id)
            assert r.status_code in (403, 404), f"outsider read org{path}: {r.status_code}"
        r = await out.req("GET", f"/api/leads/{lead['id']}", org_id=own.org_id)
        assert r.status_code in (403, 404)
        r = await out.req("GET", f"/api/leads/{lead['id']}")
        assert r.status_code == 404

        # Removing the member ends their access.
        _ok(await own.req("DELETE", f"/api/orgs/{own.org_id}/members/{mem.user_id}"),
            "remove member", (200, 204))
        r = await mem.req("GET", "/api/leads", org_id=own.org_id)
        assert r.status_code in (403, 404), f"removed member still reads: {r.status_code}"


# ── 11. Security ──────────────────────────────────────────────────────────────

async def test_journey_11_security(e2e_transport):
    """Expired sessions, unauthorized access, rate limits, input validation."""
    import jwt as pyjwt

    async with tenants(e2e_transport, "sec", ip_prefix="10.97.11") as t:
        s = t["sec"]
        c = s.client

        # No credentials / garbage / tampered / expired token.
        assert (await c.get("/api/leads")).status_code == 401
        assert (await c.get("/api/leads", headers={"Authorization": "Bearer nope"})).status_code == 401
        claims = pyjwt.decode(s.token, options={"verify_signature": False})
        forged = pyjwt.encode({**claims, "sub": str(uuid.uuid4())}, "not-the-real-secret-but-long-enough-for-hs256", algorithm="HS256")
        assert (await c.get("/api/auth/me", headers={"Authorization": f"Bearer {forged}"})).status_code == 401
        from app.core.config import SESSION_SECRET
        expired = pyjwt.encode({**claims, "iat": claims["iat"] - 3600, "exp": claims["iat"] - 1800},
                               SESSION_SECRET, algorithm="HS256")
        r = await c.get("/api/leads", headers={"Authorization": f"Bearer {expired}"})
        assert r.status_code == 401 and "token_expired" in r.text, r.text

        # Input validation: bad e-mail, short password, oversized and wrong types.
        bad = [
            {"name": "x", "email": "not-an-email", "password": PASSWORD},
            {"name": "x", "email": "ok@example.com", "password": "short"},
            {"name": "x" * 10_000, "email": "ok2@example.com", "password": PASSWORD},
            {"name": None, "email": 5, "password": []},
        ]
        for body in bad:
            r = await c.post("/api/auth/register", headers={"X-Forwarded-For": "10.97.11.50"}, json=body)
            assert r.status_code in (400, 422), f"accepted bad input {str(body)[:80]}: {r.status_code}"
        r = await s.req("POST", "/api/leads", json={"name": ""})
        assert r.status_code in (400, 422)
        r = await c.post("/api/leads", content=b"{not json",
                         headers={**s.h(), "Content-Type": "application/json"})
        assert r.status_code in (400, 422)
        # A malformed id in any URL is the caller's mistake (4xx), never a 500.
        # Every GET route with path parameters is tried with "not-a-uuid".
        crashed = []
        app = e2e_transport.app
        for path, ops in app.openapi()["paths"].items():
            if "get" not in ops or "{" not in path or "stream" in path or path.startswith("/ws"):
                continue
            url = "".join(seg if not seg.startswith("{") else "not-a-uuid"
                          for seg in path.replace("{", "/{").split("/") if seg)
            url = "/" + "/".join(p if not p.startswith("{") else "not-a-uuid" for p in path.strip("/").split("/"))
            try:
                r = await s.req("GET", url)
                code = r.status_code
            except Exception as exc:  # ASGITransport re-raises unhandled errors
                code = f"{type(exc).__name__}: {str(exc)[:60]}"
            if not isinstance(code, int) or code >= 500:
                crashed.append((url, code))
        assert not crashed, f"{len(crashed)} routes fail on a malformed id: {crashed}"
        # SQL-looking input is stored as text, not executed.
        name = "Robert'); DROP TABLE leads;--"
        lead = _ok(await s.req("POST", "/api/leads", json={"name": name}), "sql-ish lead")
        assert (await s.req("GET", f"/api/leads/{lead['id']}")).json()["name"] == name

        # Rate limit: repeated failed logins from one address get 429.
        ip = {"X-Forwarded-For": "10.97.11.99"}
        codes = [(await c.post("/api/auth/login", headers=ip,
                               json={"email": s.email, "password": "Wrong-pass-1"})).status_code
                 for _ in range(15)]
        assert 429 in codes, f"no rate limit after 15 failed logins: {codes}"
        # The lock is per account, not per address: the right password from
        # another address is refused too until it expires. That stops
        # password guessing, at the cost that anyone who knows the address
        # can lock its owner out for 15 minutes (recorded as a residual risk).
        r = await c.post("/api/auth/login", headers={"X-Forwarded-For": "10.97.11.98"},
                         json={"email": s.email, "password": PASSWORD})
        assert r.status_code == 429 and "15 minutes" in r.text, r.text
        # A session that already exists keeps working during the lock.
        assert (await s.req("GET", "/api/auth/me")).status_code == 200


# ── shared: AI sink ───────────────────────────────────────────────────────────

class _Outage(Exception):
    pass


@pytest.fixture
def ai_sink(monkeypatch):
    """Route every "anthropic" call to the offline DevMockProvider.

    The app's own code runs unchanged (routing, quotas, persistence, SSE);
    only the vendor call is replaced. ``ai_sink.down = True`` makes the
    provider fail, for the recovery journey.
    """
    from app.ai.providers.dev_mock import DevMockProvider
    from app.core.ai.registry.registry import platform_registry

    class Sink(DevMockProvider):
        provider_id = "anthropic"
        down = False
        calls = 0

        async def complete(self, request):
            type(self).calls += 1
            if type(self).down:
                raise _Outage("provider unavailable (simulated)")
            return await super().complete(request)

        async def stream(self, request, *a, **kw):
            type(self).calls += 1
            if type(self).down:
                raise _Outage("provider unavailable (simulated)")
            async for chunk in super().stream(request, *a, **kw):
                yield chunk

    sink = Sink()
    monkeypatch.setitem(platform_registry._providers, "anthropic", sink)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-sink-not-a-real-key")
    # The breaker keeps a failed provider out for 30 s before one trial call.
    # Same state machine, 1 s cooldown, so recovery is tested without waiting.
    from app.ai.circuit_breaker import circuit_breaker
    monkeypatch.setattr(circuit_breaker, "_cooldown", 1.0)
    monkeypatch.setattr(circuit_breaker, "_circuits", {})
    yield Sink


async def _provider_back(sink) -> None:
    """End the outage and let the breaker's cooldown pass (half-open trial next)."""
    sink.down = False
    await asyncio.sleep(1.2)


def _sse(text: str) -> list[dict]:
    out = []
    for line in text.splitlines():
        if line.startswith("data: "):
            try:
                out.append(json.loads(line[6:]))
            except ValueError:
                pass
    return out


# ── 3. Building apps ──────────────────────────────────────────────────────────

async def test_journey_03_build_app(e2e_transport, ai_sink):
    """Project -> describe app -> generate files -> preview -> edit -> re-run -> export."""
    async with tenants(e2e_transport, "bld", ip_prefix="10.97.3") as t:
        b = t["bld"]
        proj = _ok(await b.req("POST", "/api/projects",
                               json={"name": "J3 Booking App", "description": "synthetic"}), "project")
        pid = proj["id"]

        r = await b.req("POST", "/api/build/stream",
                        json={"project_id": pid, "prompt": "A one-page landing site for a barber shop with opening hours"})
        assert r.status_code == 200, r.text[:300]
        events = _sse(r.text)
        assert not [e for e in events if e.get("type") == "error"], events[-3:]
        files = _ok(await b.req("GET", f"/api/projects/{pid}/files"), "files")
        names = [f["path"] if isinstance(f, dict) else f for f in (files.get("files", files))]
        assert names, f"no files generated; events: {[e.get('type') for e in events]}"

        # Preview: a generated file can be read back.
        first = names[0]
        r = await b.req("GET", f"/api/projects/{pid}/files/{first}")
        assert r.status_code == 200 and r.text, r.status_code

        # Edit: a second build on the same project changes or adds files.
        r = await b.req("POST", "/api/build/stream",
                        json={"project_id": pid, "prompt": "Add a gallery section to the landing page"})
        assert r.status_code == 200
        assert not [e for e in _sse(r.text) if e.get("type") == "error"]
        files2 = _ok(await b.req("GET", f"/api/projects/{pid}/files"), "files after edit")
        assert files2

        # An app that needs a server (bookings) is refused when the model only
        # returns interface files, instead of being reported as built.
        r = await b.req("POST", "/api/build/stream",
                        json={"project_id": pid, "prompt": "A booking system with customer accounts"})
        assert any(e.get("type") == "error" and "requires a backend" in e.get("message", "")
                   for e in _sse(r.text)), _sse(r.text)[-2:]

        # Export: the project downloads as a zip containing the files.
        r = await b.req("GET", f"/api/projects/{pid}/download")
        assert r.status_code == 200, r.text[:200]
        import io
        import zipfile
        z = zipfile.ZipFile(io.BytesIO(r.content))
        assert z.namelist(), "empty export"

        # Another user cannot export it.
        async with tenants(e2e_transport, "bld2", ip_prefix="10.97.31") as t2:
            r = await t2["bld2"].req("GET", f"/api/projects/{pid}/download")
            assert r.status_code in (403, 404)


# ── 4. AI assistant ───────────────────────────────────────────────────────────

async def test_journey_04_assistant(e2e_transport, ai_sink):
    """Start chat -> send -> receive -> history saved -> reload -> conversation restored."""
    async with tenants(e2e_transport, "chat", ip_prefix="10.97.4") as t:
        u = t["chat"]
        pid = _ok(await u.req("POST", "/api/projects", json={"name": "J4 chat"}), "project")["id"]

        r = await u.req("POST", "/api/run/stream", json={"project_id": pid, "prompt": "Hello Flow, summarise my week"})
        assert r.status_code == 200
        ev = _sse(r.text)
        conv = next(e["conv_id"] for e in ev if e.get("type") == "conv_id")
        assert any(e.get("type") == "delta" for e in ev), ev[-3:]
        assert any(e.get("type") == "done" for e in ev), ev[-3:]

        # Second turn in the same conversation.
        r = await u.req("POST", "/api/run/stream",
                        json={"project_id": pid, "prompt": "And next week?", "conversation_id": conv})
        assert r.status_code == 200 and not [e for e in _sse(r.text) if e.get("type") == "error"]

        # "Reload": a fresh client with the same session lists and restores it.
        convs = _ok(await u.req("GET", f"/api/conversations?project_id={pid}"), "list")
        convs = convs.get("conversations", convs) if isinstance(convs, dict) else convs
        assert any(str(c["id"]) == conv for c in convs)
        msgs = _ok(await u.req("GET", f"/api/conversations/{conv}/messages"), "messages")
        msgs = msgs.get("messages", msgs) if isinstance(msgs, dict) else msgs
        roles = [m["role"] for m in msgs]
        assert roles == ["user", "assistant", "user", "assistant"], roles
        assert msgs[0]["content"] == "Hello Flow, summarise my week"

        # Two sends at once into one conversation: both stored, none lost.
        await asyncio.gather(*[
            u.req("POST", "/api/run/stream", json={"project_id": pid, "prompt": f"parallel {i}",
                                                   "conversation_id": conv}) for i in range(2)])
        msgs = _ok(await u.req("GET", f"/api/conversations/{conv}/messages"), "messages 2")
        msgs = msgs.get("messages", msgs) if isinstance(msgs, dict) else msgs
        assert sum(1 for m in msgs if m["content"].startswith("parallel")) == 2
        assert len(msgs) == 8

        # Export of the conversation works; another user cannot read it.
        assert (await u.req("GET", f"/api/export/conversations/{conv}")).status_code == 200
        async with tenants(e2e_transport, "chat2", ip_prefix="10.97.41") as t2:
            r = await t2["chat2"].req("GET", f"/api/conversations/{conv}/messages")
            assert r.status_code in (403, 404)


# ── 5. Leads ──────────────────────────────────────────────────────────────────

async def test_journey_05_leads(e2e_transport, ai_sink):
    """Add lead -> qualify -> follow-up -> human approval -> record outcome -> notification."""
    async with tenants(e2e_transport, "lead", ip_prefix="10.97.5") as t:
        u = t["lead"]
        # Follow-up automation whose send step needs a person's approval.
        _ok(await u.req("POST", "/api/automations", json={
            "name": "lead follow-up (approval)", "is_active": True,
            "definition": {"lead_followup": "true", "steps": [
                {"id": "draft", "name": "Draft", "kind": "noop"},
                {"id": "send", "name": "Send follow-up", "kind": "noop",
                 "requires_approval": True, "depends_on": ["draft"]},
            ]},
        }), "automation")
        key = _ok(await u.req("POST", f"/api/orgs/{u.org_id}/api-keys",
                              json={"name": "site form", "scopes": ["write"]}), "api key")["api_key"]

        # A lead arrives from the website form.
        email = f"prospect-{uuid.uuid4().hex[:6]}@example.com"
        r = await u.client.post("/api/leads/capture", headers={"X-API-Key": key, "X-Forwarded-For": "203.0.113.5"},
                                json={"name": "Synthetic Prospect", "email": email, "source": "landing-page"})
        lead = _ok(r, "capture", (201,))
        assert lead["follow_up_status"] == "enqueued", lead

        # Qualify (AI through the sink) and draft a follow-up.
        q = _ok(await u.req("POST", f"/api/leads/{lead['id']}/qualify"), "qualify")
        assert q.get("id") == lead["id"]
        draft = await u.req("POST", f"/api/leads/{lead['id']}/ai-followup", json={"language": "ar"})
        assert draft.status_code in (200, 201, 502), draft.text[:200]

        # The follow-up run waits for a person.
        run = None
        for _ in range(50):
            pend = _ok(await u.req("GET", "/api/automation-runs/pending-approvals"), "pending")
            items = pend["approvals"]
            if items:
                run = items[0]
                break
            await asyncio.sleep(0.1)
        assert run, ("follow-up never reached the approval gate",
                     await _db("SELECT status, error, triggered_by FROM automation_runs WHERE organization_id=$1", uuid.UUID(u.org_id)))
        rows = await _db("SELECT status FROM automation_runs WHERE run_id=$1", str(run["run_id"]))
        assert rows and rows[0]["status"] in ("waiting_approval", "pending", "running", "paused"), rows

        _ok(await u.req("POST", f"/api/automation-runs/{run['run_id']}/steps/{run['step_id']}/approve",
                        json={"note": "ok to send"}), "approve")
        for _ in range(50):
            got = _ok(await u.req("GET", f"/api/automation-runs/{run['run_id']}"), "run")
            if got["status"] in ("completed", "failed"):
                break
            await asyncio.sleep(0.1)
        assert got["status"] == "completed", got

        # Record the outcome.
        _ok(await u.req("PATCH", f"/api/leads/{lead['id']}/status", json={"status": "won"}), "status won")
        assert (await u.req("GET", f"/api/leads/{lead['id']}")).json()["status"] == "won"

        # A notification tells the team about the new lead.
        notes = _ok(await u.req("GET", "/api/notifications"), "notifications")
        assert notes["notifications"], "no notification for a captured lead"


# ── 6. Automation ─────────────────────────────────────────────────────────────

async def test_journey_06_automation(e2e_transport, ai_sink):
    """Create workflow -> validate input -> run -> watch status -> error -> retry."""
    async with tenants(e2e_transport, "auto", ip_prefix="10.97.6") as t:
        u = t["auto"]

        # Validation: malformed definitions are refused with a reason.
        for bad in (
            {"steps": [{"id": "a", "kind": "emial"}]},                    # typo in kind
            {"steps": [{"id": "a"}, {"id": "a"}]},                         # duplicate id
            {"steps": [{"id": "a", "depends_on": ["missing"]}]},           # unknown dependency
            {"steps": "not a list"},
        ):
            r = await u.req("POST", "/api/automations", json={"name": f"bad {uuid.uuid4().hex[:4]}", "definition": bad})
            assert r.status_code == 422, f"accepted {bad}: {r.status_code}"
        r = await u.req("POST", "/api/automations", json={"name": "", "definition": {"steps": []}})
        assert r.status_code == 422, f"accepted empty name: {r.status_code}"

        # A good workflow runs to completion and its steps are visible.
        d = _ok(await u.req("POST", "/api/automations", json={
            "name": "J6 ok", "definition": {"steps": [
                {"id": "one", "kind": "noop"}, {"id": "two", "kind": "noop", "depends_on": ["one"]}]}}), "create")

        async def run_and_wait(def_id: str) -> dict:
            started = _ok(await u.req("POST", f"/api/automations/{def_id}/run"), "run", (202,))
            run_id = started.get("run_id") or started.get("id")
            t0 = time.monotonic()
            for _ in range(1200):
                got = _ok(await u.req("GET", f"/api/automation-runs/{run_id}"), "status")
                if got["status"] in ("completed", "failed", "cancelled"):
                    print(f"J6 run {got['name']}: {got['status']} after {time.monotonic() - t0:.1f}s")
                    return got
                await asyncio.sleep(0.1)
            raise AssertionError(f"run {run_id} did not finish: {got}")

        ok = await run_and_wait(d["id"])
        assert ok["status"] == "completed", ok

        # An AI step while the provider is down fails visibly, then a retry succeeds.
        bad = _ok(await u.req("POST", "/api/automations", json={
            "name": "J6 ai", "definition": {"steps": [
                {"id": "ask", "kind": "ai", "args": {"prompt": "Write one line about Flow"}}]}}), "ai def")
        ai_sink.down = True
        ai_sink.calls = 0
        try:
            failed = await run_and_wait(bad["id"])
        finally:
            await _provider_back(ai_sink)
        print(f"J6 provider calls for one failed AI step: {ai_sink.calls}")
        assert failed["status"] == "failed", failed
        assert failed.get("error"), "failed run has no error message"
        retried = await run_and_wait(bad["id"])
        assert retried["status"] == "completed", retried


# ── 7. Devices ────────────────────────────────────────────────────────────────

async def test_journey_07_devices(e2e_transport):
    """Enroll test device -> session -> permissions -> disconnect -> clean up."""
    async with tenants(e2e_transport, "dev", "oth", ip_prefix="10.97.7") as t:
        u, o = t["dev"], t["oth"]
        tok = _ok(await u.req("POST", "/api/devices/enroll-token", json={}), "enroll token")
        token = tok.get("token") or tok.get("enrollment_token")
        dev = _ok(await u.client.post("/api/devices/enroll", headers={"X-Forwarded-For": "10.97.7.200"}, json={
            "token": token, "device_name": "J7 test laptop", "platform": "linux",
            "hostname": "j7-synthetic", "agent_version": "0.0.0-test"}), "enroll")
        device_id = dev.get("device_id") or dev.get("id")
        # The enrollment token is single-use.
        r = await u.client.post("/api/devices/enroll", json={"token": token, "device_name": "again", "platform": "linux"})
        assert r.status_code in (400, 401, 404, 409, 410), r.status_code

        sess = _ok(await u.req("POST", "/api/device-sessions/", json={
            "primary_device_id": device_id, "device_ids": [device_id]}), "session")
        sid = sess.get("id") or sess.get("session_id")
        _ok(await u.req("POST", f"/api/device-sessions/{sid}/start"), "start")

        # Permissions: another org can neither see nor drive it.
        for method, url in (("GET", f"/api/devices/{device_id}"), ("GET", f"/api/device-sessions/{sid}"),
                            ("POST", f"/api/device-sessions/{sid}/stop"), ("POST", f"/api/devices/{device_id}/revoke")):
            r = await o.req(method, url)
            assert r.status_code in (403, 404), f"{method} {url}: {r.status_code}"

        # Disconnect: stop the session, revoke the device.
        _ok(await u.req("POST", f"/api/device-sessions/{sid}/stop"), "stop")
        _ok(await u.req("POST", f"/api/devices/{device_id}/revoke"), "revoke")
        r = await u.req("GET", f"/api/devices/{device_id}/session-token?session_id={sid}")
        assert r.status_code in (400, 401, 403, 404, 409, 410), f"revoked device got a token: {r.status_code}"
        s = _ok(await u.req("GET", f"/api/device-sessions/{sid}"), "session after")
        assert s.get("status") in ("stopped", "ended", "closed", "completed"), s


# ── 8. Content ────────────────────────────────────────────────────────────────

async def test_journey_08_content(e2e_transport, monkeypatch):
    """Flow Feed -> browse -> interact -> save -> content library -> open a lesson."""
    async with tenants(e2e_transport, "pub", "rdr", ip_prefix="10.97.8") as t:
        pub, rdr = t["pub"], t["rdr"]
        c = _ok(await pub.req("POST", "/api/creations", json={
            "type": "TEMPLATE", "title": "J8 synthetic template", "description": "test", "tags": ["e2e"]}), "create")
        cid = c["id"]
        # Private until published.
        feed = _ok(await rdr.req("GET", "/api/discover"), "feed")
        items = feed.get("items", feed) if isinstance(feed, dict) else feed
        assert not any(str(i.get("id")) == cid for i in items)
        _ok(await pub.req("POST", f"/api/creations/{cid}/publish"), "publish")
        feed = _ok(await rdr.req("GET", "/api/discover"), "feed 2")
        items = feed.get("items", feed) if isinstance(feed, dict) else feed
        assert any(str(i.get("id")) == cid for i in items), "published item not in feed"

        # Interact and save; repeating does not double count.
        for _ in range(2):
            _ok(await rdr.req("POST", f"/api/creations/{cid}/like"), "like")
            _ok(await rdr.req("POST", f"/api/creations/{cid}/save"), "save")
        got = _ok(await rdr.req("GET", f"/api/creations/{cid}"), "detail")
        assert got.get("like_count", got.get("likes", 0)) in (0, 1), got  # toggle or idempotent, never 2

        # Content library: a synthetic lesson, locked until a (sandbox) purchase.
        slug = f"e2e-lesson-{uuid.uuid4().hex[:6]}"
        pdf = b"%PDF-1.4 synthetic e2e lesson"
        await _db("INSERT INTO study_lessons (slug,title,subject,description,pages,pdf_data,pdf_sha256,cover_data)"
                  " VALUES ($1,'J8 synthetic lesson','computing','test',1,$2,$3,$4)",
                  slug, pdf, hashlib.sha256(pdf + slug.encode()).hexdigest(), b"\x89PNG")
        cat = _ok(await rdr.req("GET", f"/api/study-library/catalog?slug={slug}"), "catalog")
        assert [x["slug"] for x in cat["lessons"]] == [slug]
        monkeypatch.setenv("STUDY_PAYHIP_PRODUCT_KEY", "e2eKEY")
        r = await rdr.req("GET", f"/api/study-library/lessons/{slug}/download")
        assert r.status_code == 403, f"locked lesson opened without purchase: {r.status_code}"
        await _db("INSERT INTO study_purchases (transaction_id,product_key,buyer_email,paid_at)"
                  " VALUES ($1,'e2eKEY',$2,now())", f"sandbox-{uuid.uuid4().hex}", rdr.email)
        r = await rdr.req("GET", f"/api/study-library/lessons/{slug}/download")
        assert r.status_code == 200 and r.content == pdf, r.status_code
        assert r.headers["content-type"] == "application/pdf"
        r = await rdr.req("GET", "/api/study-library/lessons/no-such-lesson/download")
        assert r.status_code == 404
        # A refund takes access away again.
        await _db("UPDATE study_purchases SET refunded_at=now() WHERE buyer_email=$1", rdr.email)
        assert (await rdr.req("GET", f"/api/study-library/lessons/{slug}/download")).status_code == 403


# ── 9. Careers ────────────────────────────────────────────────────────────────

async def test_journey_09_careers(e2e_transport):
    """Profile -> import test alerts -> de-duplicate -> rank -> show results."""
    async with tenants(e2e_transport, "job", ip_prefix="10.97.9") as t:
        u = t["job"]
        _ok(await u.req("PUT", "/api/careers/profile", json={
            "summary": "Synthetic data analyst", "roles": ["Data Analyst"], "skills": ["SQL", "Python", "Power BI"],
            "cities": ["Dubai"], "languages": ["English", "Arabic"], "experience_years": 4}), "profile")
        alert = (
            "Data Analyst - Synthetic Co - Dubai\nhttps://www.linkedin.com/jobs/view/1000000001\n"
            "SQL, Python, Power BI required.\n\n"
            "Pastry Chef - Synthetic Bakery - Abu Dhabi\nhttps://www.linkedin.com/jobs/view/1000000002\n"
            "Bakery experience.\n"
        )
        first = _ok(await u.req("POST", "/api/careers/import", json={"text": alert, "source": "linkedin", "use_ai": False}),
                    "import")
        again = _ok(await u.req("POST", "/api/careers/import", json={"text": alert, "source": "linkedin", "use_ai": False}),
                    "import again")
        jobs = _ok(await u.req("GET", "/api/careers/jobs"), "jobs")
        jobs = jobs["items"]
        urls = [j.get("url") or j.get("source_url") for j in jobs]
        assert len(urls) == len(set(urls)), f"duplicates after re-import: {urls}"
        assert len(jobs) >= 1, (first, again)
        # Ranked: the matching role comes before the unrelated one.
        titles = [j.get("title", "") for j in jobs]
        if len(titles) >= 2 and any("Analyst" in x for x in titles) and any("Chef" in x for x in titles):
            assert titles.index(next(x for x in titles if "Analyst" in x)) < titles.index(next(x for x in titles if "Chef" in x)), titles
        _ok(await u.req("PATCH", f"/api/careers/jobs/{jobs[0]['id']}/status", json={"status": "saved"}), "save job")


# ── 10. Billing (sandbox only) ────────────────────────────────────────────────

async def test_journey_10_billing(e2e_transport, monkeypatch):
    """Plans -> choose a test plan -> entitlements -> subscription status. No payment."""
    async with tenants(e2e_transport, "bill", ip_prefix="10.97.10") as t:
        u = t["bill"]
        plans = _ok(await u.req("GET", "/api/plans"), "plans")
        plans = plans.get("plans", plans) if isinstance(plans, dict) else plans
        ids = {p["id"] for p in plans}
        assert {"free", "starter", "pro"} <= ids, ids

        billing = _ok(await u.req("GET", f"/api/orgs/{u.org_id}/billing"), "billing")
        assert "free" in json.dumps(billing).lower()

        # Checkout with no payment provider configured refuses cleanly; nothing is charged.
        r = await u.req("POST", f"/api/orgs/{u.org_id}/billing/checkout", json={"plan": "starter"})
        assert r.status_code in (400, 402, 501, 503), f"checkout without Stripe: {r.status_code} {r.text[:200]}"
        r = await u.req("POST", f"/api/orgs/{u.org_id}/billing/checkout", json={"plan": "no-such-plan"})
        assert r.status_code in (400, 404, 422, 503)

        # Entitlements follow the plan. The plan changes the way it does in
        # production, through Stripe's subscription webhook, signed here with a
        # local test secret: no Stripe account, no network, no payment.
        usage = _ok(await u.req("GET", f"/api/orgs/{u.org_id}/usage"), "usage free")
        import app.core.config as cfg
        monkeypatch.setattr(cfg, "STRIPE_WEBHOOK_SECRET", "whsec_e2e_sandbox")

        async def webhook(event_type: str, status: str) -> httpx.Response:
            body = json.dumps({"id": f"evt_e2e_{uuid.uuid4().hex}", "object": "event", "type": event_type,
                               "data": {"object": {"id": "sub_e2e_sandbox", "object": "subscription",
                                                   "customer": "cus_e2e_sandbox", "status": status,
                                                   "current_period_end": int(time.time()) + 30 * 86400,
                                                   "metadata": {"organization_id": u.org_id, "plan_id": "starter"}}}})
            ts = int(time.time())
            sig = hmac.new(b"whsec_e2e_sandbox", f"{ts}.{body}".encode(), hashlib.sha256).hexdigest()
            return await u.client.post("/api/stripe/webhook", content=body,
                                       headers={"stripe-signature": f"t={ts},v1={sig}", "content-type": "application/json"})

        forged = await u.client.post("/api/stripe/webhook", content=b"{}", headers={"stripe-signature": "t=1,v1=00"})
        assert forged.status_code == 400, f"unsigned webhook accepted: {forged.status_code}"
        _ok(await webhook("customer.subscription.created", "active"), "webhook created")
        billing = _ok(await u.req("GET", f"/api/orgs/{u.org_id}/billing"), "billing 2")
        assert billing["plan"] == "starter" and billing["has_access"], billing
        usage2 = _ok(await u.req("GET", f"/api/orgs/{u.org_id}/usage"), "usage starter")
        assert json.dumps(usage) != json.dumps(usage2), "limits did not change with the plan"

        # Cancellation drops the org back to Free.
        _ok(await webhook("customer.subscription.deleted", "canceled"), "webhook deleted")
        billing = _ok(await u.req("GET", f"/api/orgs/{u.org_id}/billing"), "billing 3")
        assert not billing["has_access"], billing
        assert (await _db("SELECT plan FROM organizations WHERE id=$1", uuid.UUID(u.org_id)))[0]["plan"] == "free"

        # Nothing was charged.
        assert (await _db("SELECT count(*) AS n FROM payments WHERE organization_id=$1", uuid.UUID(u.org_id)))[0]["n"] == 0


# ── 12. Recovery ──────────────────────────────────────────────────────────────

async def test_journey_12_recovery(e2e_transport, ai_sink):
    """A non-essential service fails, then returns: no data lost, nothing duplicated."""
    async with tenants(e2e_transport, "rec", ip_prefix="10.97.12") as t:
        u = t["rec"]
        pid = _ok(await u.req("POST", "/api/projects", json={"name": "J12"}), "project")["id"]
        r = await u.req("POST", "/api/run/stream", json={"project_id": pid, "prompt": "first message"})
        conv = next(e["conv_id"] for e in _sse(r.text) if e.get("type") == "conv_id")

        # AI provider down: the user gets an error event, the platform keeps working.
        ai_sink.down = True
        try:
            r = await u.req("POST", "/api/run/stream",
                            json={"project_id": pid, "prompt": "during outage", "conversation_id": conv})
            assert r.status_code == 200
            assert any(e.get("type") == "error" for e in _sse(r.text)), "outage not reported to the user"
            # Non-AI features are unaffected.
            _ok(await u.req("POST", "/api/leads", json={"name": "Lead during outage"}), "lead during outage")
            assert (await u.client.get("/health")).status_code == 200
        finally:
            await _provider_back(ai_sink)

        # Service back: the conversation continues; nothing lost, no half-written reply.
        r = await u.req("POST", "/api/run/stream",
                        json={"project_id": pid, "prompt": "after outage", "conversation_id": conv})
        assert not [e for e in _sse(r.text) if e.get("type") == "error"]
        msgs = _ok(await u.req("GET", f"/api/conversations/{conv}/messages"), "messages")
        msgs = msgs.get("messages", msgs) if isinstance(msgs, dict) else msgs
        texts = [(m["role"], m["content"]) for m in msgs]
        assert ("user", "first message") in texts and ("user", "after outage") in texts
        assert sum(1 for role, _ in texts if role == "assistant" ) == 2, texts
        assert not any(role == "assistant" and not c for role, c in texts), "empty assistant reply stored"
        leads = _ok(await u.req("GET", "/api/leads"), "leads")
        leads = leads.get("leads", leads.get("items", [])) if isinstance(leads, dict) else leads
        assert sum(1 for x in leads if x["name"] == "Lead during outage") == 1
