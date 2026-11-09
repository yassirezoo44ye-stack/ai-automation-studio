"""
Phase A acceptance tests — chat persistence, drafts/retry, limits, isolation.

Runs against a REAL PostgreSQL database (schema built by app.core.db.init_db)
so ownership checks, the unique retry index and ON CONFLICT paths are
exercised for real rather than mocked. Only the AI provider is faked.

Skipped unless TEST_DATABASE_URL points at a disposable database, e.g.:

    TEST_DATABASE_URL=postgresql://postgres@localhost:5432/flow_test pytest tests/test_chat_persistence_phase_a.py

Tables live in their own schema (chat_phase_a_test) and are truncated per
test. Never point it at production.
"""
from __future__ import annotations

import json
import os
import uuid
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

TEST_DB = os.environ.get("TEST_DATABASE_URL")
SCHEMA = "chat_phase_a_test"
pytestmark = pytest.mark.skipif(not TEST_DB, reason="TEST_DATABASE_URL not set")

if TEST_DB:
    import asyncpg
    import httpx
    from fastapi import FastAPI, HTTPException, Request

    from app.core import db as db_mod
    from app.routers import chat as chat_mod


# ── Fake AI provider ────────────────────────────────────────────────────────

class FakeEngine:
    """Scripted stand-in for InferenceEngine.stream. ``script`` is a list of
    chunks; ``calls`` records every request so tests can assert history and
    that a replay never reached the model."""
    script: list[dict] = []
    calls: list = []

    def __init__(self, *a, **k):
        pass

    async def stream(self, request_obj, **_):
        FakeEngine.calls.append(request_obj)
        for chunk in FakeEngine.script:
            yield chunk


def reply(text: str) -> list[dict]:
    return [{"type": "delta", "text": t} for t in text.split(" ") if t] + [
        {"type": "usage", "usage": {"total_tokens": 10}}
    ]


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
async def env():
    # Own schema: TRUNCATE ... CASCADE below can never touch tables that other
    # test modules keep in the same database (CI shares one Postgres).
    boot = await asyncpg.connect(TEST_DB)
    await boot.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
    await boot.close()
    pool = await asyncpg.create_pool(TEST_DB, min_size=1, max_size=4,
                                     server_settings={"search_path": f"{SCHEMA},public"})
    async with pool.acquire() as conn:
        await db_mod.init_db(conn)
        await conn.execute("TRUNCATE messages, conversations, usage_logs, agent_runs, projects, users CASCADE")
        users = {}
        for name in ("alice", "bob"):
            users[name] = await conn.fetchval(
                "INSERT INTO users (email) VALUES ($1) RETURNING id", f"{name}@test.local")

    async def fake_owner(conn, request: Request):
        uid = users.get(request.headers.get("x-test-user", ""))
        if not uid:
            raise HTTPException(401, "no user")
        return uid

    app = FastAPI()
    app.include_router(chat_mod.router)
    FakeEngine.script, FakeEngine.calls = reply("hello there"), []

    with ExitStack() as st:
        st.enter_context(patch.object(chat_mod, "get_pool", return_value=pool))
        st.enter_context(patch.object(chat_mod, "owner_user_id", fake_owner))
        st.enter_context(patch.object(chat_mod, "ai_rate_limit", MagicMock()))
        st.enter_context(patch.object(chat_mod, "check_org_quota", AsyncMock(return_value=None)))
        st.enter_context(patch.object(chat_mod, "record_org_tokens", AsyncMock()))
        st.enter_context(patch.object(chat_mod, "InferenceEngine", FakeEngine))
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            yield client, pool, users
    await pool.close()


def H(user: str) -> dict:
    return {"x-test-user": user}


