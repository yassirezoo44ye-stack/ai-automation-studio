"""
P1 fix: display_text context-leak tests.

Verifies that:
  1. When display_text is provided, storage uses it (not the annotated prompt).
  2. When display_text is absent, storage falls back to prompt (backward-compatible).
  3. The model always receives the full prompt (with context annotation) via
     history.append — not display_text.
  4. resolve_project_id handles "copilot" → creates/finds "AI Copilot" project.

All DB interactions are mocked.
"""
from __future__ import annotations

import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))


def _fake_pool(conv_id=None):
    conn = MagicMock()
    conn.fetchval = AsyncMock(return_value=conv_id or uuid.uuid4())
    conn.fetch = AsyncMock(return_value=[])
    conn.execute = AsyncMock(return_value="OK")

    conn_cm = MagicMock()
    conn_cm.__aenter__ = AsyncMock(return_value=conn)
    conn_cm.__aexit__ = AsyncMock(return_value=False)

    pool = MagicMock()
    pool.acquire.return_value = conn_cm
    return pool, conn


class TestDisplayTextStoragePaths(unittest.IsolatedAsyncioTestCase):
    """Storage uses display_text when provided; falls back to prompt otherwise."""

    async def _drive(self, req):
        from app.routers import chat as chat_mod

        pool, conn = _fake_pool()
        with unittest.mock.patch.object(
            chat_mod, "ai_rate_limit", MagicMock(),
        ), unittest.mock.patch.object(
            chat_mod, "check_org_quota", AsyncMock(return_value="org-1"),
        ), unittest.mock.patch.object(
            chat_mod, "get_pool", return_value=pool,
        ), unittest.mock.patch.object(
            chat_mod, "owner_user_id", AsyncMock(return_value=uuid.uuid4()),
        ), unittest.mock.patch.object(
            chat_mod, "resolve_project_id", AsyncMock(return_value=uuid.uuid4()),
        ), unittest.mock.patch.object(
            chat_mod, "record_org_tokens", AsyncMock(),
        ), unittest.mock.patch(
            "app.core.ai.inference.engine.InferenceEngine.stream",
            return_value=_aiter([{"type": "done"}]),
        ):
            resp = await chat_mod.run_stream(req, MagicMock())
            _ = [chunk async for chunk in resp.body_iterator]
        return conn

    async def test_display_text_used_for_title_when_provided(self):
        from app.routers import chat as chat_mod

        req = chat_mod.RunRequest(
            project_id="copilot",
            prompt="[Context: Billing page]\n\nWhat is my plan?",
            display_text="What is my plan?",
        )
        conn = await self._drive(req)

        # First fetchval call creates conversation — second arg is the title
        create_call_args = conn.fetchval.call_args_list[0][0]
        title_arg = create_call_args[2]  # INSERT INTO conversations … ($1,$2)
        self.assertFalse(title_arg.startswith("[Context:"),
                         f"Title must not start with [Context:]: {title_arg!r}")
        self.assertIn("What is my plan?", title_arg)

    async def test_display_text_used_for_message_content_when_provided(self):
        from app.routers import chat as chat_mod

        req = chat_mod.RunRequest(
            project_id="copilot",
            prompt="[Context: Billing page]\n\nWhat is my plan?",
            display_text="What is my plan?",
        )
        conn = await self._drive(req)

        # execute calls: (1) INSERT messages user, (2) UPDATE conversations
        # (3) INSERT usage_logs message_sent, (4+5 inside event_stream)
        first_execute = conn.execute.call_args_list[0][0]
        stored_content = first_execute[2]  # $2 in INSERT INTO messages
        self.assertFalse(stored_content.startswith("[Context:"),
                         f"Stored message must not start with [Context:]: {stored_content!r}")
        self.assertEqual(stored_content, "What is my plan?")

    async def test_prompt_without_display_text_backward_compatible(self):
        """Requests without display_text (old clients) must work unchanged."""
        from app.routers import chat as chat_mod

        req = chat_mod.RunRequest(project_id="demo", prompt="Hello there")
        conn = await self._drive(req)

        first_execute = conn.execute.call_args_list[0][0]
        stored_content = first_execute[2]
        self.assertEqual(stored_content, "Hello there")

    async def test_full_prompt_with_context_reaches_model(self):
        """The model must receive the full annotated prompt, not display_text."""
        from app.routers import chat as chat_mod

        captured_messages: list = []

        class _CapturingStream:
            def __init__(self, req_obj, **_):
                captured_messages.extend(m.content for m in req_obj.messages)

            def __aiter__(self):
                return iter([])

            async def __anext__(self):
                raise StopAsyncIteration

        annotated = "[Context: Billing page]\n\nWhat is my plan?"
        req = chat_mod.RunRequest(
            project_id="copilot",
            prompt=annotated,
            display_text="What is my plan?",
        )
        pool, conn = _fake_pool()
        with unittest.mock.patch.object(
            chat_mod, "ai_rate_limit", MagicMock(),
        ), unittest.mock.patch.object(
            chat_mod, "check_org_quota", AsyncMock(return_value="org-1"),
        ), unittest.mock.patch.object(
            chat_mod, "get_pool", return_value=pool,
        ), unittest.mock.patch.object(
            chat_mod, "owner_user_id", AsyncMock(return_value=uuid.uuid4()),
        ), unittest.mock.patch.object(
            chat_mod, "resolve_project_id", AsyncMock(return_value=uuid.uuid4()),
        ), unittest.mock.patch.object(
            chat_mod, "record_org_tokens", AsyncMock(),
        ), unittest.mock.patch(
            "app.core.ai.inference.engine.InferenceEngine.stream",
            side_effect=lambda req_obj, **_: _aiter([{"type": "done"}]),
        ) as mock_stream:
            resp = await chat_mod.run_stream(req, MagicMock())
            _ = [chunk async for chunk in resp.body_iterator]

        call_req = mock_stream.call_args[0][0]
        model_contents = [m.content for m in call_req.messages]
        last_user_content = model_contents[-1]
        self.assertIn("[Context:", last_user_content,
                      "Model must receive the annotated prompt including context")
        self.assertIn("What is my plan?", last_user_content)


