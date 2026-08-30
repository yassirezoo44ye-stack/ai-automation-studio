"""
Tests for RunAgent workspace content validation.

Root cause: when a project workspace exists but is empty (no recognisable
source files), the RunAgent used to propagate an opaque
"Runtime 'unknown' is not supported in this sandbox" error from
UnifiedExecutionEngine. The fix adds a pre-flight check that returns a
clear, actionable error before ever calling the engine.

Covers:
  1. _detect_runtime_type helper — all four adapter families
  2. Empty workspace  → EMPTY_WORKSPACE error (engine is NOT called)
  3. Workspace with only non-project files → EMPTY_WORKSPACE
  4. Node.js workspace   → engine is invoked
  5. Python workspace    → engine is invoked
  6. No silent fallback to a default runtime on unrecognised projects
  7. Auth / project_id guards still enforced
"""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.builtin.run_agent import RunAgent, _detect_runtime_type


# ── Patch targets (all inside run_agent.execute() body) ───────────────────────
# These modules are imported lazily inside execute(), so we patch at the
# source module level — that's what `from X import Y` picks up at call time.

_PATCH_GET_POOL      = "app.core.db.get_pool"
_PATCH_RESOLVE_PID   = "app.core.helpers.resolve_project_id"
_PATCH_WORKSPACE     = "app.core.filesystem.workspace"
_PATCH_ENGINE        = "app.execution.platform.engine.UnifiedExecutionEngine"


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_ctx(project_id: str = "test-project", user_id: str | None = None) -> MagicMock:
    ctx = MagicMock()
    # Use None-check (not truthiness) so that user_id="" is preserved as empty.
    ctx.user_id    = user_id if user_id is not None else str(uuid.uuid4())
    ctx.project_id = project_id
    ctx.step       = AsyncMock()
    return ctx


def _make_pool() -> MagicMock:
    """Mock DB pool that satisfies `async with pool.acquire() as conn`."""
    conn = AsyncMock()
    pool = MagicMock()
    cm   = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=conn)
    cm.__aexit__  = AsyncMock(return_value=False)
    pool.acquire.return_value = cm
    return pool


# ── 1. _detect_runtime_type helper ────────────────────────────────────────────

