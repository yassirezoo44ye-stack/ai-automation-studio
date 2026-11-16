"""Unit tests for approval gating and targeted retries."""
import pytest

from app.business_launch.workflow import LaunchState, Stage, advance, retry_stage


def test_sequential_stages():
    state = LaunchState()
    for expected in (
        Stage.FEASIBILITY, Stage.BRAND, Stage.CATALOG,
        Stage.LAUNCH_PACKAGE, Stage.PENDING_APPROVAL,
    ):
        state = advance(state)
        assert state.stage == expected
        assert not state.approved


def test_approval_required():
    with pytest.raises(PermissionError):
        advance(LaunchState(Stage.PENDING_APPROVAL))


def test_approval_only_at_gate():
    with pytest.raises(ValueError):
        advance(LaunchState(), approved_by_owner=True)


def test_explicit_approval():
    state = advance(LaunchState(Stage.PENDING_APPROVAL), approved_by_owner=True)
    assert state == LaunchState(Stage.APPROVED, approved=True)
    assert advance(state) == state


def test_retry_only_current_stage():
    state = LaunchState(Stage.CATALOG)
    assert retry_stage(state, Stage.CATALOG) == state
    with pytest.raises(ValueError):
        retry_stage(state, Stage.FEASIBILITY)
    with pytest.raises(ValueError):
        retry_stage(LaunchState(Stage.APPROVED, True), Stage.APPROVED)
