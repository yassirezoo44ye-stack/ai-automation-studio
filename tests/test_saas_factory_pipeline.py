"""
SaaS Factory Pipeline — P0 regression tests.

Tests cover:
  P0-1: Build status gate in _phase_testing and resume()
  P0-2: Security verification response validation in _phase_verifying
  P0-3: PENDING_REVIEW gate — warn halts pipeline; approve/reject enforce atomicity

No live Postgres — pool/conn are mocked (same pattern as test_notifications.py).
"""
from __future__ import annotations

import json
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import contextlib


def run(coro):
    import asyncio
    return asyncio.new_event_loop().run_until_complete(coro)


def _mock_pool(conn: AsyncMock) -> MagicMock:
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool


def _make_pipeline(pool: MagicMock):
    from app.saas_factory.pipeline import SaasFactoryPipeline
    p = SaasFactoryPipeline.__new__(SaasFactoryPipeline)
    p._pool = pool
    p._gw = MagicMock()
    p._active = 0
    p._max_active = 4
    return p


# Suppress coroutine warnings from patched create_task by closing the coroutine.
def _patch_create_task():
    return patch(
        "asyncio.create_task",
        side_effect=lambda coro, **kw: coro.close() or MagicMock(),
    )


ORG = str(uuid.uuid4())
OTHER_ORG = str(uuid.uuid4())
USER = str(uuid.uuid4())
REVIEWER = str(uuid.uuid4())
PROJECT = str(uuid.uuid4())
APP_ID = str(uuid.uuid4())


# ── P0-1: _phase_testing build status gate ─────────────────────────────────────

class TestPhaseTestingBuildGate:

    def _cp_with_build(self, build_status: str) -> dict[str, Any]:
        return {
            "IDEA": {"product_name": "TestApp", "key_features": []},
            "BLUEPRINT": {},
            "BUILDING": {"app_id": APP_ID, "app_name": "TestApp", "build_status": build_status},
        }

    def test_raises_when_build_failed(self):
        conn = AsyncMock()
        pipeline = _make_pipeline(_mock_pool(conn))
        cp = self._cp_with_build("failed")
        with pytest.raises(RuntimeError, match="build_failed"):
            run(pipeline._phase_testing(PROJECT, ORG, USER, "idea", cp))

    def test_raises_when_build_timeout(self):
        """Regression: timeout must abort TESTING (raise), not silently skip."""
        conn = AsyncMock()
        pipeline = _make_pipeline(_mock_pool(conn))
        cp = self._cp_with_build("timeout")
        with pytest.raises(RuntimeError, match="build_timeout"):
            run(pipeline._phase_testing(PROJECT, ORG, USER, "idea", cp))

    def test_raises_when_build_partial(self):
        conn = AsyncMock()
        pipeline = _make_pipeline(_mock_pool(conn))
        cp = self._cp_with_build("partial")
        with pytest.raises(RuntimeError, match="build_partial"):
            run(pipeline._phase_testing(PROJECT, ORG, USER, "idea", cp))

    def test_raises_when_build_unknown(self):
        conn = AsyncMock()
        pipeline = _make_pipeline(_mock_pool(conn))
        cp = self._cp_with_build("whatever_unknown")
        with pytest.raises(RuntimeError, match="whatever_unknown"):
            run(pipeline._phase_testing(PROJECT, ORG, USER, "idea", cp))

    def test_proceeds_only_when_build_completed(self):
        """Only 'completed' must allow testing to proceed (calls LLM)."""
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)
        pipeline = _make_pipeline(_mock_pool(conn))
        cp = self._cp_with_build("completed")

        mock_resp = MagicMock()
        mock_resp.content = '{"checks": [], "coverage_pct": 80, "overall": "pass"}'
        pipeline._gw.complete = AsyncMock(return_value=mock_resp)

        result = run(pipeline._phase_testing(PROJECT, ORG, USER, "idea", cp))
        assert result.get("status") != "skipped"
        pipeline._gw.complete.assert_called_once()


