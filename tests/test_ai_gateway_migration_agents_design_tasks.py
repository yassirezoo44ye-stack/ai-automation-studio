"""
AI Gateway Migration — Commit 2: agents.py + design.py + tasks.py -> InferenceEngine.

Same conventions as tests/test_ai_gateway_migration_chat_build.py (Commit 1):
mocked DB throughout, scripted InferenceEngine.complete()/.stream() to assert
exact CompletionRequest kwargs, HTTP status mapping, SSE wire format for the
one streaming site (agents.py's agent_chat_stream — reuses chat.py's own
frontend consumer per buildChatStreamUrl() in chatService.ts), and design.py's
_call_claude() fallback-on-any-failure behavior (including a circuit-open
RuntimeError) surviving the migration unchanged.
"""
from __future__ import annotations

import sys
import unittest
import unittest.mock
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

import anthropic
from fastapi import HTTPException

from app.ai.models import CompletionResponse, UsageStats


def _fake_pool():
    conn = MagicMock()
    conn.fetchval = AsyncMock(return_value=uuid.uuid4())
    conn.fetch = AsyncMock(return_value=[])
    conn.fetchrow = AsyncMock(return_value={
        "model": "claude-sonnet-4-6", "system_prompt": "You are helpful.",
    })
    conn.execute = AsyncMock(return_value="OK")

    conn_cm = MagicMock()
    conn_cm.__aenter__ = AsyncMock(return_value=conn)
    conn_cm.__aexit__ = AsyncMock(return_value=False)

    pool = MagicMock()
    pool.acquire.return_value = conn_cm
    return pool, conn


class _StreamChunks:
    def __init__(self, chunks, raise_after: Exception | None = None):
        self._chunks = chunks
        self._raise_after = raise_after

    async def __aiter__(self):
        for c in self._chunks:
            yield c
        if self._raise_after is not None:
            raise self._raise_after


# ── agents.py::agent_chat_stream — same SSE contract as chat.py ────────────

class TestAgentChatStreamSSEReshaping(unittest.IsolatedAsyncioTestCase):
    async def _drive(self, agents_mod, agent_id, req, scripted_chunks):
        pool, conn = _fake_pool()
        with unittest.mock.patch.object(
            agents_mod, "ai_rate_limit", MagicMock(),
        ), unittest.mock.patch.object(
            agents_mod, "check_org_quota", AsyncMock(return_value="org-1"),
        ), unittest.mock.patch.object(
            agents_mod, "get_pool", return_value=pool,
        ), unittest.mock.patch.object(
            agents_mod, "owner_user_id", AsyncMock(return_value=uuid.uuid4()),
        ), unittest.mock.patch.object(
            agents_mod, "resolve_project_id", AsyncMock(return_value=uuid.uuid4()),
        ), unittest.mock.patch.object(
            agents_mod, "ensure_agents_table", AsyncMock(),
        ), unittest.mock.patch.object(
            agents_mod, "record_org_tokens", AsyncMock(),
        ) as mock_record, unittest.mock.patch(
            "app.core.ai.inference.engine.InferenceEngine.stream",
            return_value=_StreamChunks(scripted_chunks),
        ) as mock_stream:
            resp = await agents_mod.agent_chat_stream(agent_id, req, MagicMock())
            events = [chunk async for chunk in resp.body_iterator]
        return events, mock_record, mock_stream

    async def test_delta_conv_id_done_matches_chat_py_contract(self):
        from app.routers import agents as agents_mod

        agent_id = str(uuid.uuid4())
        req = agents_mod.AgentChatRequest(agent_id=agent_id, prompt="hi")
        chunks = [
            {"type": "delta", "text": "Hel"},
            {"type": "delta", "text": "lo"},
            {"type": "usage", "usage": {"total_tokens": 30}},
            {"type": "done"},
        ]
        events, mock_record, mock_stream = await self._drive(agents_mod, agent_id, req, chunks)

        joined = "".join(events)
        self.assertIn('"type": "conv_id"', joined)
        self.assertIn('"type": "delta", "text": "Hel"', joined)
        self.assertIn('"type": "done"', joined)
        mock_record.assert_awaited_once()
        self.assertEqual(mock_record.call_args.args[1], 30)
        self.assertEqual(mock_record.call_args.kwargs.get("ref_type"), "agents")

        # per-agent model/system_prompt actually reached the engine
        sent_request = mock_stream.call_args.args[0]
        self.assertEqual(sent_request.model, "claude-sonnet-4-6")
        self.assertEqual(sent_request.system, "You are helpful.")
        self.assertIsNone(sent_request.conversation_id)
        _, kwargs = mock_stream.call_args
        self.assertFalse(kwargs["auto_tools"])
        self.assertIsNone(kwargs["org_id"])

    async def test_error_chunk_translated_to_message_key(self):
        from app.routers import agents as agents_mod

        agent_id = str(uuid.uuid4())
        req = agents_mod.AgentChatRequest(agent_id=agent_id, prompt="hi")
        chunks = [
            {"type": "delta", "text": "partial"},
            {"type": "error", "error": "provider exploded"},
        ]
        events, mock_record, _ = await self._drive(agents_mod, agent_id, req, chunks)

        joined = "".join(events)
        self.assertIn('"message": "provider exploded"', joined)
        self.assertNotIn('"type": "done"', joined)
        mock_record.assert_not_awaited()


