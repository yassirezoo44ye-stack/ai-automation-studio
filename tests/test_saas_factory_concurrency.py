"""
SaaS Factory — concurrency guard + metrics tests.

Covers F-1 (bulkhead) and F-7 (active-pipeline gauge / total counter).

No live Postgres — pool/conn are mocked (same pattern as existing pipeline tests).
No live event loop across tests — each test uses asyncio.new_event_loop() via the
run() helper so state is fully isolated.
"""
from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.reliability import BulkheadFull
from app.core.observability.metrics import get_metrics


# ── helpers ───────────────────────────────────────────────────────────────────

def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _mock_pool(conn: AsyncMock) -> MagicMock:
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool


def _make_pipeline(pool: MagicMock, max_active: int = 4):
    """Bypass __init__ the same way existing tests do, but also set the new attrs."""
    from app.saas_factory.pipeline import SaasFactoryPipeline
    p = SaasFactoryPipeline.__new__(SaasFactoryPipeline)
    p._pool = pool
    p._gw = MagicMock()
    p._active = 0
    p._max_active = max_active
    return p


def _patch_create_task():
    """Suppress 'coroutine never awaited' warnings by closing the coro immediately."""
    return patch(
        "asyncio.create_task",
        side_effect=lambda coro, **kw: (coro.close(), MagicMock())[1],
    )


ORG  = str(uuid.uuid4())
USER = str(uuid.uuid4())
PROJ = str(uuid.uuid4())


# ── F-1: BulkheadFull raised at limit ─────────────────────────────────────────

class TestConcurrencyGuardStart:

    def test_raises_bulkhead_full_when_at_limit(self):
        conn = AsyncMock()
        conn.execute = AsyncMock()
        pipeline = _make_pipeline(_mock_pool(conn), max_active=2)
        pipeline._active = 2  # already at limit

        with pytest.raises(BulkheadFull) as exc_info:
            run(pipeline.start(PROJ, ORG, USER, "test idea"))

        assert exc_info.value.name == "saas_factory"
        assert exc_info.value.limit == 2

    def test_slot_not_leaked_when_db_raises(self):
        conn = AsyncMock()
        conn.execute = AsyncMock(side_effect=RuntimeError("db error"))
        pipeline = _make_pipeline(_mock_pool(conn), max_active=4)

        with pytest.raises(RuntimeError, match="db error"):
            run(pipeline.start(PROJ, ORG, USER, "test idea"))

        assert pipeline._active == 0, "slot must be released when DB raises before task spawn"

    def test_slot_incremented_after_successful_start(self):
        conn = AsyncMock()
        conn.execute = AsyncMock()
        pipeline = _make_pipeline(_mock_pool(conn), max_active=4)

        with _patch_create_task():
            run(pipeline.start(PROJ, ORG, USER, "test idea"))

        # After successful create_task, the task owns the slot — _active stays at 1
        # until the guarded wrapper finishes (which won't happen here since create_task
        # is patched to close the coro). The slot is incremented and stays there.
        assert pipeline._active == 1

    def test_below_limit_succeeds(self):
        conn = AsyncMock()
        conn.execute = AsyncMock()
        pipeline = _make_pipeline(_mock_pool(conn), max_active=2)
        pipeline._active = 1  # one slot taken

        with _patch_create_task():
            run(pipeline.start(PROJ, ORG, USER, "test idea"))

        assert pipeline._active == 2


class TestConcurrencyGuardResume:

    def _row(self, phase="FAILED"):
        row = MagicMock()
        row.__getitem__ = lambda self, k: {
            "phase": phase,
            "checkpoint": "{}",
            "idea_text": "original idea",
        }[k]
        return row

    def test_raises_bulkhead_full_when_at_limit(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=self._row())
        conn.execute = AsyncMock()
        pipeline = _make_pipeline(_mock_pool(conn), max_active=2)
        pipeline._active = 2

        with pytest.raises(BulkheadFull):
            run(pipeline.resume(PROJ, ORG, USER))

    def test_slot_not_leaked_when_create_task_raises(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=self._row())
        conn.execute = AsyncMock()
        pipeline = _make_pipeline(_mock_pool(conn), max_active=4)

        with patch("asyncio.create_task", side_effect=RuntimeError("no event loop")):
            with pytest.raises(RuntimeError):
                run(pipeline.resume(PROJ, ORG, USER))

        assert pipeline._active == 0, "slot must be released when create_task raises"