# ── P0-1: resume() must not bypass an incomplete build ────────────────────────

class TestResumeCheckpointGate:

    def _make_row(self, phase: str, checkpoint: dict) -> MagicMock:
        row = MagicMock()
        row.__getitem__ = lambda self, k: {
            "id": PROJECT,
            "idea_text": "idea",
            "phase": phase,
            "checkpoint": json.dumps(checkpoint),
        }[k]
        return row

    def _resume(self, checkpoint: dict, phase: str = "FAILED"):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=self._make_row(phase, checkpoint))
        conn.execute = AsyncMock()
        pipeline = _make_pipeline(_mock_pool(conn))

        with _patch_create_task():
            result = run(pipeline.resume(PROJECT, ORG, USER))
        return result, conn

    def test_resume_from_building_when_build_timeout(self):
        """If BUILDING checkpoint has build_status=timeout, resume must re-run BUILDING."""
        cp = {
            "IDEA": {"product_name": "App"},
            "BLUEPRINT": {},
            "BUILDING": {"app_id": APP_ID, "build_status": "timeout"},
        }
        result, conn = self._resume(cp)
        assert result["resumed_from"] == "BUILDING"

    def test_resume_from_building_when_build_partial(self):
        cp = {
            "IDEA": {},
            "BLUEPRINT": {},
            "BUILDING": {"build_status": "partial"},
        }
        result, conn = self._resume(cp)
        assert result["resumed_from"] == "BUILDING"

    def test_resume_from_testing_when_build_completed(self):
        """Completed build — resume must advance past BUILDING to TESTING."""
        cp = {
            "IDEA": {},
            "BLUEPRINT": {},
            "BUILDING": {"app_id": APP_ID, "build_status": "completed"},
        }
        result, conn = self._resume(cp)
        assert result["resumed_from"] == "TESTING"

    def test_resume_rejects_pending_review(self):
        """Regular resume must not bypass PENDING_REVIEW security gate."""
        conn = AsyncMock()
        row = MagicMock()
        row.__getitem__ = lambda self, k: {
            "id": PROJECT,
            "idea_text": "idea",
            "phase": "PENDING_REVIEW",
            "checkpoint": "{}",
        }[k]
        conn.fetchrow = AsyncMock(return_value=row)
        pipeline = _make_pipeline(_mock_pool(conn))

        with pytest.raises(ValueError, match="Cannot resume project in phase"):
            run(pipeline.resume(PROJECT, ORG, USER))


# ── P0-2: _phase_verifying security response validation ───────────────────────

class TestPhaseVerifyingSecurity:

    def _cp(self) -> dict[str, Any]:
        return {
            "IDEA": {"product_name": "App", "key_features": []},
            "BUILDING": {"app_id": APP_ID},
        }

    def _run_verifying(self, llm_content: str) -> Any:
        conn = AsyncMock()
        pipeline = _make_pipeline(_mock_pool(conn))
        mock_resp = MagicMock()
        mock_resp.content = llm_content
        pipeline._gw.complete = AsyncMock(return_value=mock_resp)
        return run(pipeline._phase_verifying(PROJECT, ORG, USER, "idea", self._cp()))

    def test_passes_on_overall_pass(self):
        result = self._run_verifying('{"findings": [], "overall": "pass", "rls_covered": true}')
        assert result["overall"] == "pass"
        assert "_pipeline_pause" not in result

    def test_passes_on_overall_warn(self):
        """warn must set _pipeline_pause but not raise — pipeline runner handles the stop."""
        result = self._run_verifying('{"findings": [{"severity":"warn","area":"auth","note":"ok"}], "overall": "warn", "rls_covered": true}')
        assert result["overall"] == "warn"
        assert result.get("_pipeline_pause") is True

    def test_raises_on_overall_fail(self):
        with pytest.raises(RuntimeError, match="Security verification failed"):
            self._run_verifying('{"findings": [{"severity":"critical","area":"rls","note":"broken"}], "overall": "fail", "rls_covered": false}')

    def test_raises_on_invalid_response_no_overall(self):
        """Regression: previously a missing 'overall' key defaulted to 'pass' silently."""
        with pytest.raises(RuntimeError, match="invalid or unparseable"):
            self._run_verifying('{"findings": [], "rls_covered": true}')

    def test_raises_on_unparseable_response(self):
        """A completely broken LLM response must not pass as 'pass'."""
        with pytest.raises(RuntimeError, match="invalid or unparseable"):
            self._run_verifying("Sorry, I cannot provide a security report for this.")

    def test_raises_on_overall_unknown(self):
        """'unknown' is not in the valid allowlist — must be rejected."""
        with pytest.raises(RuntimeError, match="invalid or unparseable"):
            self._run_verifying('{"findings": [], "overall": "unknown", "rls_covered": true}')

    def test_raises_on_overall_empty_string(self):
        """An empty string for overall is not a valid value — must be rejected."""
        with pytest.raises(RuntimeError, match="invalid or unparseable"):
            self._run_verifying('{"findings": [], "overall": "", "rls_covered": true}')


