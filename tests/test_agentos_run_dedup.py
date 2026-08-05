"""
POST /api/agentos/run's run_id-based deduplication — regression tests.
Matches tests/test_agent_deliverables.py's TestAgentOsEndpointsResolveVerifiedUserId
mocking conventions (MagicMock kernel, AsyncMock kernel.run, patched
optional_user_id/optional_org_id).
"""
from __future__ import annotations

import sys
import unittest
import unittest.mock
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import HTTPException

import app.agents.kernel as kernel_mod
from app.routers.agent_os_api import RunRequest, agentos_run


class FakeGuard:
    def __init__(self, is_replay: bool, cached_result=None):
        self.is_replay     = is_replay
        self.cached_result = cached_result
        self.result        = None


def _fake_idempotent_factory(store: dict, *, raise_on_enter: bool = False, in_progress: bool = False):
    @asynccontextmanager
    async def _fake_idempotent(scope, key, *, pool, ttl_s=86400):
        if raise_on_enter:
            raise RuntimeError("pool unavailable")
        if in_progress:
            from app.core.idempotency import IdempotencyInProgress
            raise IdempotencyInProgress(f"({scope!r}, {key!r}) is already being processed")
        cache_key = (scope, key)
        if cache_key in store:
            yield FakeGuard(is_replay=True, cached_result=store[cache_key])
            return
        guard = FakeGuard(is_replay=False)
        yield guard
        store[cache_key] = guard.result

    return _fake_idempotent