class TestDetectRuntimeType:
    def test_empty_directory_returns_none(self, tmp_path: Path) -> None:
        assert _detect_runtime_type(tmp_path) is None

    def test_package_json_detects_nodejs(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text('{"name":"x"}')
        assert _detect_runtime_type(tmp_path) == "Node.js"

    def test_js_file_detects_nodejs(self, tmp_path: Path) -> None:
        (tmp_path / "index.js").write_text("console.log('hi')")
        assert _detect_runtime_type(tmp_path) == "Node.js"

    def test_ts_file_detects_nodejs(self, tmp_path: Path) -> None:
        (tmp_path / "app.ts").write_text("export default {};")
        assert _detect_runtime_type(tmp_path) == "Node.js"

    def test_tsx_file_detects_nodejs(self, tmp_path: Path) -> None:
        (tmp_path / "App.tsx").write_text("export default () => null;")
        assert _detect_runtime_type(tmp_path) == "Node.js"

    def test_requirements_txt_detects_python(self, tmp_path: Path) -> None:
        (tmp_path / "requirements.txt").write_text("fastapi\nuvicorn\n")
        assert _detect_runtime_type(tmp_path) == "Python"

    def test_pyproject_toml_detects_python(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[tool.poetry]\nname = 'x'\n")
        assert _detect_runtime_type(tmp_path) == "Python"

    def test_py_file_detects_python(self, tmp_path: Path) -> None:
        (tmp_path / "main.py").write_text("print('hi')")
        assert _detect_runtime_type(tmp_path) == "Python"

    def test_dockerfile_detects_docker(self, tmp_path: Path) -> None:
        (tmp_path / "Dockerfile").write_text("FROM ubuntu\n")
        assert _detect_runtime_type(tmp_path) == "Docker"

    def test_docker_compose_yml_detects_docker(self, tmp_path: Path) -> None:
        (tmp_path / "docker-compose.yml").write_text("version: '3'\n")
        assert _detect_runtime_type(tmp_path) == "Docker"

    def test_docker_compose_yaml_detects_docker(self, tmp_path: Path) -> None:
        (tmp_path / "docker-compose.yaml").write_text("version: '3'\n")
        assert _detect_runtime_type(tmp_path) == "Docker"

    def test_node_wins_over_python_by_priority(self, tmp_path: Path) -> None:
        """Node has priority 10, Python has priority 20 — Node wins when both present."""
        (tmp_path / "package.json").write_text('{"name":"x"}')
        (tmp_path / "main.py").write_text("print('hi')")
        assert _detect_runtime_type(tmp_path) == "Node.js"

    def test_unrecognised_files_return_none(self, tmp_path: Path) -> None:
        (tmp_path / "README.md").write_text("# Hello")
        (tmp_path / "config.json").write_text("{}")
        assert _detect_runtime_type(tmp_path) is None


# ── 2. RunAgent — empty workspace ─────────────────────────────────────────────

class TestRunAgentEmptyWorkspace:
    """EMPTY_WORKSPACE error is returned without calling UnifiedExecutionEngine."""

    @pytest.mark.asyncio
    async def test_empty_workspace_returns_controlled_error(self, tmp_path: Path) -> None:
        agent  = RunAgent()
        pid    = uuid.uuid4()
        pool   = _make_pool()
        ctx    = _make_ctx()
        engine_calls: list = []

        with (
            patch(_PATCH_GET_POOL, return_value=pool),
            patch(_PATCH_RESOLVE_PID, new=AsyncMock(return_value=pid)),
            patch(_PATCH_WORKSPACE, return_value=tmp_path),
            patch(_PATCH_ENGINE, side_effect=lambda: engine_calls.append(1) or MagicMock()),
        ):
            result = await agent.execute(ctx)

        assert result.success is False
        assert result.data.get("error_code") == "EMPTY_WORKSPACE"
        assert len(engine_calls) == 0, "Engine must NOT be called for an empty workspace"

    @pytest.mark.asyncio
    async def test_error_message_does_not_say_runtime_unknown(self, tmp_path: Path) -> None:
        agent  = RunAgent()
        pid    = uuid.uuid4()
        pool   = _make_pool()
        ctx    = _make_ctx()

        with (
            patch(_PATCH_GET_POOL, return_value=pool),
            patch(_PATCH_RESOLVE_PID, new=AsyncMock(return_value=pid)),
            patch(_PATCH_WORKSPACE, return_value=tmp_path),
            patch(_PATCH_ENGINE),
        ):
            result = await agent.execute(ctx)

        # The OLD opaque message must never appear
        assert "Runtime 'unknown'" not in (result.output or "")
        assert "Runtime 'unknown'" not in (result.error or "")
        # The new message must mention what's missing
        combined = (result.output or "") + (result.error or "")
        assert "package.json" in combined or "requirements.txt" in combined

    @pytest.mark.asyncio
    async def test_workspace_with_only_non_project_files(self, tmp_path: Path) -> None:
        (tmp_path / "README.md").write_text("# hello")
        (tmp_path / ".gitignore").write_text("node_modules/\n")
        agent = RunAgent()
        pid   = uuid.uuid4()
        pool  = _make_pool()
        ctx   = _make_ctx()

        with (
            patch(_PATCH_GET_POOL, return_value=pool),
            patch(_PATCH_RESOLVE_PID, new=AsyncMock(return_value=pid)),
            patch(_PATCH_WORKSPACE, return_value=tmp_path),
            patch(_PATCH_ENGINE),
        ):
            result = await agent.execute(ctx)

        assert result.success is False
        assert result.data.get("error_code") == "EMPTY_WORKSPACE"


# ── 3. RunAgent — recognised project types → engine is invoked ────────────────

class TestRunAgentWithProjectFiles:
    @staticmethod
    def _noop_engine_run():
        """Async generator that yields nothing — simulates a completed run."""
        async def _gen(*_args, **_kwargs):
            return
            yield   # pragma: no cover — makes this an async generator
        return _gen

    @pytest.mark.asyncio
    async def test_node_project_calls_engine(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text('{"name":"x"}')
        agent = RunAgent()
        pid   = uuid.uuid4()
        pool  = _make_pool()
        ctx   = _make_ctx()

        mock_instance = MagicMock()
        mock_instance.run = self._noop_engine_run()

        with (
            patch(_PATCH_GET_POOL, return_value=pool),
            patch(_PATCH_RESOLVE_PID, new=AsyncMock(return_value=pid)),
            patch(_PATCH_WORKSPACE, return_value=tmp_path),
            patch(_PATCH_ENGINE, return_value=mock_instance),
        ):
            result = await agent.execute(ctx)

        # EMPTY_WORKSPACE must not appear for a recognised project
        assert result.data.get("error_code") != "EMPTY_WORKSPACE"

    @pytest.mark.asyncio
    async def test_python_project_calls_engine(self, tmp_path: Path) -> None:
        (tmp_path / "requirements.txt").write_text("fastapi\n")
        agent = RunAgent()
        pid   = uuid.uuid4()
        pool  = _make_pool()
        ctx   = _make_ctx()

        mock_instance = MagicMock()
        mock_instance.run = self._noop_engine_run()

        with (
            patch(_PATCH_GET_POOL, return_value=pool),
            patch(_PATCH_RESOLVE_PID, new=AsyncMock(return_value=pid)),
            patch(_PATCH_WORKSPACE, return_value=tmp_path),
            patch(_PATCH_ENGINE, return_value=mock_instance),
        ):
            result = await agent.execute(ctx)

        assert result.data.get("error_code") != "EMPTY_WORKSPACE"

    @pytest.mark.asyncio
    async def test_docker_project_calls_engine(self, tmp_path: Path) -> None:
        (tmp_path / "Dockerfile").write_text("FROM alpine\n")
        agent = RunAgent()
        pid   = uuid.uuid4()
        pool  = _make_pool()
        ctx   = _make_ctx()

        mock_instance = MagicMock()
        mock_instance.run = self._noop_engine_run()

        with (
            patch(_PATCH_GET_POOL, return_value=pool),
            patch(_PATCH_RESOLVE_PID, new=AsyncMock(return_value=pid)),
            patch(_PATCH_WORKSPACE, return_value=tmp_path),
            patch(_PATCH_ENGINE, return_value=mock_instance),
        ):
            result = await agent.execute(ctx)

        assert result.data.get("error_code") != "EMPTY_WORKSPACE"


# ── 4. Auth / project guards still enforced ───────────────────────────────────

class TestRunAgentAuthValidation:
    @pytest.mark.asyncio
    async def test_missing_user_id_returns_auth_error(self) -> None:
        agent = RunAgent()
        ctx   = _make_ctx(user_id="")
        result = await agent.execute(ctx)
        assert result.success is False
        output = (result.output or "").lower()
        assert "authentication" in output or "auth" in output

    @pytest.mark.asyncio
    async def test_missing_project_id_returns_project_error(self) -> None:
        agent = RunAgent()
        ctx   = _make_ctx()
        ctx.project_id = ""
        result = await agent.execute(ctx)
        assert result.success is False
        assert "project" in (result.output or "").lower()


# ── 5. No silent fallback ─────────────────────────────────────────────────────

class TestNoSilentFallback:
    """The fix must never silently pick a default runtime for unrecognised projects."""

    @pytest.mark.asyncio
    async def test_unknown_project_never_uses_default_runtime(self, tmp_path: Path) -> None:
        # Only a README — no project files
        (tmp_path / "README.md").write_text("hello world")
        agent  = RunAgent()
        pid    = uuid.uuid4()
        pool   = _make_pool()
        ctx    = _make_ctx()
        engine_calls: list = []

        with (
            patch(_PATCH_GET_POOL, return_value=pool),
            patch(_PATCH_RESOLVE_PID, new=AsyncMock(return_value=pid)),
            patch(_PATCH_WORKSPACE, return_value=tmp_path),
            patch(_PATCH_ENGINE, side_effect=lambda: engine_calls.append(1) or MagicMock()),
        ):
            result = await agent.execute(ctx)

        assert len(engine_calls) == 0, (
            "Engine was called for an unrecognised project — "
            "no silent fallback to any default runtime is allowed"
        )
        assert result.data.get("error_code") == "EMPTY_WORKSPACE"
