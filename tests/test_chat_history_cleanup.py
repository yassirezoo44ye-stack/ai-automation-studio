"""
"My AI Assistant" history fixes.

1. Conversations saved before the display_text fix kept the hidden
   "[Context: the user is currently on …]" preamble in their title and first
   user message; reads must show what the user actually typed.
2. A provider stream that finishes with no text must surface an error, not
   save an empty assistant reply.
"""
from __future__ import annotations

import json

import pytest
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.routers import chat as chat_mod  # noqa: E402

CTX = ('[Context: the user is currently on the "Design Studio" page of the "Acme [beta]" '
       'organization inside Axon AI Automation Studio. Answer helpfully and concisely; you may '
       'suggest which page to visit but cannot take actions yourself.]')


class TestStripContext(unittest.TestCase):
    def test_strips_preamble_even_with_bracket_in_org_name(self):
        self.assertEqual(chat_mod.strip_context_prefix(f"{CTX}\n\nصمم شعارًا"), "صمم شعارًا")

    def test_leaves_normal_text_alone(self):
        for text in ("hello", "[x] keep this", "", "Context: no bracket"):
            self.assertEqual(chat_mod.strip_context_prefix(text), text)

    def test_make_title(self):
        self.assertEqual(chat_mod.make_title(f"{CTX}\n\nhello"), "hello")
        self.assertEqual(chat_mod.make_title("x" * 70), "x" * 60 + "…")
        self.assertEqual(chat_mod.make_title("   "), "New conversation")
        # A truncated preamble with no user text never becomes a title.
        self.assertEqual(chat_mod.make_title(CTX[:60]), "New conversation")


def _pool(conn):
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=conn)
    cm.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire.return_value = cm
    return pool


class TestListAndMessages(unittest.IsolatedAsyncioTestCase):
    async def test_list_rebuilds_leaked_titles_from_first_message(self):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        bad, good = uuid.uuid4(), uuid.uuid4()
        conn = MagicMock()
        conn.fetch = AsyncMock(side_effect=[
            [{"id": bad, "title": CTX[:60] + "…", "created_at": now, "updated_at": now},
             {"id": good, "title": "اكتب كود Python", "created_at": now, "updated_at": now}],
            [{"conversation_id": bad, "content": f"{CTX}\n\nDesign a logo for my bakery"}],
        ])
        with patch.object(chat_mod, "get_pool", return_value=_pool(conn)), \
             patch.object(chat_mod, "owner_user_id", AsyncMock(return_value=uuid.uuid4())), \
             patch.object(chat_mod, "resolve_project_id", AsyncMock(return_value=uuid.uuid4())):
            out = await chat_mod.list_conversations(MagicMock(), project_id="demo")
        self.assertEqual([c["title"] for c in out], ["Design a logo for my bakery", "اكتب كود Python"])
        # Only the leaked conversation is looked up.
        self.assertEqual(conn.fetch.await_args_list[1].args[1], [bad])

    async def test_messages_hide_preamble_on_user_rows_only(self):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        conn = MagicMock()
        conn.fetchval = AsyncMock(return_value=1)
        conn.fetch = AsyncMock(return_value=[
            {"id": uuid.uuid4(), "role": "user", "content": f"{CTX}\n\nhi", "created_at": now},
            {"id": uuid.uuid4(), "role": "assistant", "content": "[Context: quoted] ok", "created_at": now},
        ])
        with patch.object(chat_mod, "get_pool", return_value=_pool(conn)), \
             patch.object(chat_mod, "owner_user_id", AsyncMock(return_value=uuid.uuid4())):
            out = await chat_mod.get_messages(str(uuid.uuid4()), MagicMock())
        self.assertEqual([m["content"] for m in out], ["hi", "[Context: quoted] ok"])


async def _aiter(items):
    for item in items:
        yield item