# ── design.py::design_ai_generate / ai_assistant — complete() call shape ───

class TestDesignAiGenerateCallShape(unittest.IsolatedAsyncioTestCase):
    async def test_happy_path_isolated_kwargs(self):
        from app.routers import design as design_mod

        fake_resp = CompletionResponse(
            content='{"version":"6.0.0","objects":[],"background":"#000"}',
            usage=UsageStats(input_tokens=5, output_tokens=5, total_tokens=10, cost_usd=0.0001),
        )
        with unittest.mock.patch.object(
            design_mod, "ai_rate_limit", MagicMock(),
        ), unittest.mock.patch.object(
            design_mod, "check_org_quota", AsyncMock(return_value="org-1"),
        ), unittest.mock.patch.object(
            design_mod, "get_pool", return_value=MagicMock(),
        ), unittest.mock.patch.object(
            design_mod, "record_org_tokens", AsyncMock(),
        ) as mock_record, unittest.mock.patch(
            "app.core.ai.inference.engine.InferenceEngine.complete",
            AsyncMock(return_value=fake_resp),
        ) as mock_complete:
            req = design_mod.DesignAIRequest(prompt="a poster")
            result = await design_mod.design_ai_generate(req, MagicMock())

        self.assertIn("canvas_json", result)
        mock_record.assert_awaited_once()
        self.assertEqual(mock_record.call_args.args[1], 10)

        mock_complete.assert_awaited_once()
        _, kwargs = mock_complete.call_args
        self.assertFalse(kwargs["auto_tools"])
        self.assertIsNone(kwargs["org_id"])
        self.assertIsNone(kwargs["user_id"])  # design.py never fetched uid before this migration either

    async def test_circuit_open_maps_to_503(self):
        from app.routers import design as design_mod

        with unittest.mock.patch.object(
            design_mod, "ai_rate_limit", MagicMock(),
        ), unittest.mock.patch.object(
            design_mod, "check_org_quota", AsyncMock(return_value=None),
        ), unittest.mock.patch.object(
            design_mod, "get_pool", return_value=MagicMock(),
        ), unittest.mock.patch(
            "app.core.ai.inference.engine.InferenceEngine.complete",
            AsyncMock(side_effect=RuntimeError("every provider's circuit is open")),
        ):
            req = design_mod.DesignAIRequest(prompt="a poster")
            with self.assertRaises(HTTPException) as ctx:
                await design_mod.design_ai_generate(req, MagicMock())
        self.assertEqual(ctx.exception.status_code, 503)


