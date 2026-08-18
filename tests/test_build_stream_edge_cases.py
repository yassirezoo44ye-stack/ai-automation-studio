"""
Build endpoint edge-case tests.

Coverage:
  - valid project_id   → build streams successfully
  - missing project_id → 422 (Pydantic required field)
  - unauthorized project_id (another user's project) → 404
  - provider available  → stream proceeds normally
  - provider unavailable (circuit open) → SSE error event, no done
  - generated files  → written to workspace, file SSE events emitted
  - preview/run endpoint ownership guard
  - i18n: Arabic and English prompts accepted without issue

DB interaction is mocked throughout — no live Postgres needed.
Follows the exact pattern of test_ai_gateway_migration_chat_build.py:
  _fake_pool() + patch object / patch path.
"""
from __future__ import annotations

import sys
import unittest
import unittest.mock
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import HTTPException


# ── Shared fixtures ───────────────────────────────────────────────────────────

def _fake_pool():
    """Pool mock whose acquire() yields a MagicMock conn
    with AsyncMock fetchval/fetch/execute — sufficient for every DB call
    build.py makes around the (mocked) AI call."""
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
    """Async generator over a scripted chunk list, matching what
    InferenceEngine.stream() yields. If raise_after is set, raises that
    exception after the last scripted chunk (simulates a raw drop)."""

    def __init__(self, chunks, raise_after: Exception | None = None):
        self._chunks = chunks
        self._raise_after = raise_after

    async def __aiter__(self):
        for c in self._chunks:
            yield c
        if self._raise_after is not None:
            raise self._raise_after


# ── build_stream: valid project_id ────────────────────────────────────────────

class TestBuildStreamValidProjectId(unittest.IsolatedAsyncioTestCase):
    """A valid project_id owned by the caller → stream completes normally."""

    async def test_valid_project_id_streams_to_done(self):
        from app.routers import build as build_mod

        pool, _ = _fake_pool()
        written_files: dict[str, str] = {}

        def fake_safe_path(ws, path):
            p = MagicMock()
            p.parent.mkdir = MagicMock()
            p.write_text = lambda content, encoding: written_files.__setitem__(path, content)
            return p

        with unittest.mock.patch.object(
            build_mod, "ai_rate_limit", MagicMock(),
        ), unittest.mock.patch.object(
            build_mod, "check_org_quota", AsyncMock(return_value="org-valid"),
        ), unittest.mock.patch.object(
            build_mod, "get_pool", return_value=pool,
        ), unittest.mock.patch.object(
            build_mod, "owner_user_id", AsyncMock(return_value=uuid.uuid4()),
        ), unittest.mock.patch.object(
            # resolve_project_id returns normally → project is valid + owned
            build_mod, "resolve_project_id", AsyncMock(return_value=uuid.uuid4()),
        ), unittest.mock.patch.object(
            build_mod, "record_org_tokens", AsyncMock(),
        ) as mock_record, unittest.mock.patch.object(
            build_mod, "workspace", return_value=Path("ws"),
        ), unittest.mock.patch.object(
            build_mod, "safe_path", side_effect=fake_safe_path,
        ), unittest.mock.patch(
            "app.core.ai.inference.engine.InferenceEngine.stream",
            return_value=_StreamChunks([
                {"type": "delta", "text": "<<<FILE: app.py>>>\nprint('hello')\n<<<ENDFILE>>>\n"},
                {"type": "delta", "text": "<<<META>>>\n"},
                {"type": "delta", "text": '{"description":"demo","run_command":"python app.py","language":"python"}\n'},
                {"type": "delta", "text": "<<<ENDMETA>>>\n"},
                {"type": "usage", "usage": {"total_tokens": 30}},
            ]),
        ):
            req = build_mod.BuildRequest(project_id="demo-pid", prompt="build a hello app")
            resp = await build_mod.build_stream(req, MagicMock())
            events = [chunk async for chunk in resp.body_iterator]

        joined = "".join(events)
        # SSE must contain file event and done event
        self.assertIn('"type": "file"', joined)
        self.assertIn('"type": "done"', joined)
        # Token recording must have fired
        mock_record.assert_awaited_once()
        self.assertEqual(mock_record.call_args.args[1], 30)


