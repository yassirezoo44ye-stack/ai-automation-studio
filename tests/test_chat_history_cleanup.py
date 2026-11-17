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