async def send(client, user, prompt, *, conv=None, req_id=None, project="demo"):
    body = {"project_id": project, "prompt": prompt, "conversation_id": conv,
            "client_request_id": req_id}
    r = await client.post("/api/run/stream", json=body, headers=H(user))
    if r.status_code != 200:
        return r.status_code, r.json(), []
    events = [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: ")]
    return 200, None, events


async def count(pool, sql, *args):
    async with pool.acquire() as c:
        return await c.fetchval(sql, *args)


# ── 1. Send, reload, restore ────────────────────────────────────────────────

async def test_send_then_reload_restores_conversation(env):
    client, pool, _ = env
    rid = str(uuid.uuid4())
    code, _, ev = await send(client, "alice", "Plan my week", req_id=rid)
    assert code == 200
    ack = ev[0]
    assert ack["type"] == "conv_id" and ack["user_saved"] is True
    assert ack["client_request_id"] == rid and ack["retry"] is False
    assert ev[-1]["type"] == "done"
    conv = ack["conv_id"]

    # "Reload": a fresh client session only knows the stored conv id.
    meta = (await client.get(f"/api/conversations/{conv}", headers=H("alice"))).json()
    assert meta["id"] == conv and meta["archived"] is False
    listed = (await client.get("/api/conversations?project_id=demo", headers=H("alice"))).json()
    assert [c["id"] for c in listed] == [conv]
    msgs = (await client.get(f"/api/conversations/{conv}/messages", headers=H("alice"))).json()
    assert [(m["role"], m["content"], m["status"]) for m in msgs] == [
        ("user", "Plan my week", "complete"),
        ("assistant", "hellothere", "complete"),
    ]
    assert msgs[0]["client_request_id"] == rid


# ── 2/3. Retry is idempotent ────────────────────────────────────────────────

async def test_retry_after_success_replays_without_duplicates_or_model_call(env):
    client, pool, _ = env
    rid = str(uuid.uuid4())
    _, _, ev1 = await send(client, "alice", "Hi", req_id=rid)
    conv = ev1[0]["conv_id"]
    calls_before = len(FakeEngine.calls)

    _, _, ev2 = await send(client, "alice", "Hi", req_id=rid)
    assert ev2[0]["conv_id"] == conv and ev2[0]["retry"] is True
    assert ev2[-1] == {"type": "done", "replayed": True}
    assert "".join(e.get("text", "") for e in ev2 if e["type"] == "delta") == "hellothere"
    assert len(FakeEngine.calls) == calls_before, "replay must not call the model again"
    assert await count(pool, "SELECT count(*) FROM messages WHERE conversation_id=$1", uuid.UUID(conv)) == 2
    assert await count(pool, "SELECT count(*) FROM conversations") == 1


async def test_failed_reply_keeps_user_message_and_retry_regenerates_once(env):
    client, pool, _ = env
    rid = str(uuid.uuid4())
    FakeEngine.script = [{"type": "delta", "text": "partial "}, {"type": "error", "error": "provider down"}]
    _, _, ev = await send(client, "alice", "Write the report", req_id=rid)
    conv = ev[0]["conv_id"]
    err = ev[-1]
    assert err["type"] == "error" and err["retryable"] is True and err["partial"] is True

    msgs = (await client.get(f"/api/conversations/{conv}/messages", headers=H("alice"))).json()
    assert [(m["role"], m["status"]) for m in msgs] == [("user", "complete"), ("assistant", "partial")]
    assert msgs[1]["content"] == "partial "

    FakeEngine.script = reply("full answer")
    _, _, ev2 = await send(client, "alice", "Write the report", req_id=rid, conv=conv)
    assert ev2[0]["retry"] is True and ev2[-1]["type"] == "done"
    msgs = (await client.get(f"/api/conversations/{conv}/messages", headers=H("alice"))).json()
    assert [(m["role"], m["content"], m["status"]) for m in msgs] == [
        ("user", "Write the report", "complete"),
        ("assistant", "fullanswer", "complete"),
    ]
    # The regenerated call saw no duplicate user turn.
    last = FakeEngine.calls[-1].messages
    assert [m.role for m in last] == ["user"]


async def test_reply_with_no_text_is_marked_failed_and_excluded_from_history(env):
    client, _, _ = env
    FakeEngine.script = [{"type": "error", "error": "bad key"}]
    _, _, ev = await send(client, "alice", "First", req_id=str(uuid.uuid4()))
    conv = ev[0]["conv_id"]
    assert ev[-1]["partial"] is False
    msgs = (await client.get(f"/api/conversations/{conv}/messages", headers=H("alice"))).json()
    assert msgs[-1]["status"] == "failed"

    FakeEngine.script = reply("ok")
    await send(client, "alice", "Second", conv=conv, req_id=str(uuid.uuid4()))
    roles = [m.role for m in FakeEngine.calls[-1].messages]
    assert roles == ["user", "user"], "empty failed reply must not be sent to the model"


async def test_client_disconnect_mid_stream_saves_partial_reply(env):
    _, pool, users = env
    FakeEngine.script = [{"type": "delta", "text": "first chunk"}, {"type": "delta", "text": " second"}]
    req = chat_mod.RunRequest(project_id="demo", prompt="Long task",
                              client_request_id=str(uuid.uuid4()))
    request = MagicMock()
    request.headers = {"x-test-user": "alice"}
    resp = await chat_mod.run_stream(req, request)
    it = resp.body_iterator
    ack = json.loads((await it.__anext__())[6:])
    first = json.loads((await it.__anext__())[6:])
    assert first == {"type": "delta", "text": "first chunk"}
    await it.aclose()  # what Starlette does when the client goes away

    async with pool.acquire() as c:
        row = await c.fetchrow(
            "SELECT content, status FROM messages WHERE conversation_id=$1 AND role='assistant'",
            uuid.UUID(ack["conv_id"]))
    assert row["status"] == "partial" and row["content"] == "first chunk"


# ── 5/6. Long prompts and limits ────────────────────────────────────────────

async def test_long_arabic_prompt_with_code_round_trips_exactly(env):
    client, _, _ = env
    prompt = (
        "أريد منك مراجعة هذا المرجع ثم تعديل الشفرة.\n\n"
        "المرجع:\n> " + ("نص مرجعي طويل. " * 400) + "\n\n"
        "```python\ndef f(x):\n    return {\"k\": x}  # تعليق\n```\n"
        "القيود: لا تغيّر التوقيع.\n"
    )
    assert len(prompt) > 4000, "must exceed the old 4000-char cap"
    code, _, ev = await send(client, "alice", prompt, req_id=str(uuid.uuid4()))
    assert code == 200
    msgs = (await client.get(f"/api/conversations/{ev[0]['conv_id']}/messages", headers=H("alice"))).json()
    assert msgs[0]["content"] == prompt
    assert FakeEngine.calls[-1].messages[-1].content == prompt


async def test_oversized_prompt_rejected_with_explanation_and_nothing_stored(env):
    client, pool, _ = env
    limit = (await client.get("/api/chat/limits")).json()["max_prompt_chars"]
    code, body, _ = await send(client, "alice", "ب" * (limit + 1), req_id=str(uuid.uuid4()))
    assert code == 413
    d = body["detail"]
    assert d["code"] == "prompt_too_long" and d["limit"] == limit and d["length"] == limit + 1
    assert d["message_ar"] and d["message"]
    assert await count(pool, "SELECT count(*) FROM messages") == 0
    assert await count(pool, "SELECT count(*) FROM conversations") == 0
    assert FakeEngine.calls == []


async def test_prompt_at_exact_limit_is_accepted(env):
    client, _, _ = env
    limit = (await client.get("/api/chat/limits")).json()["max_prompt_chars"]
    code, _, _ = await send(client, "alice", "a" * limit, req_id=str(uuid.uuid4()))
    assert code == 200


async def test_blank_prompt_rejected(env):
    client, _, _ = env
    code, body, _ = await send(client, "alice", "   \n ", req_id=str(uuid.uuid4()))
    assert code == 422 and body["detail"]["code"] == "prompt_empty"


# ── 7. Isolation ────────────────────────────────────────────────────────────

async def test_user_cannot_read_or_modify_another_users_conversation(env):
    client, pool, _ = env
    rid = str(uuid.uuid4())
    _, _, ev = await send(client, "alice", "secret plan", req_id=rid)
    conv = ev[0]["conv_id"]

    for method, path, kw in [
        ("GET", f"/api/conversations/{conv}", {}),
        ("GET", f"/api/conversations/{conv}/messages", {}),
        ("GET", f"/api/export/conversations/{conv}", {}),
        ("PATCH", f"/api/conversations/{conv}", {"json": {"title": "pwned"}}),
        ("DELETE", f"/api/conversations/{conv}", {}),
    ]:
        r = await client.request(method, path, headers=H("bob"), **kw)
        assert r.status_code == 404, (method, path, r.status_code)

    code, _, _ = await send(client, "bob", "inject", conv=conv, req_id=str(uuid.uuid4()))
    assert code == 404
    # Reusing Alice's request id must neither replay her reply nor reveal it.
    code, body, _ = await send(client, "bob", "x", req_id=rid)
    assert code == 409 and "secret" not in json.dumps(body)

    assert (await client.get("/api/conversations", headers=H("bob"))).json() == []
    assert (await client.get("/api/conversations?q=secret", headers=H("bob"))).json() == []
    assert (await client.get("/api/search?q=secret", headers=H("bob"))).json()["messages"] == []
    meta = (await client.get(f"/api/conversations/{conv}", headers=H("alice"))).json()
    assert meta["title"] != "pwned"
    assert await count(pool, "SELECT count(*) FROM messages WHERE conversation_id=$1", uuid.UUID(conv)) == 2


async def test_malformed_conversation_id_is_404_not_500(env):
    client, _, _ = env
    for path in ("/api/conversations/not-a-uuid", "/api/conversations/not-a-uuid/messages",
                 "/api/export/conversations/not-a-uuid"):
        assert (await client.get(path, headers=H("alice"))).status_code == 404
    assert (await client.delete("/api/conversations/nope", headers=H("alice"))).status_code == 404


# ── List management: rename, archive, search ────────────────────────────────

async def test_rename_archive_search_unarchive(env):
    client, _, _ = env
    _, _, a = await send(client, "alice", "budget for Q3", req_id=str(uuid.uuid4()))
    _, _, b = await send(client, "alice", "landing page copy", req_id=str(uuid.uuid4()))
    ca, cb = a[0]["conv_id"], b[0]["conv_id"]

    r = await client.patch(f"/api/conversations/{ca}", json={"title": "  ميزانية   الربع الثالث "},
                           headers=H("alice"))
    assert r.status_code == 200 and r.json()["title"] == "ميزانية الربع الثالث"
    assert (await client.patch(f"/api/conversations/{ca}", json={"title": ""},
                               headers=H("alice"))).status_code == 422

    found = (await client.get("/api/conversations?q=ميزانية", headers=H("alice"))).json()
    assert [c["id"] for c in found] == [ca]
    found = (await client.get("/api/conversations?q=landing", headers=H("alice"))).json()
    assert [c["id"] for c in found] == [cb], "search must match message content too"

    r = await client.patch(f"/api/conversations/{cb}", json={"archived": True}, headers=H("alice"))
    assert r.json()["archived"] is True
    active = [c["id"] for c in (await client.get("/api/conversations", headers=H("alice"))).json()]
    archived = [c["id"] for c in (await client.get("/api/conversations?archived=true", headers=H("alice"))).json()]
    assert active == [ca] and archived == [cb]

    await client.patch(f"/api/conversations/{cb}", json={"archived": False}, headers=H("alice"))
    active = {c["id"] for c in (await client.get("/api/conversations", headers=H("alice"))).json()}
    assert active == {ca, cb}

    md = (await client.get(f"/api/export/conversations/{ca}", headers=H("alice"))).text
    assert "budget for Q3" in md and "ميزانية الربع الثالث" in md