# ── P0-3: PENDING_REVIEW gate ─────────────────────────────────────────────────

class TestRunPipelineHaltOnWarn:
    """_run_pipeline must set PENDING_REVIEW and stop when _phase_verifying returns warn."""

    def _cp_through_testing(self) -> dict[str, Any]:
        return {
            "IDEA": {"product_name": "App", "key_features": []},
            "BLUEPRINT": {},
            "BUILDING": {"app_id": APP_ID, "build_status": "completed"},
            "TESTING": {"checks": [], "coverage_pct": 80, "overall": "pass"},
        }

    def test_pipeline_sets_pending_review_on_warn(self):
        """warn from _phase_verifying must cause _run_pipeline to set PENDING_REVIEW."""
        conn = AsyncMock()
        conn.execute = AsyncMock()
        pipeline = _make_pipeline(_mock_pool(conn))

        warn_payload = '{"findings": [{"severity":"warn","area":"auth","note":"weak"}], "overall": "warn", "rls_covered": true}'
        mock_resp = MagicMock()
        mock_resp.content = warn_payload
        pipeline._gw.complete = AsyncMock(return_value=mock_resp)

        cp = self._cp_through_testing()
        run(pipeline._run_pipeline(PROJECT, ORG, USER, "idea", checkpoint=cp, start_phase="VERIFYING"))

        execute_calls = [str(c) for c in conn.execute.call_args_list]
        assert any("PENDING_REVIEW" in c for c in execute_calls), \
            "Expected PENDING_REVIEW in execute calls; got: " + str(execute_calls)

    def test_pipeline_saves_checkpoint_before_pending_review(self):
        """Checkpoint with security report must be saved before setting PENDING_REVIEW."""
        saved_checkpoints: list[str] = []

        async def capture_execute(*args, **kwargs):
            sql = str(args[0]) if args else ""
            if "checkpoint" in sql.lower() and "update" in sql.lower() and len(args) > 1 and isinstance(args[1], str):
                # args[1] is the checkpoint JSON
                saved_checkpoints.append(args[1])

        conn = AsyncMock()
        conn.execute = AsyncMock(side_effect=capture_execute)
        pipeline = _make_pipeline(_mock_pool(conn))

        warn_payload = '{"findings": [], "overall": "warn", "rls_covered": true}'
        mock_resp = MagicMock()
        mock_resp.content = warn_payload
        pipeline._gw.complete = AsyncMock(return_value=mock_resp)

        cp = self._cp_through_testing()
        run(pipeline._run_pipeline(PROJECT, ORG, USER, "idea", checkpoint=cp, start_phase="VERIFYING"))

        # At least one checkpoint save must have happened that includes VERIFYING data
        assert any("VERIFYING" in s for s in saved_checkpoints), \
            "VERIFYING checkpoint not saved before PENDING_REVIEW"

    def test_pipeline_does_not_call_deploying_after_warn(self):
        """No deployment phase must run when warn halts the pipeline."""
        conn = AsyncMock()
        conn.execute = AsyncMock()
        pipeline = _make_pipeline(_mock_pool(conn))

        warn_payload = '{"findings": [], "overall": "warn", "rls_covered": true}'
        mock_resp = MagicMock()
        mock_resp.content = warn_payload
        pipeline._gw.complete = AsyncMock(return_value=mock_resp)

        cp = self._cp_through_testing()
        # Spy on _phase_deploying to ensure it's never called
        pipeline._phase_deploying = AsyncMock(return_value={"creation_id": "x"})

        run(pipeline._run_pipeline(PROJECT, ORG, USER, "idea", checkpoint=cp, start_phase="VERIFYING"))

        pipeline._phase_deploying.assert_not_called()

    def test_pipeline_pause_signal_stripped_from_checkpoint(self):
        """_pipeline_pause must not appear in the persisted checkpoint."""
        persisted: list[dict] = []

        async def capture_execute(*args, **kwargs):
            sql = str(args[0]) if args else ""
            if "checkpoint" in sql.lower() and len(args) > 1 and isinstance(args[1], str):
                with contextlib.suppress(Exception):
                    persisted.append(json.loads(args[1]))

        conn = AsyncMock()
        conn.execute = AsyncMock(side_effect=capture_execute)
        pipeline = _make_pipeline(_mock_pool(conn))

        warn_payload = '{"findings": [], "overall": "warn", "rls_covered": true}'
        mock_resp = MagicMock()
        mock_resp.content = warn_payload
        pipeline._gw.complete = AsyncMock(return_value=mock_resp)

        cp = self._cp_through_testing()
        run(pipeline._run_pipeline(PROJECT, ORG, USER, "idea", checkpoint=cp, start_phase="VERIFYING"))

        for saved in persisted:
            verifying_data = saved.get("VERIFYING", {})
            assert "_pipeline_pause" not in verifying_data, \
                "_pipeline_pause leaked into persisted checkpoint"