class TestEmptyReply(unittest.IsolatedAsyncioTestCase):
    async def test_empty_stream_reports_error_and_saves_nothing(self):
        conn = MagicMock()
        conn.fetchval = AsyncMock(return_value=uuid.uuid4())
        conn.fetch = AsyncMock(return_value=[])
        conn.execute = AsyncMock(return_value="OK")
        req = chat_mod.RunRequest(project_id="demo", prompt="hello")
        with patch.object(chat_mod, "ai_rate_limit", MagicMock()), \
             patch.object(chat_mod, "check_org_quota", AsyncMock(return_value="org")), \
             patch.object(chat_mod, "get_pool", return_value=_pool(conn)), \
             patch.object(chat_mod, "owner_user_id", AsyncMock(return_value=uuid.uuid4())), \
             patch.object(chat_mod, "resolve_project_id", AsyncMock(return_value=uuid.uuid4())), \
             patch("app.core.ai.inference.engine.InferenceEngine.stream",
                   return_value=_aiter([{"type": "usage", "usage": {"total_tokens": 3}}])):
            resp = await chat_mod.run_stream(req, MagicMock())
            events = [json.loads(chunk.removeprefix("data: ").strip())
                      async for chunk in resp.body_iterator]
        self.assertEqual([e["type"] for e in events], ["conv_id", "error"])
        self.assertIn("empty reply", events[-1]["message"])
        saved = [c.args for c in conn.execute.await_args_list if "'assistant'" in c.args[0]]
        self.assertEqual(saved, [])


if __name__ == "__main__":
    unittest.main()


class TestNavigationPrompt(unittest.IsolatedAsyncioTestCase):
    """M2: the page catalog reaches the model only when the client asks for it."""

    async def _system_for(self, **req_kwargs):
        conn = MagicMock()
        conn.fetchval = AsyncMock(return_value=uuid.uuid4())
        conn.fetch = AsyncMock(return_value=[])
        conn.execute = AsyncMock(return_value="OK")
        seen = {}

        def fake_stream(self_engine, request, **_kw):
            seen["system"] = request.system
            return _aiter([{"type": "delta", "text": "ok"}])

        req = chat_mod.RunRequest(project_id="demo", prompt="open settings", **req_kwargs)
        with patch.object(chat_mod, "ai_rate_limit", MagicMock()), \
             patch.object(chat_mod, "check_org_quota", AsyncMock(return_value="org")), \
             patch.object(chat_mod, "get_pool", return_value=_pool(conn)), \
             patch.object(chat_mod, "owner_user_id", AsyncMock(return_value=uuid.uuid4())), \
             patch.object(chat_mod, "resolve_project_id", AsyncMock(return_value=uuid.uuid4())), \
             patch.object(chat_mod, "record_org_tokens", AsyncMock()), \
             patch("app.core.ai.inference.engine.InferenceEngine.stream", fake_stream):
            resp = await chat_mod.run_stream(req, MagicMock())
            [_ async for _ in resp.body_iterator]
        return seen["system"]

    async def test_catalog_added_when_requested(self):
        system = await self._system_for(navigation=True)
        self.assertIn("[[open:settings]]", system)
        self.assertIn("cannot open pages", system)
        from app.core.ai.navigation import PAGES
        for pid in ("leads", "billing", "app-builder"):
            self.assertIn(f"- {pid}:", system)
        self.assertIn("leads", PAGES)

    async def test_workspace_snapshot_only_when_requested(self):
        snap = AsyncMock(return_value="<workspace-data>\nTasks: pending 2\n</workspace-data>")
        with patch("app.core.ai.workspace_snapshot.build_snapshot", snap), \
             patch.object(chat_mod, "owner_email", MagicMock(return_value="a@x.io")):
            on = await self._system_for(workspace_data=True)
            off = await self._system_for()
        self.assertIn("Tasks: pending 2", on)
        self.assertFalse(off and "workspace-data" in off)
        self.assertEqual(snap.await_count, 1)

    async def test_no_catalog_by_default(self):
        system = await self._system_for()
        self.assertFalse(system and "[[open:" in system)


def test_page_catalog_matches_web_client():
    """Every page the model may suggest must be one the client can open."""
    import re as _re
    from app.core.ai.navigation import PAGES
    ts = (Path(__file__).parent.parent / "src/renderer/shared/utils/assistantNav.ts").read_text()
    block = ts.split("export const ASSISTANT_PAGES", 1)[1].split("};", 1)[0]
    client = set(_re.findall(r'^\s*"?([a-z-]+)"?\s*:\s*\{ page:', block, _re.M))
    assert set(PAGES) == client


def test_action_catalogue_is_allow_list_only():
    from app.core.ai.navigation import ACTIONS, navigation_system_prompt
    assert set(ACTIONS) == {"create_task", "create_lead"}
    prompt = navigation_system_prompt()
    assert "[[action:create_task" in prompt
    assert "Never say an action is done" in prompt
    assert "Deleting, paying, sending messages" in prompt


def test_task_source_is_restricted():
    import pydantic
    from app.routers.tasks import TaskCreate
    assert TaskCreate(title="x").source == "manual"
    assert TaskCreate(title="x", source="assistant").source == "assistant"
    with pytest.raises(pydantic.ValidationError):
        TaskCreate(title="x", source="admin")