# ── build_stream: missing project_id ─────────────────────────────────────────

class TestBuildStreamMissingProjectId(unittest.IsolatedAsyncioTestCase):
    """BuildRequest.project_id is a required string field.
    Pydantic raises ValidationError before the endpoint runs."""

    def test_missing_project_id_fails_validation(self):
        from pydantic import ValidationError
        from app.routers import build as build_mod

        # project_id is required — omitting it must raise immediately
        with self.assertRaises(ValidationError):
            build_mod.BuildRequest(prompt="build something")  # type: ignore[call-arg]

    def test_empty_project_id_is_accepted_by_pydantic(self):
        """Pydantic allows empty string — the runtime DB lookup is what rejects it."""
        from app.routers import build as build_mod
        # Should not raise at model level
        req = build_mod.BuildRequest(project_id="", prompt="build something")
        self.assertEqual(req.project_id, "")


# ── build_stream: unauthorized project_id ────────────────────────────────────

class TestBuildStreamUnauthorizedProjectId(unittest.IsolatedAsyncioTestCase):
    """project_id belonging to another user → resolve_project_id raises 404
    (not-found-not-forbidden convention) → HTTPException propagates to caller."""

    async def test_other_users_project_id_raises_404(self):
        from app.routers import build as build_mod

        pool, _ = _fake_pool()

        with unittest.mock.patch.object(
            build_mod, "ai_rate_limit", MagicMock(),
        ), unittest.mock.patch.object(
            build_mod, "check_org_quota", AsyncMock(return_value="org-attacker"),
        ), unittest.mock.patch.object(
            build_mod, "get_pool", return_value=pool,
        ), unittest.mock.patch.object(
            build_mod, "owner_user_id", AsyncMock(return_value=uuid.uuid4()),
        ), unittest.mock.patch.object(
            # resolve_project_id raises 404 when the caller doesn't own the project
            build_mod, "resolve_project_id",
            AsyncMock(side_effect=HTTPException(404, "Project not found")),
        ):
            req = build_mod.BuildRequest(
                project_id="other-users-project-uuid",
                prompt="steal their data",
            )
            with self.assertRaises(HTTPException) as ctx:
                await build_mod.build_stream(req, MagicMock())

        self.assertEqual(ctx.exception.status_code, 404)

    async def test_nonexistent_project_id_also_raises_404(self):
        """A completely made-up project_id looks identical to an IDOR attempt
        from the caller's perspective — both get 404, never 403."""
        from app.routers import build as build_mod

        pool, _ = _fake_pool()

        with unittest.mock.patch.object(
            build_mod, "ai_rate_limit", MagicMock(),
        ), unittest.mock.patch.object(
            build_mod, "check_org_quota", AsyncMock(return_value="org-1"),
        ), unittest.mock.patch.object(
            build_mod, "get_pool", return_value=pool,
        ), unittest.mock.patch.object(
            build_mod, "owner_user_id", AsyncMock(return_value=uuid.uuid4()),
        ), unittest.mock.patch.object(
            build_mod, "resolve_project_id",
            AsyncMock(side_effect=HTTPException(404, "Project not found")),
        ):
            req = build_mod.BuildRequest(
                project_id=str(uuid.uuid4()),
                prompt="build something",
            )
            with self.assertRaises(HTTPException) as ctx:
                await build_mod.build_stream(req, MagicMock())

        self.assertEqual(ctx.exception.status_code, 404)
        # Must NOT be 403 — the convention is always 404
        self.assertNotEqual(ctx.exception.status_code, 403)


# ── build_stream: provider available ─────────────────────────────────────────