class TestApproveMethod:
    """approve() must be atomic, verify the saved result, and record the decision."""

    def _make_conn(
        self,
        phase: str = "PENDING_REVIEW",
        verifying_overall: str = "warn",
        update_result: str = "UPDATE 1",
    ) -> AsyncMock:
        cp = {
            "IDEA": {"product_name": "App"},
            "BLUEPRINT": {},
            "BUILDING": {"app_id": APP_ID, "build_status": "completed"},
            "TESTING": {},
            "VERIFYING": {
                "findings": [{"severity": "warn", "area": "auth", "note": "weak"}],
                "overall": verifying_overall,
                "rls_covered": True,
            },
        }
        row = MagicMock()
        row.__getitem__ = lambda self, k: {
            "idea_text": "idea",
            "phase": phase,
            "checkpoint": json.dumps(cp),
        }[k]
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)
        conn.execute = AsyncMock(return_value=update_result)
        return conn

    def test_approve_advances_to_deploying(self):
        conn = self._make_conn()
        pipeline = _make_pipeline(_mock_pool(conn))

        with _patch_create_task():
            result = run(pipeline.approve(PROJECT, ORG, REVIEWER))

        assert result["resumed_from"] == "DEPLOYING"
        assert result["project_id"] == PROJECT

    def test_approve_records_decision_in_checkpoint(self):
        """Approval must save reviewer_user_id and decided_at in checkpoint."""
        saved_cps: list[dict] = []

        conn = self._make_conn()

        async def capture(*args, **kwargs):
            sql = str(args[0]) if args else ""
            if "checkpoint" in sql.lower() and len(args) > 1 and isinstance(args[1], str):
                with contextlib.suppress(Exception):
                    saved_cps.append(json.loads(args[1]))
            return "UPDATE 1"

        conn.execute = AsyncMock(side_effect=capture)
        pipeline = _make_pipeline(_mock_pool(conn))

        with _patch_create_task():
            run(pipeline.approve(PROJECT, ORG, REVIEWER))

        assert saved_cps, "No checkpoint was saved during approve()"
        review = saved_cps[-1].get("_review", {})
        assert review.get("decision") == "approved"
        assert review.get("reviewer_user_id") == REVIEWER
        assert "decided_at" in review

    def test_approve_rejects_wrong_org(self):
        """A project that doesn't exist for this org must raise ValueError."""
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)
        pipeline = _make_pipeline(_mock_pool(conn))

        with pytest.raises(ValueError, match="Project not found"):
            run(pipeline.approve(PROJECT, OTHER_ORG, REVIEWER))

    def test_approve_rejects_wrong_phase(self):
        """approve() must reject projects not in PENDING_REVIEW."""
        conn = self._make_conn(phase="FAILED")
        pipeline = _make_pipeline(_mock_pool(conn))

        with pytest.raises(ValueError, match="not awaiting security review"):
            run(pipeline.approve(PROJECT, ORG, REVIEWER))

    def test_approve_rejects_non_warn_verifying_result(self):
        """approve() must verify the saved VERIFYING result is actually 'warn'."""
        conn = self._make_conn(verifying_overall="pass")
        pipeline = _make_pipeline(_mock_pool(conn))

        with pytest.raises(ValueError, match="not 'warn'"):
            run(pipeline.approve(PROJECT, ORG, REVIEWER))

    def test_approve_rejects_missing_verifying_result(self):
        """approve() must reject if VERIFYING checkpoint has no 'overall'."""
        cp = {
            "IDEA": {},
            "VERIFYING": {},  # no 'overall'
        }
        row = MagicMock()
        row.__getitem__ = lambda self, k: {
            "idea_text": "idea",
            "phase": "PENDING_REVIEW",
            "checkpoint": json.dumps(cp),
        }[k]
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)
        pipeline = _make_pipeline(_mock_pool(conn))

        with pytest.raises(ValueError, match="not 'warn'"):
            run(pipeline.approve(PROJECT, ORG, REVIEWER))

    def test_approve_concurrent_second_call_raises(self):
        """Concurrent approval — second call must fail (UPDATE 0 from WHERE phase check)."""
        conn = self._make_conn(update_result="UPDATE 0")
        pipeline = _make_pipeline(_mock_pool(conn))

        with pytest.raises(ValueError, match="already recorded"):
            run(pipeline.approve(PROJECT, ORG, REVIEWER))

    def test_approve_idempotent_after_success_raises_on_second(self):
        """Re-submitting approve after it succeeded must not start a second deployment."""
        # First call: phase is PENDING_REVIEW, update succeeds
        # Second call: phase is now DEPLOYING (not PENDING_REVIEW), so it raises
        conn_second = self._make_conn(phase="DEPLOYING")
        pipeline = _make_pipeline(_mock_pool(conn_second))

        with pytest.raises(ValueError, match="not awaiting security review"):
            run(pipeline.approve(PROJECT, ORG, REVIEWER))

    def test_approve_task_launch_failure_reverts_to_pending_review(self):
        """If create_task raises, phase must revert to PENDING_REVIEW."""
        revert_calls: list[str] = []

        async def capture_execute(*args, **kwargs):
            sql = str(args[0]) if args else ""
            if "PENDING_REVIEW" in sql:
                revert_calls.append(sql)
            return "UPDATE 1"

        conn = self._make_conn()
        conn.execute = AsyncMock(side_effect=capture_execute)
        pipeline = _make_pipeline(_mock_pool(conn))

        with patch("asyncio.create_task", side_effect=RuntimeError("event loop gone")):
            with pytest.raises(RuntimeError, match="Deployment task could not be launched"):
                run(pipeline.approve(PROJECT, ORG, REVIEWER))

        assert any("PENDING_REVIEW" in c for c in revert_calls), \
            "Phase was not reverted to PENDING_REVIEW after task launch failure"

    def test_approve_does_not_rerun_building(self):
        """After approval, no DB write must mention phase=BUILDING — pipeline resumes from DEPLOYING."""
        conn = self._make_conn()
        pipeline = _make_pipeline(_mock_pool(conn))

        with _patch_create_task():
            result = run(pipeline.approve(PROJECT, ORG, REVIEWER))

        assert result["resumed_from"] == "DEPLOYING"
        execute_calls = [str(c) for c in conn.execute.call_args_list]
        assert not any("'BUILDING'" in c for c in execute_calls), \
            "Unexpected write to BUILDING phase after approval"