class TestDesignAssistantCallShape(unittest.IsolatedAsyncioTestCase):
    async def test_happy_path(self):
        from app.routers import design as design_mod

        fake_resp = CompletionResponse(
            content="Try a bolder accent color.",
            usage=UsageStats(input_tokens=8, output_tokens=6, total_tokens=14, cost_usd=0.0002),
        )
        with unittest.mock.patch.object(
            design_mod, "ai_rate_limit", MagicMock(),
        ), unittest.mock.patch.object(
            design_mod, "check_org_quota", AsyncMock(return_value=None),
        ), unittest.mock.patch.object(
            design_mod, "get_pool", return_value=MagicMock(),
        ), unittest.mock.patch(
            "app.core.ai.inference.engine.InferenceEngine.complete",
            AsyncMock(return_value=fake_resp),
        ):
            req = design_mod.AssistantRequest(messages=[{"role": "user", "content": "help"}])
            result = await design_mod.ai_assistant(req, MagicMock())
        self.assertEqual(result["message"], "Try a bolder accent color.")

    async def test_invalid_role_in_caller_messages_maps_to_502_not_500(self):
        """A caller-supplied role outside the Message literal set now fails
        pydantic validation locally (inside the try block) instead of
        reaching Anthropic's API — must still surface as 502, not an
        unhandled 500."""
        from app.routers import design as design_mod

        with unittest.mock.patch.object(
            design_mod, "ai_rate_limit", MagicMock(),
        ), unittest.mock.patch.object(
            design_mod, "check_org_quota", AsyncMock(return_value=None),
        ), unittest.mock.patch.object(
            design_mod, "get_pool", return_value=MagicMock(),
        ):
            req = design_mod.AssistantRequest(messages=[{"role": "bogus_role", "content": "hi"}])
            with self.assertRaises(HTTPException) as ctx:
                await design_mod.ai_assistant(req, MagicMock())
        self.assertEqual(ctx.exception.status_code, 502)


# ── design.py::_call_claude — graceful-fallback behavior preserved ─────────

class TestCallClaudeFallbackBehavior(unittest.IsolatedAsyncioTestCase):
    async def test_circuit_open_runtime_error_still_falls_back_gracefully(self):
        """Before this migration, ai_circuit_precheck() raising
        HTTPException(503) inside _call_claude was already swallowed by the
        caller's `except (json.JSONDecodeError, Exception):` fallback — a
        circuit-open RuntimeError from InferenceEngine.complete() must be
        swallowed the exact same way, not surface as an HTTP error."""
        from app.routers import design as design_mod

        with unittest.mock.patch.object(
            design_mod, "ai_rate_limit", MagicMock(),
        ), unittest.mock.patch.object(
            design_mod, "check_org_quota", AsyncMock(return_value=None),
        ), unittest.mock.patch.object(
            design_mod, "get_pool", return_value=MagicMock(),
        ), unittest.mock.patch(
            "app.core.ai.inference.engine.InferenceEngine.complete",
            AsyncMock(side_effect=RuntimeError("every provider's circuit is open")),
        ):
            req = design_mod.PaletteRequest(prompt="sunset")
            result = await design_mod.ai_palette(req, MagicMock())
        # Falls back to the hardcoded default palette — no exception raised.
        self.assertIn("colors", result)
        self.assertEqual(len(result["colors"]), 5)

    async def test_happy_path_uses_haiku_model_not_sonnet(self):
        from app.routers import design as design_mod

        fake_resp = CompletionResponse(
            content='{"colors":[{"name":"X","hex":"#000000","role":"primary"}]}',
            usage=UsageStats(input_tokens=3, output_tokens=3, total_tokens=6, cost_usd=0.00001),
        )
        with unittest.mock.patch.object(
            design_mod, "ai_rate_limit", MagicMock(),
        ), unittest.mock.patch.object(
            design_mod, "check_org_quota", AsyncMock(return_value=None),
        ), unittest.mock.patch.object(
            design_mod, "get_pool", return_value=MagicMock(),
        ), unittest.mock.patch(
            "app.core.ai.inference.engine.InferenceEngine.complete",
            AsyncMock(return_value=fake_resp),
        ) as mock_complete:
            req = design_mod.PaletteRequest(prompt="sunset")
            await design_mod.ai_palette(req, MagicMock())

        sent_request = mock_complete.call_args.args[0]
        self.assertEqual(sent_request.model, "claude-haiku-4-5-20251001")


# ── tasks.py::extract_tasks_from_conversation — complete() call shape ──────