class TestBuildStreamProviderAvailable(unittest.IsolatedAsyncioTestCase):
    """When InferenceEngine.stream() succeeds, events flow through to done."""

    async def test_provider_available_emits_done_and_meta(self):
        from app.routers import build as build_mod

        pool, _ = _fake_pool()
        written_files: dict[str, str] = {}

        def fake_safe_path(ws, path):
            p = MagicMock()
            p.parent.mkdir = MagicMock()
            p.write_text = lambda content, encoding: written_files.__setitem__(path, content)
            return p

        with unittest.mock.patch.object(
            build_mod, "ai_rate_limit", MagicMock(),
        ), unittest.mock.patch.object(
            build_mod, "check_org_quota", AsyncMock(return_value="org-ok"),
        ), unittest.mock.patch.object(
            build_mod, "get_pool", return_value=pool,
        ), unittest.mock.patch.object(
            build_mod, "owner_user_id", AsyncMock(return_value=uuid.uuid4()),
        ), unittest.mock.patch.object(
            build_mod, "resolve_project_id", AsyncMock(return_value=uuid.uuid4()),
        ), unittest.mock.patch.object(
            build_mod, "record_org_tokens", AsyncMock(),
        ), unittest.mock.patch.object(
            build_mod, "workspace", return_value=Path("ws"),
        ), unittest.mock.patch.object(
            build_mod, "safe_path", side_effect=fake_safe_path,
        ), unittest.mock.patch(
            "app.core.ai.inference.engine.InferenceEngine.stream",
            return_value=_StreamChunks([
                {"type": "delta", "text": "<<<FILE: main.py>>>\nprint('ok')\n<<<ENDFILE>>>\n"},
                {"type": "delta", "text": "<<<META>>>\n"},
                {"type": "delta", "text": '{"description":"ok","run_command":"python main.py","language":"python"}\n'},
                {"type": "delta", "text": "<<<ENDMETA>>>\n"},
                {"type": "usage", "usage": {"total_tokens": 50}},
            ]),
        ):
            req = build_mod.BuildRequest(project_id="pid-ok", prompt="make me a thing")
            resp = await build_mod.build_stream(req, MagicMock())
            events = [chunk async for chunk in resp.body_iterator]

        joined = "".join(events)
        self.assertIn('"type": "done"', joined)
        self.assertIn('"description": "ok"', joined)
        self.assertIn('"run_command": "python main.py"', joined)
        self.assertIn("main.py", written_files)


# ── build_stream: provider unavailable ───────────────────────────────────────

class TestBuildStreamProviderUnavailable(unittest.IsolatedAsyncioTestCase):
    """When every provider's circuit is open → 503."""

    async def test_circuit_open_stops_stream_with_error_not_done(self):
        from app.routers import build as build_mod

        pool, _ = _fake_pool()

        with unittest.mock.patch.object(
            build_mod, "ai_rate_limit", MagicMock(),
        ), unittest.mock.patch.object(
            build_mod, "check_org_quota", AsyncMock(return_value="org-1"),
        ), unittest.mock.patch.object(
            build_mod, "get_pool", return_value=pool,
        ), unittest.mock.patch.object(
            build_mod, "owner_user_id", AsyncMock(return_value=uuid.uuid4()),
        ), unittest.mock.patch.object(
            build_mod, "resolve_project_id", AsyncMock(return_value=uuid.uuid4()),
        ), unittest.mock.patch(
            "app.core.ai.inference.engine.InferenceEngine.stream",
            return_value=_StreamChunks(
                [],
                raise_after=RuntimeError("every provider's circuit is open"),
            ),
        ):
            req = build_mod.BuildRequest(project_id="pid-down", prompt="build")
            resp = await build_mod.build_stream(req, MagicMock())
            events = [chunk async for chunk in resp.body_iterator]

        joined = "".join(events)
        self.assertIn('"type": "error"', joined)
        self.assertNotIn('"type": "done"', joined)

    async def test_provider_error_chunk_stops_stream(self):
        """An error StreamChunk (not a raw exception) also prevents 'done'."""
        from app.routers import build as build_mod

        pool, _ = _fake_pool()

        with unittest.mock.patch.object(
            build_mod, "ai_rate_limit", MagicMock(),
        ), unittest.mock.patch.object(
            build_mod, "check_org_quota", AsyncMock(return_value="org-1"),
        ), unittest.mock.patch.object(
            build_mod, "get_pool", return_value=pool,
        ), unittest.mock.patch.object(
            build_mod, "owner_user_id", AsyncMock(return_value=uuid.uuid4()),
        ), unittest.mock.patch.object(
            build_mod, "resolve_project_id", AsyncMock(return_value=uuid.uuid4()),
        ), unittest.mock.patch(
            "app.core.ai.inference.engine.InferenceEngine.stream",
            return_value=_StreamChunks([
                {"type": "error", "error": "No AI providers available"},
            ]),
        ):
            req = build_mod.BuildRequest(project_id="pid-down", prompt="build")
            resp = await build_mod.build_stream(req, MagicMock())
            events = [chunk async for chunk in resp.body_iterator]

        joined = "".join(events)
        self.assertIn('"type": "error"', joined)
        self.assertIn("No AI providers available", joined)
        self.assertNotIn('"type": "done"', joined)