class TestRejectMethod:

    def _make_conn(self, phase: str = "PENDING_REVIEW", update_result: str = "UPDATE 1") -> AsyncMock:
        cp = {
            "VERIFYING": {"findings": [], "overall": "warn", "rls_covered": True},
        }
        row = MagicMock()
        row.__getitem__ = lambda self, k: {
            "phase": phase,
            "checkpoint": json.dumps(cp),
        }[k]
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)
        conn.execute = AsyncMock(return_value=update_result)
        return conn

    def test_reject_sets_failed(self):
        conn = self._make_conn()
        pipeline = _make_pipeline(_mock_pool(conn))
        result = run(pipeline.reject(PROJECT, ORG, REVIEWER, reason="Auth bypass found"))
        assert result["status"] == "rejected"

    def test_reject_records_decision_in_checkpoint(self):
        saved_cps: list[dict] = []

        conn = self._make_conn()

        async def capture(*args, **kwargs):
            sql = str(args[0]) if args else ""
            if "checkpoint" in sql.lower() and len(args) > 1 and isinstance(args[1], str):
                with contextlib.suppress(Exception):
                    saved_cps.append(json.loads(args[1]))
            return "UPDATE 1"

        conn.execute = AsyncMock(side_effect=capture)
        pipeline = _make_pipeline(_mock_pool(conn))
        run(pipeline.reject(PROJECT, ORG, REVIEWER, reason="Auth bypass found"))

        assert saved_cps
        review = saved_cps[-1].get("_review", {})
        assert review.get("decision") == "rejected"
        assert review.get("reviewer_user_id") == REVIEWER
        assert review.get("reason") == "Auth bypass found"

    def test_reject_wrong_phase_raises(self):
        conn = self._make_conn(phase="FAILED")
        pipeline = _make_pipeline(_mock_pool(conn))
        with pytest.raises(ValueError, match="not awaiting security review"):
            run(pipeline.reject(PROJECT, ORG, REVIEWER))

    def test_reject_concurrent_second_call_raises(self):
        conn = self._make_conn(update_result="UPDATE 0")
        pipeline = _make_pipeline(_mock_pool(conn))
        with pytest.raises(ValueError, match="already recorded"):
            run(pipeline.reject(PROJECT, ORG, REVIEWER))

    def test_reject_wrong_org_raises(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)
        pipeline = _make_pipeline(_mock_pool(conn))
        with pytest.raises(ValueError, match="Project not found"):
            run(pipeline.reject(PROJECT, OTHER_ORG, REVIEWER))


