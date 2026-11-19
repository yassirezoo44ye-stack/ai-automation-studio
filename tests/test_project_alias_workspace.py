"""The "demo"/"copilot" aliases map to each caller's own workspace.

resolve_project_id turns "demo" into the caller's own project, but the
handlers used the raw string for the workspace and process key, so every
user's "demo" files, runs and preview server shared WORKSPACES/demo.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("SESSION_SECRET", "test-secret-for-unit-tests-do-not-use-in-prod")

from app.routers import build as build_mod


def _pool():
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool


def test_owner_check_returns_the_resolved_project_id():
    resolved = uuid.uuid4()
    with patch.object(build_mod, "get_pool", return_value=_pool()), \
         patch.object(build_mod, "owner_user_id", AsyncMock(return_value=uuid.uuid4())), \
         patch.object(build_mod, "resolve_project_id", AsyncMock(return_value=resolved)):
        got = asyncio.run(build_mod._require_project_owner("demo", MagicMock()))
    assert got == str(resolved)
    assert got != "demo"


def test_two_users_demo_aliases_get_different_workspaces():
    a, b = uuid.uuid4(), uuid.uuid4()
    results = []
    for resolved in (a, b):
        with patch.object(build_mod, "get_pool", return_value=_pool()), \
             patch.object(build_mod, "owner_user_id", AsyncMock(return_value=uuid.uuid4())), \
             patch.object(build_mod, "resolve_project_id", AsyncMock(return_value=resolved)):
            results.append(asyncio.run(build_mod._require_project_owner("demo", MagicMock())))
    assert build_mod.workspace(results[0]) != build_mod.workspace(results[1])