# ── build_stream: generated files ────────────────────────────────────────────

class TestBuildStreamGeneratedFiles(unittest.IsolatedAsyncioTestCase):
    """Files announced in the stream must be written to disk and
    reported via SSE file events."""

    async def test_multiple_files_all_written_and_reported(self):
        from app.routers import build as build_mod

        pool, _ = _fake_pool()
        written_files: dict[str, str] = {}

        def fake_safe_path(ws, path):
            p = MagicMock()
            p.parent.mkdir = MagicMock()
            p.write_text = lambda content, encoding: written_files.__setitem__(path, content)
            return p

        payload = (
            "<<<FILE: index.html>>>\n<html>hello</html>\n<<<ENDFILE>>>\n"
            "<<<FILE: style.css>>>\nbody{margin:0}\n<<<ENDFILE>>>\n"
            "<<<FILE: app.js>>>\nconsole.log(1)\n<<<ENDFILE>>>\n"
            "<<<META>>>\n"
            '{"description":"web app","run_command":"open index.html","language":"html"}\n'
            "<<<ENDMETA>>>\n"
        )

        with unittest.mock.patch.object(
            build_mod, "ai_rate_limit", MagicMock(),
        ), unittest.mock.patch.object(
            build_mod, "check_org_quota", AsyncMock(return_value="org-ok"),
        ), unittest.mock.patch.object(
            build_mod, "get_pool", return_value=pool,
        ), unittest.mock.patch.object(
            build_mod, "owner_user_id", AsyncMock(return_value=uuid.uuid4()),
        ), unittest.mock.patch.object(
            build_mod, "resolve_project_id", AsyncMock(return_value=uuid.uuid4()),
        ), unittest.mock.patch.object(
            build_mod, "record_org_tokens", AsyncMock(),
        ), unittest.mock.patch.object(
            build_mod, "workspace", return_value=Path("ws"),
        ), unittest.mock.patch.object(
            build_mod, "safe_path", side_effect=fake_safe_path,
        ), unittest.mock.patch(
            "app.core.ai.inference.engine.InferenceEngine.stream",
            return_value=_StreamChunks([
                {"type": "delta", "text": payload},
                {"type": "usage", "usage": {"total_tokens": 120}},
            ]),
        ):
            req = build_mod.BuildRequest(project_id="pid-files", prompt="make a web app")
            resp = await build_mod.build_stream(req, MagicMock())
            events = [chunk async for chunk in resp.body_iterator]

        joined = "".join(events)
        # All three files must appear in SSE stream
        self.assertIn("index.html", joined)
        self.assertIn("style.css", joined)
        self.assertIn("app.js", joined)
        # All three must have been written to disk
        self.assertIn("index.html", written_files)
        self.assertIn("style.css", written_files)
        self.assertIn("app.js", written_files)
        # Content integrity
        self.assertEqual(written_files["index.html"], "<html>hello</html>")
        self.assertEqual(written_files["style.css"], "body{margin:0}")
        self.assertIn('"type": "done"', joined)


# ── build_stream: preview URL in events ──────────────────────────────────────