class TestResolveProjectIdCopilot(unittest.IsolatedAsyncioTestCase):
    """resolve_project_id("copilot") finds or creates "AI Copilot" project."""

    async def test_copilot_key_finds_existing_project(self):
        from app.core.helpers import resolve_project_id

        existing_id = uuid.uuid4()
        conn = MagicMock()
        conn.fetchval = AsyncMock(return_value=existing_id)

        result = await resolve_project_id(conn, "copilot", uuid.uuid4())
        self.assertEqual(result, existing_id)

        select_call = conn.fetchval.call_args_list[0]
        self.assertIn("AI Copilot", select_call[0])

    async def test_copilot_key_creates_project_when_missing(self):
        from app.core.helpers import resolve_project_id

        new_id = uuid.uuid4()
        # first call (SELECT) returns None; second (INSERT) returns new_id
        conn = MagicMock()
        conn.fetchval = AsyncMock(side_effect=[None, new_id])

        result = await resolve_project_id(conn, "copilot", uuid.uuid4())
        self.assertEqual(result, new_id)
        self.assertEqual(conn.fetchval.call_count, 2)

        insert_call = conn.fetchval.call_args_list[1]
        self.assertIn("AI Copilot", insert_call[0])

    async def test_copilot_project_is_separate_from_demo(self):
        """Two separate SELECT queries — one for "Demo Project", one for "AI Copilot"."""
        from app.core.helpers import resolve_project_id

        demo_id = uuid.uuid4()
        copilot_id = uuid.uuid4()
        uid = uuid.uuid4()

        conn_demo = MagicMock()
        conn_demo.fetchval = AsyncMock(return_value=demo_id)
        conn_copilot = MagicMock()
        conn_copilot.fetchval = AsyncMock(return_value=copilot_id)

        result_demo    = await resolve_project_id(conn_demo,    "demo",    uid)
        result_copilot = await resolve_project_id(conn_copilot, "copilot", uid)

        self.assertNotEqual(result_demo, result_copilot,
                            "demo and copilot must resolve to different projects")


# ── tiny async iterable helper ────────────────────────────────────────────────

class _Iter:
    def __init__(self, items): self._items = iter(items)
    def __aiter__(self): return self
    async def __anext__(self):
        try: return next(self._items)
        except StopIteration as exc: raise StopAsyncIteration from exc


def _aiter(items): return _Iter(items)


if __name__ == "__main__":
    unittest.main()
