"""
AI Gateway Migration — Commit 1: chat.py + build.py -> InferenceEngine.

Covers the 4 migrated call sites (chat.py::run_stream/run_agent,
build.py::build_program/build_stream): that InferenceEngine.complete()/
.stream() is called with the exact kwargs the migration plan requires
(auto_tools=False, conversation_id=None, org_id=None), that record_org_tokens
still gets the right total, that provider-exception -> HTTP-status mapping
(401/402/503/502) is preserved, that the streaming SSE wire format the
frontend depends on is unchanged (including the error->message key
translation InferenceEngine.stream()'s StreamChunk requires), and that
build_stream's real _BuildParser still correctly assembles files out of
scripted delta chunks — including one that splits an <<<ENDFILE>>> marker
across a chunk boundary, the one case most likely to break silently.

DB interaction is mocked throughout (matching tests/test_reliability_wiring.py
and tests/test_ai_routing.py's DB-free convention) — no live Postgres needed.
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
    """A get_pool() replacement whose .acquire() yields a MagicMock conn
    with AsyncMock fetchval/fetch/execute — good enough for every DB call
    chat.py/build.py make around the (mocked) AI call itself."""
    conn = MagicMock()
    conn.fetchval = AsyncMock(return_value=uuid.uuid4())
    conn.fetch = AsyncMock(return_value=[])
    conn.execute = AsyncMock(return_value="OK")

    conn_cm = MagicMock()
    conn_cm.__aenter__ = AsyncMock(return_value=conn)
    conn_cm.__aexit__ = AsyncMock(return_value=False)

    pool = MagicMock()
    pool.acquire.return_value = conn_cm
    return pool, conn


class _StreamChunks:
    """Async generator wrapping a plain list of chunk dicts, matching what
    InferenceEngine.stream() yields. If raise_after is set, raises that
    exception mid-iteration (after yielding the scripted chunks) instead of
    completing normally — simulates a raw exception escaping the generator
    itself (e.g. a dropped connection), as opposed to a StreamChunk(type=
    "error") the registry pre-converts failures into. stream_with_events()
    never actually raises for provider failures (it always yields an error
    chunk instead), but AIGateway._enrich()/_check_quota() run before the
    registry is ever reached and are NOT wrapped that way — this fixture
    proves the router's own try/except around the whole loop is what
    guards against that class of failure, not reliance on the registry."""

    def __init__(self, chunks, raise_after: Exception | None = None):
        self._chunks = chunks
        self._raise_after = raise_after

    async def __aiter__(self):
        for c in self._chunks:
            yield c
        if self._raise_after is not None:
            raise self._raise_after


# ── run_agent / build_program: complete() call-shape + token recording ─────

class TestRunAgentCompleteCallShape(unittest.IsolatedAsyncioTestCase):
    async def test_happy_path_records_tokens_and_calls_engine_with_isolated_kwargs(self):
        from app.routers import chat as chat_mod

        pool, conn = _fake_pool()
        fake_resp = CompletionResponse(
            content="hello back",
            usage=UsageStats(input_tokens=10, output_tokens=5, total_tokens=15, cost_usd=0.001),
        )

        with unittest.mock.patch.object(
            chat_mod, "check_org_quota", AsyncMock(return_value="org-1"),
        ), unittest.mock.patch.object(
            chat_mod, "get_pool", return_value=pool,
        ), unittest.mock.patch.object(
            chat_mod, "owner_user_id", AsyncMock(return_value=uuid.uuid4()),
        ), unittest.mock.patch.object(
            chat_mod, "resolve_project_id", AsyncMock(return_value=uuid.uuid4()),
        ), unittest.mock.patch.object(
            chat_mod, "record_org_tokens", AsyncMock(),
        ) as mock_record, unittest.mock.patch(
            "app.core.ai.inference.engine.InferenceEngine.complete",
            AsyncMock(return_value=fake_resp),
        ) as mock_complete:
            req = chat_mod.RunRequest(project_id="demo", prompt="hello")
            result = await chat_mod.run_agent(req, MagicMock())

        self.assertEqual(result, {"result": {"summary": "hello back"}})
        mock_record.assert_awaited_once()
        self.assertEqual(mock_record.call_args.args[0], "org-1")
        self.assertEqual(mock_record.call_args.args[1], 15)

        mock_complete.assert_awaited_once()
        _, kwargs = mock_complete.call_args
        self.assertFalse(kwargs["auto_tools"])
        self.assertIsNone(kwargs["org_id"])
        self.assertIsInstance(kwargs["user_id"], str)
        sent_request = mock_complete.call_args.args[0]
        self.assertIsNone(sent_request.conversation_id)
        self.assertIsNone(sent_request.prompt_id)
        self.assertFalse(sent_request.memory_enabled)

    async def test_authentication_error_maps_to_401(self):
        from app.routers import chat as chat_mod

        pool, _ = _fake_pool()
        with unittest.mock.patch.object(
            chat_mod, "check_org_quota", AsyncMock(return_value=None),
        ), unittest.mock.patch.object(
            chat_mod, "get_pool", return_value=pool,
        ), unittest.mock.patch.object(
            chat_mod, "owner_user_id", AsyncMock(return_value=uuid.uuid4()),
        ), unittest.mock.patch(
            "app.core.ai.inference.engine.InferenceEngine.complete",
            AsyncMock(side_effect=anthropic.AuthenticationError(
                "bad key", response=MagicMock(), body=None,
            )),
        ):
            req = chat_mod.RunRequest(project_id="demo", prompt="hello")
            with self.assertRaises(HTTPException) as ctx:
                await chat_mod.run_agent(req, MagicMock())
        self.assertEqual(ctx.exception.status_code, 401)

    async def test_bad_request_error_maps_to_402(self):
        from app.routers import chat as chat_mod

        pool, _ = _fake_pool()
        fake_response = MagicMock()
        fake_response.headers = {}
        err = anthropic.BadRequestError(
            "billing issue", response=fake_response,
            body={"error": {"message": "insufficient credit"}},
        )
        with unittest.mock.patch.object(
            chat_mod, "check_org_quota", AsyncMock(return_value=None),
        ), unittest.mock.patch.object(
            chat_mod, "get_pool", return_value=pool,
        ), unittest.mock.patch.object(
            chat_mod, "owner_user_id", AsyncMock(return_value=uuid.uuid4()),
        ), unittest.mock.patch(
            "app.core.ai.inference.engine.InferenceEngine.complete",
            AsyncMock(side_effect=err),
        ):
            req = chat_mod.RunRequest(project_id="demo", prompt="hello")
            with self.assertRaises(HTTPException) as ctx:
                await chat_mod.run_agent(req, MagicMock())
        self.assertEqual(ctx.exception.status_code, 402)

    async def test_circuit_open_runtime_error_maps_to_503(self):
        from app.routers import chat as chat_mod

        pool, _ = _fake_pool()
        with unittest.mock.patch.object(
            chat_mod, "check_org_quota", AsyncMock(return_value=None),
        ), unittest.mock.patch.object(
            chat_mod, "get_pool", return_value=pool,
        ), unittest.mock.patch.object(
            chat_mod, "owner_user_id", AsyncMock(return_value=uuid.uuid4()),
        ), unittest.mock.patch(
            "app.core.ai.inference.engine.InferenceEngine.complete",
            AsyncMock(side_effect=RuntimeError("every provider's circuit is open")),
        ):
            req = chat_mod.RunRequest(project_id="demo", prompt="hello")
            with self.assertRaises(HTTPException) as ctx:
                await chat_mod.run_agent(req, MagicMock())
        self.assertEqual(ctx.exception.status_code, 503)

    async def test_unexpected_error_maps_to_502(self):
        from app.routers import chat as chat_mod

        pool, _ = _fake_pool()
        with unittest.mock.patch.object(
            chat_mod, "check_org_quota", AsyncMock(return_value=None),
        ), unittest.mock.patch.object(
            chat_mod, "get_pool", return_value=pool,
        ), unittest.mock.patch.object(
            chat_mod, "owner_user_id", AsyncMock(return_value=uuid.uuid4()),
        ), unittest.mock.patch(
            "app.core.ai.inference.engine.InferenceEngine.complete",
            AsyncMock(side_effect=ValueError("boom")),
        ):
            req = chat_mod.RunRequest(project_id="demo", prompt="hello")
            with self.assertRaises(HTTPException) as ctx:
                await chat_mod.run_agent(req, MagicMock())
        self.assertEqual(ctx.exception.status_code, 502)


class TestBuildProgramCompleteCallShape(unittest.IsolatedAsyncioTestCase):
    async def test_happy_path_calls_engine_with_isolated_kwargs_and_system_prompt(self):
        from app.routers import build as build_mod

        pool, _ = _fake_pool()
        fake_resp = CompletionResponse(
            content='{"description":"d","files":[],"run_command":"","language":"python"}',
            usage=UsageStats(input_tokens=20, output_tokens=8, total_tokens=28, cost_usd=0.002),
        )

        with unittest.mock.patch.object(
            build_mod, "check_org_quota", AsyncMock(return_value="org-1"),
        ), unittest.mock.patch.object(
            build_mod, "get_pool", return_value=pool,
        ), unittest.mock.patch.object(
            build_mod, "owner_user_id", AsyncMock(return_value=uuid.uuid4()),
        ), unittest.mock.patch.object(
            build_mod, "resolve_project_id", AsyncMock(return_value=uuid.uuid4()),
        ), unittest.mock.patch.object(
            build_mod, "record_org_tokens", AsyncMock(),
        ) as mock_record, unittest.mock.patch.object(
            build_mod, "workspace", return_value=Path("does-not-matter"),
        ), unittest.mock.patch(
            "app.core.ai.inference.engine.InferenceEngine.complete",
            AsyncMock(return_value=fake_resp),
        ) as mock_complete:
            req = build_mod.BuildRequest(project_id="demo", prompt="build me a thing")
            result = await build_mod.build_program(req, MagicMock())

        self.assertEqual(result["description"], "d")
        mock_record.assert_awaited_once_with("org-1", 28, "demo")

        mock_complete.assert_awaited_once()
        _, kwargs = mock_complete.call_args
        self.assertFalse(kwargs["auto_tools"])
        self.assertIsNone(kwargs["org_id"])
        sent_request = mock_complete.call_args.args[0]
        self.assertEqual(sent_request.system, build_mod.BUILD_SYSTEM)
        self.assertIsNone(sent_request.conversation_id)

    async def test_bad_request_error_maps_to_402_no_401_handling(self):
        """build_program never handled AuthenticationError specially —
        preserve that asymmetry with run_agent exactly."""
        from app.routers import build as build_mod

        pool, _ = _fake_pool()
        fake_response = MagicMock()
        fake_response.headers = {}
        err = anthropic.BadRequestError(
            "billing issue", response=fake_response,
            body={"error": {"message": "insufficient credit"}},
        )
        with unittest.mock.patch.object(
            build_mod, "check_org_quota", AsyncMock(return_value=None),
        ), unittest.mock.patch.object(
            build_mod, "get_pool", return_value=pool,
        ), unittest.mock.patch.object(
            build_mod, "owner_user_id", AsyncMock(return_value=uuid.uuid4()),
        ), unittest.mock.patch.object(
            build_mod, "resolve_project_id", AsyncMock(return_value=uuid.uuid4()),
        ), unittest.mock.patch(
            "app.core.ai.inference.engine.InferenceEngine.complete",
            AsyncMock(side_effect=err),
        ):
            req = build_mod.BuildRequest(project_id="demo", prompt="build me a thing")
            with self.assertRaises(HTTPException) as ctx:
                await build_mod.build_program(req, MagicMock())
        self.assertEqual(ctx.exception.status_code, 402)

    async def test_circuit_open_runtime_error_maps_to_503(self):
        from app.routers import build as build_mod

        pool, _ = _fake_pool()
        with unittest.mock.patch.object(
            build_mod, "check_org_quota", AsyncMock(return_value=None),
        ), unittest.mock.patch.object(
            build_mod, "get_pool", return_value=pool,
        ), unittest.mock.patch.object(
            build_mod, "owner_user_id", AsyncMock(return_value=uuid.uuid4()),
        ), unittest.mock.patch.object(
            build_mod, "resolve_project_id", AsyncMock(return_value=uuid.uuid4()),
        ), unittest.mock.patch(
            "app.core.ai.inference.engine.InferenceEngine.complete",
            AsyncMock(side_effect=RuntimeError("every provider's circuit is open")),
        ):
            req = build_mod.BuildRequest(project_id="demo", prompt="build me a thing")
            with self.assertRaises(HTTPException) as ctx:
                await build_mod.build_program(req, MagicMock())
        self.assertEqual(ctx.exception.status_code, 503)


# ── run_stream: SSE re-shaping, incl. error->message key translation ───────

class TestRunStreamSSEReshaping(unittest.IsolatedAsyncioTestCase):
    async def _drive(self, chat_mod, req, scripted_chunks):
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
        ) as mock_record, unittest.mock.patch(
            "app.core.ai.inference.engine.InferenceEngine.stream",
            return_value=_StreamChunks(scripted_chunks),
        ):
            resp = await chat_mod.run_stream(req, MagicMock())
            events = [chunk async for chunk in resp.body_iterator]
        return events, mock_record

    async def test_delta_conv_id_done_sequence_matches_frontend_contract(self):
        from app.routers import chat as chat_mod

        req = chat_mod.RunRequest(project_id="demo", prompt="hi")
        chunks = [
            {"type": "delta", "text": "Hel"},
            {"type": "delta", "text": "lo"},
            {"type": "usage", "usage": {"total_tokens": 42}},
            {"type": "done"},
        ]
        events, mock_record = await self._drive(chat_mod, req, chunks)

        joined = "".join(events)
        self.assertIn('"type": "conv_id"', joined)
        self.assertIn('"type": "delta", "text": "Hel"', joined)
        self.assertIn('"type": "delta", "text": "lo"', joined)
        self.assertIn('"type": "done"', joined)
        mock_record.assert_awaited_once()
        self.assertEqual(mock_record.call_args.args[1], 42)

    async def test_error_chunk_translated_to_message_key(self):
        """StreamChunk uses 'error' as its payload key; the frontend
        (ChatTab.tsx/CopilotContext.tsx) reads 'message' — the router must
        translate, not pass the raw key through."""
        from app.routers import chat as chat_mod

        req = chat_mod.RunRequest(project_id="demo", prompt="hi")
        chunks = [
            {"type": "delta", "text": "partial"},
            {"type": "error", "error": "provider exploded"},
        ]
        events, mock_record = await self._drive(chat_mod, req, chunks)

        joined = "".join(events)
        self.assertIn('"message": "provider exploded"', joined)
        self.assertNotIn('"error": "provider exploded"', joined)
        self.assertNotIn('"type": "done"', joined)
        mock_record.assert_not_awaited()  # error path skips token recording

    async def test_raw_exception_mid_stream_is_caught_not_leaked(self):
        """A raw exception escaping InferenceEngine.stream() itself (not a
        pre-converted StreamChunk error — e.g. a dropped connection inside
        AIGateway._enrich(), which runs before the registry's own
        try/except is ever reached) must still surface as a clean SSE
        error event, not an unhandled exception that crashes the
        StreamingResponse mid-flight. _drive() wraps a plain chunk list in
        _StreamChunks itself, so this bypasses it to exercise raise_after
        directly."""
        from app.routers import chat as chat_mod

        pool, conn = _fake_pool()
        req = chat_mod.RunRequest(project_id="demo", prompt="hi")
        raising_stream = _StreamChunks(
            [{"type": "delta", "text": "some text already sent"}],
            raise_after=ConnectionError("connection dropped"),
        )
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
        ) as mock_record, unittest.mock.patch(
            "app.core.ai.inference.engine.InferenceEngine.stream",
            return_value=raising_stream,
        ):
            resp = await chat_mod.run_stream(req, MagicMock())
            events = [chunk async for chunk in resp.body_iterator]

        joined = "".join(events)
        # The delta that was already sent before the drop must still have
        # reached the client (no silent truncation of already-flushed data).
        self.assertIn('"type": "delta", "text": "some text already sent"', joined)
        # The raw ConnectionError must never appear as a Python traceback —
        # only as a clean SSE error event, and 'done' must never follow it.
        self.assertIn('"type": "error"', joined)
        self.assertIn("connection dropped", joined)
        self.assertNotIn('"type": "done"', joined)
        mock_record.assert_not_awaited()


# ── build_stream: real _BuildParser fed from scripted engine.stream() ──────

class TestBuildStreamParserIntegration(unittest.IsolatedAsyncioTestCase):
    async def test_file_and_meta_assembled_across_chunk_boundaries(self):
        """Splits the payload into small, arbitrary chunk boundaries —
        including one that cuts an <<<ENDFILE>>> marker itself in half —
        proving the real _BuildParser's line-buffering survives the
        migration from the SDK's own chunking to InferenceEngine's."""
        from app.routers import build as build_mod

        full_text = (
            "<<<FILE: hello.py>>>\n"
            "print('hi')\n"
            "<<<ENDFILE>>>\n"
            "<<<META>>>\n"
            '{"description":"a demo","run_command":"python hello.py","language":"python"}\n'
            "<<<ENDMETA>>>\n"
        )
        # Split at an arbitrary offset that lands inside "<<<ENDFILE>>>".
        cut = full_text.index("<<<ENDFILE>>>") + 3
        piece_a, piece_b = full_text[:cut], full_text[cut:]

        pool, _ = _fake_pool()
        written_files: dict[str, str] = {}

        def fake_safe_path(ws, path):
            p = MagicMock()
            p.parent.mkdir = MagicMock()
            def _write(content, encoding):
                written_files[path] = content
            p.write_text = _write
            return p

        with unittest.mock.patch.object(
            build_mod, "ai_rate_limit", MagicMock(),
        ), unittest.mock.patch.object(
            build_mod, "check_org_quota", AsyncMock(return_value=None),
        ), unittest.mock.patch.object(
            build_mod, "get_pool", return_value=pool,
        ), unittest.mock.patch.object(
            build_mod, "owner_user_id", AsyncMock(return_value=uuid.uuid4()),
        ), unittest.mock.patch.object(
            build_mod, "resolve_project_id", AsyncMock(return_value=uuid.uuid4()),
        ), unittest.mock.patch.object(
            build_mod, "workspace", return_value=Path("ws"),
        ), unittest.mock.patch.object(
            build_mod, "safe_path", side_effect=fake_safe_path,
        ), unittest.mock.patch(
            "app.core.ai.inference.engine.InferenceEngine.stream",
            return_value=_StreamChunks([
                {"type": "delta", "text": piece_a},
                {"type": "delta", "text": piece_b},
                {"type": "usage", "usage": {"total_tokens": 99}},
            ]),
        ):
            req = build_mod.BuildRequest(project_id="demo", prompt="build me a thing")
            resp = await build_mod.build_stream(req, MagicMock())
            events = [chunk async for chunk in resp.body_iterator]

        joined = "".join(events)
        self.assertIn("hello.py", written_files)
        self.assertEqual(written_files["hello.py"], "print('hi')")
        self.assertIn('"type": "done"', joined)
        self.assertIn('"description": "a demo"', joined)
        self.assertIn('"run_command": "python hello.py"', joined)

    async def test_error_chunk_stops_before_completion_events(self):
        from app.routers import build as build_mod

        pool, _ = _fake_pool()
        with unittest.mock.patch.object(
            build_mod, "ai_rate_limit", MagicMock(),
        ), unittest.mock.patch.object(
            build_mod, "check_org_quota", AsyncMock(return_value=None),
        ), unittest.mock.patch.object(
            build_mod, "get_pool", return_value=pool,
        ), unittest.mock.patch.object(
            build_mod, "owner_user_id", AsyncMock(return_value=uuid.uuid4()),
        ), unittest.mock.patch.object(
            build_mod, "resolve_project_id", AsyncMock(return_value=uuid.uuid4()),
        ), unittest.mock.patch.object(
            build_mod, "workspace", return_value=Path("ws"),
        ), unittest.mock.patch(
            "app.core.ai.inference.engine.InferenceEngine.stream",
            return_value=_StreamChunks([
                {"type": "delta", "text": "<<<FILE: partial.py>>>\nprint(1)\n"},
                {"type": "error", "error": "connection reset"},
            ]),
        ):
            req = build_mod.BuildRequest(project_id="demo", prompt="build me a thing")
            resp = await build_mod.build_stream(req, MagicMock())
            events = [chunk async for chunk in resp.body_iterator]

        joined = "".join(events)
        self.assertIn('"message": "connection reset"', joined)
        self.assertNotIn('"type": "done"', joined)

    async def test_raw_exception_mid_stream_is_caught_not_leaked(self):
        """Same guarantee as chat.py's run_stream: a raw exception escaping
        InferenceEngine.stream() (not a StreamChunk error) after a file has
        already been written must surface as a clean SSE error event, not
        an unhandled crash — and must not proceed to the completion tail
        (done/meta/usage_logs)."""
        from app.routers import build as build_mod

        pool, _ = _fake_pool()
        written_files: dict[str, str] = {}

        def fake_safe_path(ws, path):
            p = MagicMock()
            p.parent.mkdir = MagicMock()
            def _write(content, encoding):
                written_files[path] = content
            p.write_text = _write
            return p

        raising_stream = _StreamChunks(
            [{"type": "delta", "text": "<<<FILE: partial.py>>>\nprint(1)\n<<<ENDFILE>>>\n"}],
            raise_after=ConnectionError("connection dropped mid-build"),
        )

        with unittest.mock.patch.object(
            build_mod, "ai_rate_limit", MagicMock(),
        ), unittest.mock.patch.object(
            build_mod, "check_org_quota", AsyncMock(return_value=None),
        ), unittest.mock.patch.object(
            build_mod, "get_pool", return_value=pool,
        ), unittest.mock.patch.object(
            build_mod, "owner_user_id", AsyncMock(return_value=uuid.uuid4()),
        ), unittest.mock.patch.object(
            build_mod, "resolve_project_id", AsyncMock(return_value=uuid.uuid4()),
        ), unittest.mock.patch.object(
            build_mod, "workspace", return_value=Path("ws"),
        ), unittest.mock.patch.object(
            build_mod, "safe_path", side_effect=fake_safe_path,
        ), unittest.mock.patch(
            "app.core.ai.inference.engine.InferenceEngine.stream",
            return_value=raising_stream,
        ):
            req = build_mod.BuildRequest(project_id="demo", prompt="build me a thing")
            resp = await build_mod.build_stream(req, MagicMock())
            events = [chunk async for chunk in resp.body_iterator]

        joined = "".join(events)
        # The file completed before the drop must still have been written
        # and its SSE event still flushed (no silent truncation).
        self.assertIn("partial.py", written_files)
        self.assertIn('"type": "file"', joined)
        # The raw ConnectionError must never leak as a traceback — only a
        # clean SSE error event — and completion events must never follow.
        self.assertIn('"type": "error"', joined)
        self.assertIn("connection dropped mid-build", joined)
        self.assertNotIn('"type": "done"', joined)


# ── run_stream: context budgeting (P0, docs/context-control-audit.md §6/§18) ─
#
# chat.py's history SELECT has no LIMIT (see chat.py::run_stream) — these
# prove InferenceEngine.stream() never receives that unbounded list
# verbatim once it stops fitting the model's context window, while a
# normal short conversation is completely unaffected.

class TestRunStreamContextBudgeting(unittest.IsolatedAsyncioTestCase):
    async def _drive_with_history(self, chat_mod, req, history_rows, scripted_chunks):
        pool, conn = _fake_pool()
        conn.fetch = AsyncMock(return_value=history_rows)
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
            MagicMock(return_value=_StreamChunks(scripted_chunks)),
        ) as mock_stream:
            resp = await chat_mod.run_stream(req, MagicMock())
            events = [chunk async for chunk in resp.body_iterator]
        return events, mock_stream

    async def test_short_conversation_history_sent_unchanged(self):
        """Requirement 1/short-conversation: existing behavior must not
        change for a normal, well-within-budget conversation."""
        from app.routers import chat as chat_mod

        history_rows = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ]
        req = chat_mod.RunRequest(
            project_id="demo", prompt="how are you?", conversation_id=str(uuid.uuid4()),
        )
        chunks = [{"type": "delta", "text": "fine"}, {"type": "done"}]
        events, mock_stream = await self._drive_with_history(chat_mod, req, history_rows, chunks)

        sent_request = mock_stream.call_args.args[0]
        self.assertEqual(len(sent_request.messages), 3)  # 2 history rows + current prompt
        self.assertEqual(sent_request.messages[-1].content, "how are you?")
        self.assertIn('"type": "delta", "text": "fine"', "".join(events))

    async def test_long_conversation_is_bounded_not_sent_verbatim(self):
        """Requirements 1/2/6: a long, unbounded-from-the-DB history must
        not be forwarded verbatim to InferenceEngine.stream()."""
        from app.routers import chat as chat_mod

        history_rows = [
            {"role": "user" if i % 2 == 0 else "assistant", "content": ("x" * 8_000)}
            for i in range(120)
        ]
        req = chat_mod.RunRequest(
            project_id="demo", prompt="what's the summary so far?",
            conversation_id=str(uuid.uuid4()),
        )
        chunks = [{"type": "delta", "text": "ok"}, {"type": "done"}]
        events, mock_stream = await self._drive_with_history(chat_mod, req, history_rows, chunks)

        sent_request = mock_stream.call_args.args[0]
        # Never the full 120 history rows + current prompt (121 messages).
        self.assertLess(len(sent_request.messages), 121)
        # Requirement 4: current input is never lost, even when bounded.
        self.assertEqual(sent_request.messages[-1].content, "what's the summary so far?")
        # Requirement 7: not silent — a summary message stands in for the
        # dropped turns instead of them just vanishing.
        self.assertIn("summary", str(sent_request.messages[0].content).lower())

    async def test_overflow_returns_error_without_ever_calling_the_engine(self):
        """Requirement 8: when even the current message alone cannot fit
        the model's context window, the provider must never be called."""
        from app.routers import chat as chat_mod

        history_rows: list[dict] = []
        huge_prompt = "x" * 4_000  # RunRequest caps prompt at 4000 chars — this is the max
        req = chat_mod.RunRequest(
            project_id="demo", prompt=huge_prompt, conversation_id=str(uuid.uuid4()),
        )
        # A 4000-char prompt (~1000 tokens) fits even a small window on its
        # own, so force the floor check to fail by patching the model's
        # resolved context window down via a tiny-window model id instead —
        # simplest reliable way to hit the ContextBudgetError branch
        # end-to-end without depending on RunRequest's max_length.
        with unittest.mock.patch.object(chat_mod, "budget_history") as mock_budget:
            from app.core.ai.context.manager import ContextBudgetError
            mock_budget.side_effect = ContextBudgetError(
                "system prompt + current message alone exceed the context window",
                estimated_tokens=999_999, context_window=32_000,
            )
            events, mock_stream = await self._drive_with_history(chat_mod, req, history_rows, [])

        mock_stream.assert_not_called()
        joined = "".join(events)
        self.assertIn('"type": "error"', joined)
        self.assertIn("context window", joined)
        self.assertNotIn('"type": "done"', joined)


if __name__ == "__main__":
    unittest.main()