class TestSecurityPolicyIntegrity:
    """pass / fail / invalid overall preserve their original security behavior."""

    def _run_verifying(self, llm_content: str) -> Any:
        conn = AsyncMock()
        pipeline = _make_pipeline(_mock_pool(conn))
        mock_resp = MagicMock()
        mock_resp.content = llm_content
        pipeline._gw.complete = AsyncMock(return_value=mock_resp)
        cp = {
            "IDEA": {"product_name": "App", "key_features": []},
            "BUILDING": {"app_id": APP_ID},
        }
        return run(pipeline._phase_verifying(PROJECT, ORG, USER, "idea", cp))

    def test_pass_allows_continuation_with_no_pause(self):
        result = self._run_verifying('{"findings": [], "overall": "pass", "rls_covered": true}')
        assert result["overall"] == "pass"
        assert "_pipeline_pause" not in result

    def test_fail_blocks_immediately(self):
        with pytest.raises(RuntimeError, match="Security verification failed"):
            self._run_verifying('{"findings": [{"severity":"critical","area":"rls","note":"broken"}], "overall": "fail", "rls_covered": false}')

    def test_invalid_overall_blocks_immediately(self):
        with pytest.raises(RuntimeError, match="invalid or unparseable"):
            self._run_verifying('{"findings": [], "overall": "danger", "rls_covered": true}')

    def test_none_overall_blocks_immediately(self):
        with pytest.raises(RuntimeError, match="invalid or unparseable"):
            self._run_verifying('{"findings": [], "rls_covered": true}')