class TestBuildStreamPreviewEvents(unittest.IsolatedAsyncioTestCase):
    """run_command and language must appear in the done/meta SSE event."""

    async def test_meta_block_emitted_as_done_event(self):
        from app.routers import build as build_mod

        pool, _ = _fake_pool()
        written_files: dict[str, str] = {}

        def fake_safe_path(ws, path):
            p = MagicMock()
            p.parent.mkdir = MagicMock()
            p.write_text = lambda content, encoding: written_files.__setitem__(path, content)
            return p

        with unittest.mock.patch.object(
            build_mod, "ai_rate_limit", MagicMock(),
        ), unittest.mock.patch.object(
            build_mod, "check_org_quota", AsyncMock(return_value="org-1"),
        ), unittest.mock.patch.object(
            build_mod, "get_pool", return_value=pool,
        ), unittest.mock.patch.object(
            build_mod, "owner_user_id", AsyncMock(return_value=uuid.uuid4()),
        ), unittest.mock.patch.object(
            build_mod, "resolve_project_id", AsyncMock(return_value=uuid.uuid4()),
        ), unittest.mock.patch.object(
            build_mod, "record_org_tokens", AsyncMock(),
        ), unittest.mock.patch.object(
            build_mod, "workspace", return_value=Path("ws"),
        ), unittest.mock.patch.object(
            build_mod, "safe_path", side_effect=fake_safe_path,
        ), unittest.mock.patch(
            "app.core.ai.inference.engine.InferenceEngine.stream",
            return_value=_StreamChunks([
                {"type": "delta", "text": "<<<FILE: server.py>>>\nfrom flask import Flask\n<<<ENDFILE>>>\n"},
                {"type": "delta", "text": "<<<META>>>\n"},
                {"type": "delta", "text": '{"description":"Flask API","run_command":"python server.py","language":"python"}\n'},
                {"type": "delta", "text": "<<<ENDMETA>>>\n"},
                {"type": "usage", "usage": {"total_tokens": 75}},
            ]),
        ):
            req = build_mod.BuildRequest(project_id="pid-preview", prompt="build a Flask API")
            resp = await build_mod.build_stream(req, MagicMock())
            events = [chunk async for chunk in resp.body_iterator]

        joined = "".join(events)
        self.assertIn('"type": "done"', joined)
        self.assertIn('"run_command": "python server.py"', joined)
        self.assertIn('"language": "python"', joined)
        self.assertIn('"description": "Flask API"', joined)


# ── i18n: Arabic and English prompts ─────────────────────────────────────────

class TestBuildStreamI18N(unittest.IsolatedAsyncioTestCase):
    """Arabic and English prompts both pass Pydantic validation and
    reach InferenceEngine.stream() unchanged."""

    async def _run_build_with_prompt(self, prompt: str) -> str:
        """Returns the joined SSE events string from build_stream."""
        from app.routers import build as build_mod

        pool, _ = _fake_pool()
        written_files: dict[str, str] = {}

        def fake_safe_path(ws, path):
            p = MagicMock()
            p.parent.mkdir = MagicMock()
            p.write_text = lambda content, encoding: written_files.__setitem__(path, content)
            return p

        with unittest.mock.patch.object(
            build_mod, "ai_rate_limit", MagicMock(),
        ), unittest.mock.patch.object(
            build_mod, "check_org_quota", AsyncMock(return_value="org-1"),
        ), unittest.mock.patch.object(
            build_mod, "get_pool", return_value=pool,
        ), unittest.mock.patch.object(
            build_mod, "owner_user_id", AsyncMock(return_value=uuid.uuid4()),
        ), unittest.mock.patch.object(
            build_mod, "resolve_project_id", AsyncMock(return_value=uuid.uuid4()),
        ), unittest.mock.patch.object(
            build_mod, "record_org_tokens", AsyncMock(),
        ), unittest.mock.patch.object(
            build_mod, "workspace", return_value=Path("ws"),
        ), unittest.mock.patch.object(
            build_mod, "safe_path", side_effect=fake_safe_path,
        ), unittest.mock.patch(
            "app.core.ai.inference.engine.InferenceEngine.stream",
            return_value=_StreamChunks([
                # Must include at least one file or the router emits an error
                # instead of done ("Claude did not produce any files").
                {"type": "delta", "text": "<<<FILE: main.py>>>\nprint('ok')\n<<<ENDFILE>>>\n"},
                {"type": "delta", "text": "<<<META>>>\n"},
                {"type": "delta", "text": '{"description":"ok","run_command":"python main.py","language":"python"}\n'},
                {"type": "delta", "text": "<<<ENDMETA>>>\n"},
                {"type": "usage", "usage": {"total_tokens": 10}},
            ]),
        ):
            req = build_mod.BuildRequest(project_id="pid-i18n", prompt=prompt)
            resp = await build_mod.build_stream(req, MagicMock())
            events = [chunk async for chunk in resp.body_iterator]

        return "".join(events)

    async def test_english_prompt_accepted_and_streams_to_done(self):
        """English prompt reaches build_stream and produces a done event."""
        joined = await self._run_build_with_prompt("Build a CRM system with AI automation")
        self.assertIn('"type": "done"', joined)

    async def test_arabic_prompt_accepted_and_streams_to_done(self):
        """Arabic prompt (RTL unicode) reaches build_stream without error."""
        joined = await self._run_build_with_prompt("ابنِ نظام CRM بالأتمتة الذكية")
        self.assertIn('"type": "done"', joined)
        self.assertNotIn('"type": "error"', joined)

    async def test_mixed_arabic_english_prompt_accepted(self):
        """Mixed Arabic+English prompt is accepted by Pydantic and reaches engine."""
        joined = await self._run_build_with_prompt(
            "Build CRM نظام with HR portal بوابة الموارد البشرية"
        )
        self.assertIn('"type": "done"', joined)


