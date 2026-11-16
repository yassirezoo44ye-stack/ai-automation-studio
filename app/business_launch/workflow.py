"""Pure, approval-gated business launch workflow.

No deployment, payment, or outbound communication is performed here.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Stage(str, Enum):
    IDEA = "IDEA"
    FEASIBILITY = "FEASIBILITY"
    BRAND = "BRAND"
    CATALOG = "CATALOG"
    LAUNCH_PACKAGE = "LAUNCH_PACKAGE"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"


ORDER = (
    Stage.IDEA, Stage.FEASIBILITY, Stage.BRAND,
    Stage.CATALOG, Stage.LAUNCH_PACKAGE, Stage.PENDING_APPROVAL,
)


@dataclass(frozen=True)
class LaunchState:
    stage: Stage = Stage.IDEA
    approved: bool = False


def advance(state: LaunchState, *, approved_by_owner: bool = False) -> LaunchState:
    """Advance exactly one stage; explicit approval required at final gate."""
    if state.stage == Stage.APPROVED:
        return state
    if state.stage == Stage.PENDING_APPROVAL:
        if not approved_by_owner:
            raise PermissionError("Owner approval required")
        return LaunchState(stage=Stage.APPROVED, approved=True)
    if approved_by_owner:
        raise ValueError("Approval is only valid at the review gate")
    index = ORDER.index(state.stage)
    return LaunchState(stage=ORDER[index + 1])


def retry_stage(state: LaunchState, failed_stage: Stage) -> LaunchState:
    """Return the same stage for a targeted retry; never replay earlier stages."""
    if state.stage != failed_stage or state.stage == Stage.APPROVED:
        raise ValueError("Only the current unapproved stage can be retried")
    return state