# ── P2: build failure stops pipeline (does not reach VERIFYING/DEPLOYING/LIVE) ─

class TestBuildFailureStopsPipeline:
    """P2 — a non-completed build must mark the project FAILED and not
    allow the pipeline to proceed past TESTING to VERIFYING, DEPLOYING or LIVE."""

    def _run_pipeline_with_build(self, build_status: str) -> list[str]:
        """Run _run_pipeline from TESTING with a given build_status.
        Returns the list of phase strings passed to _set_phase."""
        conn = AsyncMock()
        conn.execute = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)
        pool = _mock_pool(conn)
        pipeline = _make_pipeline(pool)

        phases_set: list[str] = []

        async def fake_set_phase(project_id, org_id, phase):
            phases_set.append(phase)

        async def fake_save_checkpoint(project_id, org_id, cp):
            pass

        async def fake_fail(project_id, org_id, message):
            phases_set.append("FAILED")

        pipeline._set_phase = fake_set_phase
        pipeline._save_checkpoint = fake_save_checkpoint
        pipeline._fail = fake_fail

        checkpoint = {
            "IDEA":      {"product_name": "App", "key_features": []},
            "BLUEPRINT": {"user_stories": []},
            "BUILDING":  {"app_id": APP_ID, "app_name": "App",
                          "build_status": build_status},
        }

        run(pipeline._run_pipeline(
            PROJECT, ORG, USER, "idea",
            checkpoint=checkpoint,
            start_phase="TESTING",
        ))
        return phases_set

    def test_failed_build_marks_project_failed(self):
        phases = self._run_pipeline_with_build("failed")
        assert "FAILED" in phases
        assert "VERIFYING" not in phases
        assert "DEPLOYING" not in phases
        assert "LIVE" not in phases

    def test_timeout_build_marks_project_failed(self):
        phases = self._run_pipeline_with_build("timeout")
        assert "FAILED" in phases
        assert "VERIFYING" not in phases
        assert "DEPLOYING" not in phases

    def test_partial_build_marks_project_failed(self):
        phases = self._run_pipeline_with_build("partial")
        assert "FAILED" in phases
        assert "VERIFYING" not in phases


# ── P3: _poll_app_build returns timeout after exceeding the time limit ──────────

class TestPollAppBuildTimeout:
    """P3 — _poll_app_build must return 'timeout' when no terminal status
    is reached within the configured limit, and must not loop forever."""

    def test_returns_timeout_when_limit_exceeded(self):
        import asyncio

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)
        pool = _mock_pool(conn)
        pipeline = _make_pipeline(pool)

        sleep_calls: list[float] = []

        async def fake_sleep(n):
            sleep_calls.append(n)

        async def run_poll():
            with patch("asyncio.sleep", fake_sleep):
                return await pipeline._poll_app_build(
                    APP_ID, ORG, timeout=15
                )

        result = asyncio.new_event_loop().run_until_complete(run_poll())
        assert result == "timeout"
        total_slept = sum(sleep_calls)
        assert total_slept >= 15, f"Expected ≥15s slept, got {total_slept}"

    def test_returns_completed_before_timeout(self):
        import asyncio

        completed_row = MagicMock()
        completed_row.__getitem__ = lambda self, k: "completed"
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=completed_row)
        pool = _mock_pool(conn)
        pipeline = _make_pipeline(pool)

        async def fake_sleep(n):
            pass

        async def run_poll():
            with patch("asyncio.sleep", fake_sleep):
                return await pipeline._poll_app_build(
                    APP_ID, ORG, timeout=600
                )

        result = asyncio.new_event_loop().run_until_complete(run_poll())
        assert result == "completed"