# ── project_id ownership: endpoint-level guard ───────────────────────────────

class TestRequireProjectOwner(unittest.IsolatedAsyncioTestCase):
    """_require_project_owner is used by all /api/projects/{id}/* endpoints.
    Verify it raises 404 when resolve_project_id raises, and passes when
    the project is owned."""

    async def test_owned_project_passes_guard(self):
        from app.routers import build as build_mod

        pool, _ = _fake_pool()
        request = MagicMock()
        request.app.state = MagicMock()

        with unittest.mock.patch.object(
            build_mod, "get_pool", return_value=pool,
        ), unittest.mock.patch.object(
            build_mod, "owner_user_id", AsyncMock(return_value=uuid.uuid4()),
        ), unittest.mock.patch.object(
            build_mod, "resolve_project_id", AsyncMock(return_value=uuid.uuid4()),
        ):
            # Should not raise
            await build_mod._require_project_owner("my-project", request)

    async def test_unowned_project_raises_404(self):
        from app.routers import build as build_mod

        pool, _ = _fake_pool()
        request = MagicMock()

        with unittest.mock.patch.object(
            build_mod, "get_pool", return_value=pool,
        ), unittest.mock.patch.object(
            build_mod, "owner_user_id", AsyncMock(return_value=uuid.uuid4()),
        ), unittest.mock.patch.object(
            build_mod, "resolve_project_id",
            AsyncMock(side_effect=HTTPException(404, "Project not found")),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await build_mod._require_project_owner("stolen-project", request)

        self.assertEqual(ctx.exception.status_code, 404)


# ── BuildRequest field contract ───────────────────────────────────────────────

class TestBuildRequestContract(unittest.IsolatedAsyncioTestCase):
    """BuildRequest model must have exactly the right required fields and
    must NOT expose org_id (must come from server-side auth context)."""

    def test_project_id_is_required(self):
        from pydantic import ValidationError
        from app.routers import build as build_mod

        with self.assertRaises(ValidationError):
            build_mod.BuildRequest(prompt="hello")  # type: ignore[call-arg]

    def test_prompt_is_required(self):
        from pydantic import ValidationError
        from app.routers import build as build_mod

        with self.assertRaises(ValidationError):
            build_mod.BuildRequest(project_id="pid")  # type: ignore[call-arg]

    def test_no_org_id_field(self):
        from app.routers import build as build_mod

        # org_id must NOT be in the request body — it comes from JWT auth context
        self.assertFalse(
            hasattr(build_mod.BuildRequest, "org_id"),
            "BuildRequest must not have org_id — it must come from JWT auth context",
        )

    def test_no_user_id_field(self):
        from app.routers import build as build_mod

        self.assertFalse(
            hasattr(build_mod.BuildRequest, "user_id"),
            "BuildRequest must not have user_id — it must come from JWT auth context",
        )

    def test_valid_request_passes(self):
        from app.routers import build as build_mod

        req = build_mod.BuildRequest(project_id="proj-1", prompt="make a todo app")
        self.assertEqual(req.project_id, "proj-1")
        self.assertEqual(req.prompt, "make a todo app")


if __name__ == "__main__":
    unittest.main()
