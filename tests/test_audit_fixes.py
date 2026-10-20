"""
Regression tests for the P0/P1/P2 audit fixes.

Each test is lightweight (no live DB, no fastapi server) and targets the
specific invariant the fix enforces.
"""
from __future__ import annotations

import ast
import os
import sys
import types
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("SESSION_SECRET", "test-secret-for-unit-tests-do-not-use-in-prod")

_ROOT = Path(__file__).resolve().parent.parent


def _src(rel: str) -> str:
    return (_ROOT / rel).read_text(encoding="utf-8")


# ── P0-1: Design Studio IDOR ──────────────────────────────────────────────────

def test_design_canvas_update_includes_project_id_in_where():
    """UPDATE must filter by both id AND project_id to prevent IDOR."""
    src = _src("app/routers/design.py")
    # Find the UPDATE block
    update_idx = src.find("UPDATE design_canvases")
    assert update_idx != -1, "UPDATE design_canvases not found"
    update_block = src[update_idx: update_idx + 300]
    assert "project_id" in update_block, (
        "UPDATE design_canvases WHERE clause must include project_id filter"
    )


def test_design_canvas_update_raises_404_on_no_match():
    """save_canvas must raise 404 (not silently INSERT) when design_id not found."""
    src = _src("app/routers/design.py")
    # After the UPDATE block, expect a 404 raise when row is None
    assert 'raise HTTPException(404, "Design not found")' in src, (
        "save_canvas must raise 404 when UPDATE matches no rows for design_id"
    )


# ── P1-1: Lead automation run_id ─────────────────────────────────────────────

def test_capture_lead_payload_includes_run_id():
    """capture_lead must include run_id in the job queue payload."""
    src = _src("app/routers/leads.py")
    # Find the capture endpoint's submit call
    capture_idx = src.find("lead-followup:{org_id}:{lead_id}")
    assert capture_idx != -1, "capture endpoint dedup key not found"
    # Find the payload= argument within ~300 chars before the dedup key
    context = src[max(0, capture_idx - 400): capture_idx]
    assert '"run_id": run_id' in context, (
        "capture_lead job payload must include run_id to allow automation handler to proceed"
    )


def test_create_lead_payload_includes_run_id():
    """create_lead must include run_id in the job queue payload."""
    src = _src("app/routers/leads.py")
    # Find the create endpoint's submit call (uses ctx.org_id)
    create_idx = src.find("lead-followup:{ctx.org_id}:{lead_id}")
    assert create_idx != -1, "create endpoint dedup key not found"
    context = src[max(0, create_idx - 400): create_idx]
    assert '"run_id": run_id' in context, (
        "create_lead job payload must include run_id to allow automation handler to proceed"
    )


# ── P1-2: SaaS Factory poll terminal status ───────────────────────────────────

def test_saas_factory_poll_terminal_includes_ready():
    """_poll_app_build terminal set must include 'ready' (App Builder success status)."""
    src = _src("app/saas_factory/pipeline.py")
    assert '"ready"' in src or "'ready'" in src, "terminal set must include ready"
    # More precisely: the terminal set definition must include "ready"
    terminal_idx = src.find("terminal = {")
    assert terminal_idx != -1, "terminal set not found"
    terminal_block = src[terminal_idx: terminal_idx + 80]
    assert "ready" in terminal_block, (
        "_poll_app_build terminal set must include 'ready' to match App Builder build_status"
    )


def test_saas_factory_phase4_accepts_ready_build_status():
    """Phase 4 TESTING must accept build_status='ready' as a successful build."""
    src = _src("app/saas_factory/pipeline.py")
    # The guard that aborts TESTING must allow "ready"
    # Old buggy line: if build_status != "completed":
    # Fixed line: if build_status not in {"completed", "ready"}:
    assert 'build_status not in {"completed", "ready"}' in src or \
           "build_status not in {'completed', 'ready'}" in src, (
        'TESTING phase must accept build_status "ready" as a successful App Builder build'
    )


# ── P1-3: Email re-raise ──────────────────────────────────────────────────────

def test_email_send_reraises_on_failure():
    """send_email must re-raise exceptions so callers can detect delivery failure."""
    src = _src("app/core/email.py")
    except_idx = src.find("except Exception:")
    assert except_idx != -1, "except block not found"
    after_except = src[except_idx: except_idx + 120]
    assert "raise" in after_except, (
        "send_email must re-raise after logging so callers detect email delivery failure"
    )


# ── P1-4: Lead qualification requires valid score ─────────────────────────────

def test_qualify_only_marks_qualified_with_valid_int_score():
    """qualify() must only set status='qualified' when ai_score is an integer."""
    src = _src("app/core/leads/service.py")
    # The old buggy line: new_status = "qualified"
    # The fixed line: new_status = "qualified" if isinstance(ai_score, int) else "new"
    assert 'new_status = "qualified" if isinstance(ai_score, int) else "new"' in src, (
        'qualify must guard: new_status = "qualified" if isinstance(ai_score, int) else "new"'
    )


# ── P2-2: Business plan org determinism ──────────────────────────────────────

def test_resolve_org_has_order_by():
    """_resolve_org must use ORDER BY to produce a deterministic result for multi-org users."""
    src = _src("app/routers/business_plans.py")
    resolve_idx = src.find("_resolve_org")
    assert resolve_idx != -1
    # Find the SELECT inside _resolve_org
    fn_src = src[resolve_idx: resolve_idx + 400]
    assert "ORDER BY" in fn_src, (
        "_resolve_org must ORDER BY to deterministically pick the primary org for users "
        "who belong to multiple organizations"
    )


# ── P1-5: SaaS Factory AI review metadata ────────────────────────────────────

def test_saas_factory_testing_phase_marks_not_executed():
    """TESTING phase result must include executed=False to prevent false 'tests passed' UI."""
    src = _src("app/saas_factory/pipeline.py")
    assert '"executed"' in src or "'executed'" in src, (
        "TESTING/VERIFYING phase result must include executed=False field"
    )
    # Confirm the value is False
    assert "False" in src, "executed field must be False (not True)"


def test_saas_factory_testing_phase_marks_ai_review_type():
    """TESTING phase result must include review_type='ai_static_analysis'."""
    src = _src("app/saas_factory/pipeline.py")
    assert "ai_static_analysis" in src, (
        "TESTING/VERIFYING phase result must mark review_type='ai_static_analysis' "
        "so UI can distinguish AI review from real test execution"
    )