class TestAgentosRunDedup(unittest.IsolatedAsyncioTestCase):
    def _fake_kernel(self, result_dict=None, side_effect=None):
        fake_kernel = MagicMock()
        if side_effect is not None:
            fake_kernel.run = AsyncMock(side_effect=side_effect)
        else:
            fake_result = MagicMock()
            fake_result.to_dict.return_value = result_dict or {"ok": True}
            fake_kernel.run = AsyncMock(return_value=fake_result)
        return fake_kernel

    async def test_no_run_id_bypasses_dedup_entirely(self):
        fake_kernel = self._fake_kernel()
        with patch.object(kernel_mod, "get_agent_kernel", return_value=fake_kernel), \
             patch("app.tenancy.context.optional_user_id", AsyncMock(return_value=None)), \
             patch("app.tenancy.context.optional_org_id", AsyncMock(return_value=None)):
            result = await agentos_run(RunRequest(input="echo hi"), MagicMock())
        self.assertEqual(result, {"ok": True})
        self.assertEqual(fake_kernel.run.call_count, 1)

    async def test_same_run_id_executes_kernel_only_once(self):
        fake_kernel = self._fake_kernel({"value": 42})
        store: dict = {}
        with patch.object(kernel_mod, "get_agent_kernel", return_value=fake_kernel), \
             patch("app.tenancy.context.optional_user_id", AsyncMock(return_value=None)), \
             patch("app.tenancy.context.optional_org_id", AsyncMock(return_value=None)), \
             patch("app.core.db.get_pool", return_value=object()), \
             patch("app.core.idempotency.idempotent", _fake_idempotent_factory(store)):
            r1 = await agentos_run(RunRequest(input="echo hi", run_id="fixed-run-id"), MagicMock())
            r2 = await agentos_run(RunRequest(input="echo hi", run_id="fixed-run-id"), MagicMock())

        self.assertEqual(r1, {"value": 42})
        self.assertEqual(r2, {"value": 42})
        self.assertEqual(fake_kernel.run.call_count, 1)  # NOT re-executed on replay

    async def test_different_run_ids_both_execute(self):
        fake_kernel = self._fake_kernel()
        store: dict = {}
        with patch.object(kernel_mod, "get_agent_kernel", return_value=fake_kernel), \
             patch("app.tenancy.context.optional_user_id", AsyncMock(return_value=None)), \
             patch("app.tenancy.context.optional_org_id", AsyncMock(return_value=None)), \
             patch("app.core.db.get_pool", return_value=object()), \
             patch("app.core.idempotency.idempotent", _fake_idempotent_factory(store)):
            await agentos_run(RunRequest(input="a", run_id="run-1"), MagicMock())
            await agentos_run(RunRequest(input="b", run_id="run-2"), MagicMock())
        self.assertEqual(fake_kernel.run.call_count, 2)

    async def test_dedup_mechanism_unavailable_fails_closed_503(self):
        """Unlike JobQueue.submit's idempotency_key (fail-open), this must
        refuse rather than risk a silent double-execution of a
        side-effecting agent run."""
        fake_kernel = self._fake_kernel()
        store: dict = {}
        with patch.object(kernel_mod, "get_agent_kernel", return_value=fake_kernel), \
             patch("app.tenancy.context.optional_user_id", AsyncMock(return_value=None)), \
             patch("app.tenancy.context.optional_org_id", AsyncMock(return_value=None)), \
             patch("app.core.db.get_pool", return_value=object()), \
             patch("app.core.idempotency.idempotent",
                   _fake_idempotent_factory(store, raise_on_enter=True)):
            with self.assertRaises(HTTPException) as ctx:
                await agentos_run(RunRequest(input="echo hi", run_id="run-x"), MagicMock())
        self.assertEqual(ctx.exception.status_code, 503)
        self.assertEqual(fake_kernel.run.call_count, 0)  # never even attempted

    async def test_genuine_concurrent_duplicate_returns_409_not_503(self):
        """A different failure mode than the mechanism-unavailable case
        above: the dedup mechanism worked correctly and detected that
        another call for this exact run_id is still in flight (e.g. a
        double-click). That's not an outage — it must surface as 409, a
        distinct status from the 503 "could not verify" case, so a
        client can tell the two apart."""
        fake_kernel = self._fake_kernel()
        store: dict = {}
        with patch.object(kernel_mod, "get_agent_kernel", return_value=fake_kernel), \
             patch("app.tenancy.context.optional_user_id", AsyncMock(return_value=None)), \
             patch("app.tenancy.context.optional_org_id", AsyncMock(return_value=None)), \
             patch("app.core.db.get_pool", return_value=object()), \
             patch("app.core.idempotency.idempotent",
                   _fake_idempotent_factory(store, in_progress=True)):
            with self.assertRaises(HTTPException) as ctx:
                await agentos_run(RunRequest(input="echo hi", run_id="run-z"), MagicMock())
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(fake_kernel.run.call_count, 0)  # never even attempted

    async def test_real_execution_failure_propagates_unmasked(self):
        """A genuine agent-execution error (not a dedup-mechanism problem)
        must propagate as-is, not get relabeled as a 503 dedup failure."""
        fake_kernel = self._fake_kernel(side_effect=ValueError("agent blew up"))
        store: dict = {}
        with patch.object(kernel_mod, "get_agent_kernel", return_value=fake_kernel), \
             patch("app.tenancy.context.optional_user_id", AsyncMock(return_value=None)), \
             patch("app.tenancy.context.optional_org_id", AsyncMock(return_value=None)), \
             patch("app.core.db.get_pool", return_value=object()), \
             patch("app.core.idempotency.idempotent", _fake_idempotent_factory(store)):
            with self.assertRaises(ValueError):
                await agentos_run(RunRequest(input="echo hi", run_id="run-y"), MagicMock())

    async def test_scope_includes_org_id_so_orgs_do_not_collide(self):
        fake_kernel = self._fake_kernel()
        store: dict = {}
        with patch.object(kernel_mod, "get_agent_kernel", return_value=fake_kernel), \
             patch("app.tenancy.context.optional_user_id", AsyncMock(return_value=None)), \
             patch("app.core.db.get_pool", return_value=object()), \
             patch("app.core.idempotency.idempotent", _fake_idempotent_factory(store)):
            with patch("app.tenancy.context.optional_org_id", AsyncMock(return_value="org-a")):
                await agentos_run(RunRequest(input="a", run_id="shared-id"), MagicMock())
            with patch("app.tenancy.context.optional_org_id", AsyncMock(return_value="org-b")):
                await agentos_run(RunRequest(input="b", run_id="shared-id"), MagicMock())
        self.assertEqual(fake_kernel.run.call_count, 2)  # different orgs, not deduped


if __name__ == "__main__":
    unittest.main()