class TestConcurrencyGuardApprove:

    def _row(self):
        row = MagicMock()
        row.__getitem__ = lambda self, k: {
            "phase": "PENDING_REVIEW",
            "checkpoint": '{"VERIFYING": {"overall": "warn"}}',
            "idea_text": "original idea",
        }[k]
        return row

    def test_raises_bulkhead_full_when_at_limit(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=self._row())
        conn.execute = AsyncMock(return_value="UPDATE 1")
        pipeline = _make_pipeline(_mock_pool(conn), max_active=2)
        pipeline._active = 2

        with pytest.raises(BulkheadFull):
            run(pipeline.approve(PROJ, ORG, USER))

    def test_slot_and_db_reverted_when_create_task_raises(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=self._row())
        conn.execute = AsyncMock(return_value="UPDATE 1")
        pipeline = _make_pipeline(_mock_pool(conn), max_active=4)

        with patch("asyncio.create_task", side_effect=RuntimeError("no event loop")):
            with pytest.raises(RuntimeError, match="Deployment task could not be launched"):
                run(pipeline.approve(PROJ, ORG, USER))

        assert pipeline._active == 0, "slot must be released on create_task failure"
        # DB revert execute was called (the last execute after the failure)
        assert conn.execute.call_count >= 2

    def test_db_reverted_to_pending_review_when_bulkhead_full(self):
        """Phase must revert from DEPLOYING→PENDING_REVIEW when BulkheadFull fires."""
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=self._row())
        conn.execute = AsyncMock(return_value="UPDATE 1")
        pipeline = _make_pipeline(_mock_pool(conn), max_active=2)
        pipeline._active = 2

        with pytest.raises(BulkheadFull):
            run(pipeline.approve(PROJ, ORG, USER))

        # execute[0]: phase→DEPLOYING; execute[1]: phase→PENDING_REVIEW (revert)
        assert conn.execute.call_count == 2

    def test_bulkhead_full_reraises_as_bulkhead_full_not_runtime_error(self):
        """BulkheadFull must not be wrapped in RuntimeError — 503 mapping depends on it."""
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=self._row())
        conn.execute = AsyncMock(return_value="UPDATE 1")
        pipeline = _make_pipeline(_mock_pool(conn), max_active=2)
        pipeline._active = 2

        with pytest.raises(BulkheadFull) as exc_info:
            run(pipeline.approve(PROJ, ORG, USER))

        assert exc_info.value.name == "saas_factory"

    def test_db_revert_failure_does_not_swallow_bulkhead_full(self):
        """If the DB revert itself fails, BulkheadFull must still propagate."""
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=self._row())
        # First call: UPDATE 1 (phase→DEPLOYING); second call: revert fails
        conn.execute = AsyncMock(side_effect=["UPDATE 1", RuntimeError("revert db error")])
        pipeline = _make_pipeline(_mock_pool(conn), max_active=2)
        pipeline._active = 2

        with pytest.raises(BulkheadFull):
            run(pipeline.approve(PROJ, ORG, USER))


# ── F-7: metrics gauge + counter ──────────────────────────────────────────────

class TestPipelineMetrics:

    def test_active_gauge_pre_registered(self):
        m = get_metrics()
        gauge = m.gauge("saas_factory_active_pipelines", "")
        assert gauge.name == "saas_factory_active_pipelines"

    def test_total_counter_pre_registered(self):
        m = get_metrics()
        ctr = m.counter("saas_factory_pipelines_total", "")
        assert ctr.name == "saas_factory_pipelines_total"

    def test_reserve_increments_gauge_and_counter(self):
        conn = AsyncMock()
        pipeline = _make_pipeline(_mock_pool(conn), max_active=4)
        m = get_metrics()
        gauge = m.gauge("saas_factory_active_pipelines", "")
        ctr   = m.counter("saas_factory_pipelines_total", "")
        before_gauge = gauge.value
        before_ctr   = ctr.value

        pipeline._reserve_slot()

        assert gauge.value == before_gauge + 1
        assert ctr.value   == before_ctr + 1

    def test_release_decrements_gauge(self):
        conn = AsyncMock()
        pipeline = _make_pipeline(_mock_pool(conn), max_active=4)
        pipeline._active = 1
        m = get_metrics()
        gauge = m.gauge("saas_factory_active_pipelines", "")
        gauge.set(1)

        pipeline._release_slot()

        assert pipeline._active == 0
        assert gauge.value == 0

    def test_release_does_not_go_negative(self):
        conn = AsyncMock()
        pipeline = _make_pipeline(_mock_pool(conn), max_active=4)
        pipeline._active = 0

        pipeline._release_slot()  # must not raise or go below 0

        assert pipeline._active == 0

    def test_gauge_updated_on_successful_start(self):
        conn = AsyncMock()
        conn.execute = AsyncMock()
        pipeline = _make_pipeline(_mock_pool(conn), max_active=4)
        m = get_metrics()
        gauge = m.gauge("saas_factory_active_pipelines", "")
        gauge.set(0)

        with _patch_create_task():
            run(pipeline.start(PROJ, ORG, USER, "test idea"))

        assert gauge.value == 1

    def test_prometheus_text_includes_saas_factory_metrics(self):
        m = get_metrics()
        text = m.prometheus_text()
        assert "saas_factory_active_pipelines" in text
        assert "saas_factory_pipelines_total" in text