class TestExtractTasksCallShape(unittest.IsolatedAsyncioTestCase):
    async def _fake_pool_with_conversation(self, uid):
        conn = MagicMock()
        conn.fetchrow = AsyncMock(return_value={"id": uuid.uuid4(), "project_id": uuid.uuid4()})
        conn.fetch = AsyncMock(return_value=[{"role": "user", "content": "remind me to ship"}])
        conn.execute = AsyncMock(return_value="OK")
        conn_cm = MagicMock()
        conn_cm.__aenter__ = AsyncMock(return_value=conn)
        conn_cm.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire.return_value = conn_cm
        return pool, conn

    async def test_happy_path_isolated_kwargs(self):
        from app.routers import tasks as tasks_mod

        uid = uuid.uuid4()
        pool, conn = await self._fake_pool_with_conversation(uid)
        fake_resp = CompletionResponse(
            content='[{"title":"Ship it","priority":"medium"}]',
            usage=UsageStats(input_tokens=40, output_tokens=10, total_tokens=50, cost_usd=0.001),
        )
        with unittest.mock.patch.object(
            tasks_mod, "check_org_quota", AsyncMock(return_value="org-1"),
        ), unittest.mock.patch.object(
            tasks_mod, "get_pool", return_value=pool,
        ), unittest.mock.patch.object(
            tasks_mod, "owner_user_id", AsyncMock(return_value=uid),
        ), unittest.mock.patch.object(
            tasks_mod, "owner_email", MagicMock(return_value="a@example.com"),
        ), unittest.mock.patch.object(
            tasks_mod, "ensure_tasks_table", AsyncMock(),
        ), unittest.mock.patch.object(
            tasks_mod, "record_org_tokens", AsyncMock(),
        ) as mock_record, unittest.mock.patch(
            "app.core.ai.inference.engine.InferenceEngine.complete",
            AsyncMock(return_value=fake_resp),
        ) as mock_complete:
            conv_id = str(uuid.uuid4())
            result = await tasks_mod.extract_tasks_from_conversation(conv_id, MagicMock())

        self.assertEqual(len(result["created"]), 1)
        mock_record.assert_awaited_once()
        self.assertEqual(mock_record.call_args.args[1], 50)
        self.assertEqual(mock_record.call_args.kwargs.get("ref_type"), "tasks")

        mock_complete.assert_awaited_once()
        _, kwargs = mock_complete.call_args
        self.assertFalse(kwargs["auto_tools"])
        self.assertIsNone(kwargs["org_id"])
        self.assertEqual(kwargs["user_id"], str(uid))
        sent_request = mock_complete.call_args.args[0]
        self.assertIsNone(sent_request.conversation_id)

    async def test_bad_request_error_maps_to_402(self):
        from app.routers import tasks as tasks_mod

        uid = uuid.uuid4()
        pool, conn = await self._fake_pool_with_conversation(uid)
        fake_response = MagicMock()
        fake_response.headers = {}
        err = anthropic.BadRequestError(
            "billing issue", response=fake_response,
            body={"error": {"message": "insufficient credit"}},
        )
        with unittest.mock.patch.object(
            tasks_mod, "check_org_quota", AsyncMock(return_value=None),
        ), unittest.mock.patch.object(
            tasks_mod, "get_pool", return_value=pool,
        ), unittest.mock.patch.object(
            tasks_mod, "owner_user_id", AsyncMock(return_value=uid),
        ), unittest.mock.patch.object(
            tasks_mod, "owner_email", MagicMock(return_value="a@example.com"),
        ), unittest.mock.patch.object(
            tasks_mod, "ensure_tasks_table", AsyncMock(),
        ), unittest.mock.patch(
            "app.core.ai.inference.engine.InferenceEngine.complete",
            AsyncMock(side_effect=err),
        ):
            conv_id = str(uuid.uuid4())
            with self.assertRaises(HTTPException) as ctx:
                await tasks_mod.extract_tasks_from_conversation(conv_id, MagicMock())
        self.assertEqual(ctx.exception.status_code, 402)

    async def test_circuit_open_maps_to_503(self):
        from app.routers import tasks as tasks_mod

        uid = uuid.uuid4()
        pool, conn = await self._fake_pool_with_conversation(uid)
        with unittest.mock.patch.object(
            tasks_mod, "check_org_quota", AsyncMock(return_value=None),
        ), unittest.mock.patch.object(
            tasks_mod, "get_pool", return_value=pool,
        ), unittest.mock.patch.object(
            tasks_mod, "owner_user_id", AsyncMock(return_value=uid),
        ), unittest.mock.patch.object(
            tasks_mod, "owner_email", MagicMock(return_value="a@example.com"),
        ), unittest.mock.patch.object(
            tasks_mod, "ensure_tasks_table", AsyncMock(),
        ), unittest.mock.patch(
            "app.core.ai.inference.engine.InferenceEngine.complete",
            AsyncMock(side_effect=RuntimeError("every provider's circuit is open")),
        ):
            conv_id = str(uuid.uuid4())
            with self.assertRaises(HTTPException) as ctx:
                await tasks_mod.extract_tasks_from_conversation(conv_id, MagicMock())
        self.assertEqual(ctx.exception.status_code, 503)


if __name__ == "__main__":
    unittest.main()