# ── F-1: _run_pipeline_guarded releases slot on completion ───────────────────

class TestRunPipelineGuardedReleasesSlot:

    def test_slot_released_on_normal_exit(self):
        conn = AsyncMock()
        pipeline = _make_pipeline(_mock_pool(conn), max_active=4)
        pipeline._active = 1

        async def fast_run(*a, **kw):
            pass

        pipeline._run_pipeline = fast_run

        run(pipeline._run_pipeline_guarded(PROJ, ORG, USER, "idea"))

        assert pipeline._active == 0

    def test_slot_released_even_when_pipeline_raises(self):
        conn = AsyncMock()
        pipeline = _make_pipeline(_mock_pool(conn), max_active=4)
        pipeline._active = 1

        async def failing_run(*a, **kw):
            raise RuntimeError("phase error")

        pipeline._run_pipeline = failing_run

        with pytest.raises(RuntimeError, match="phase error"):
            run(pipeline._run_pipeline_guarded(PROJ, ORG, USER, "idea"))

        assert pipeline._active == 0


# ── F-1: resume() ordering — reserve-before-update ───────────────────────────

class TestConcurrencyGuardResumeOrdering:
    """_reserve_slot() must precede the DB phase UPDATE so BulkheadFull never mutates DB."""

    def _row(self, phase="FAILED"):
        row = MagicMock()
        row.__getitem__ = lambda self, k: {
            "phase": phase,
            "checkpoint": "{}",
            "idea_text": "original idea",
        }[k]
        return row

    def test_db_not_updated_when_bulkhead_full(self):
        """Phase UPDATE must NOT be called when BulkheadFull is raised."""
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=self._row())
        conn.execute = AsyncMock()
        pipeline = _make_pipeline(_mock_pool(conn), max_active=2)
        pipeline._active = 2

        with pytest.raises(BulkheadFull):
            run(pipeline.resume(PROJ, ORG, USER))

        conn.execute.assert_not_called()

    def test_slot_released_when_db_update_raises(self):
        """Slot acquired before the DB update must be released when the update fails."""
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=self._row())
        conn.execute = AsyncMock(side_effect=RuntimeError("db error"))
        pipeline = _make_pipeline(_mock_pool(conn), max_active=4)

        with pytest.raises(RuntimeError, match="db error"):
            run(pipeline.resume(PROJ, ORG, USER))

        assert pipeline._active == 0

    def test_no_double_release_after_task_spawned(self):
        """When create_task succeeds, _active stays at 1 — task owns the slot."""
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=self._row())
        conn.execute = AsyncMock()
        pipeline = _make_pipeline(_mock_pool(conn), max_active=4)

        with _patch_create_task():
            run(pipeline.resume(PROJ, ORG, USER))

        assert pipeline._active == 1

    def test_normal_resume_returns_result_and_updates_db(self):
        """Happy path: DB updated once, slot at 1, result returned."""
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=self._row())
        conn.execute = AsyncMock()
        pipeline = _make_pipeline(_mock_pool(conn), max_active=4)

        with _patch_create_task():
            result = run(pipeline.resume(PROJ, ORG, USER))

        assert result["project_id"] == PROJ
        assert "resumed_from" in result
        assert pipeline._active == 1
        conn.execute.assert_called_once()
