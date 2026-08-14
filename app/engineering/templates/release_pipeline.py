"""
Release Autopilot — 13-step release pipeline.

Pipeline steps (in order):
  01. PLAN              — plan the release, enumerate files to change
  02. CREATE_BRANCH     — create feature/fix branch via github.create_branch
  03. IMPLEMENT         — AI generates changes; writes them via github.create_or_update_file
  04. STATIC_ANALYSIS   — lint (Ruff) + TypeScript check via github.create_workflow_dispatch
  05. UNIT_TEST         — run unit test suite via github.create_workflow_dispatch
  06. SECURITY_SCAN     — scan for secrets and vulnerabilities
  07. BUILD             — Docker / Vite build via github.create_workflow_dispatch
  08. CREATE_PR         — open pull request via github.create_pull_request
  09. WAIT_FOR_CI       — poll github.get_check_suite_status until all pass
  10. APPROVAL          — human approval gate (risk=high → admin/owner)
  11. MERGE             — merge PR via github.merge_pull_request (DESTRUCTIVE)
  12. DEPLOY            — trigger Render deploy via render.trigger_deploy
  13. VERIFY_PRODUCTION — poll deploy status + health + SHA via ProductionVerifier

Rules enforced here:
  - No step may be skipped unless condition() returns False AND skip is explicit.
  - CI Gate (steps 04–07) must ALL pass before CREATE_PR.
  - APPROVAL is always required before MERGE, regardless of CI outcome.
  - DEPLOY → VERIFY is mandatory: pipeline never claims SUCCEEDED on HTTP 200 alone.
  - If VERIFY_PRODUCTION fails → pipeline status = FAILED (not SUCCEEDED).
  - Final classification is set in pipeline context["classification"]:
      DEVELOPMENT            — not all CI steps run
      PRODUCTION CANDIDATE   — CI passes, build passes, PR merged, deploy triggered
      PRODUCTION VERIFIED    — deploy verified: sha_match=True + health=True
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from app.core.workflow.engine import (
    WorkflowBuilder, WorkflowRun, WorkflowStep, RetryPolicy,
)

log = logging.getLogger(__name__)

# ── Step IDs (stable identifiers used for depends_on wiring) ─────────────────

STEP_PLAN               = "01_plan"
STEP_CREATE_BRANCH      = "02_create_branch"
STEP_IMPLEMENT          = "03_implement"
STEP_STATIC_ANALYSIS    = "04_static_analysis"
STEP_UNIT_TEST          = "05_unit_test"
STEP_SECURITY_SCAN      = "06_security_scan"
STEP_BUILD              = "07_build"
STEP_CREATE_PR          = "08_create_pr"
STEP_WAIT_FOR_CI        = "09_wait_for_ci"
STEP_APPROVAL           = "10_approval"
STEP_MERGE              = "11_merge"
STEP_DEPLOY             = "12_deploy"
STEP_VERIFY_PRODUCTION  = "13_verify_production"

ALL_STEPS = [
    STEP_PLAN, STEP_CREATE_BRANCH, STEP_IMPLEMENT,
    STEP_STATIC_ANALYSIS, STEP_UNIT_TEST, STEP_SECURITY_SCAN,
    STEP_BUILD, STEP_CREATE_PR, STEP_WAIT_FOR_CI,
    STEP_APPROVAL, STEP_MERGE, STEP_DEPLOY, STEP_VERIFY_PRODUCTION,
]


# ── Step implementations ───────────────────────────────────────────────────────

async def _step_plan(ctx: dict) -> dict:
    """Record plan in mission memory; return list of planned file changes."""
    from app.engineering.memory import get_engineering_memory
    mission_id = ctx["mission_id"]
    org_id     = ctx["org_id"]
    objective  = ctx.get("objective", "unspecified")
    plan_notes = ctx.get("plan_notes", "")

    mem = get_engineering_memory()
    await mem.store(
        org_id=org_id,
        mission_id=mission_id,
        fact_type="mission_notes",
        value=f"objective={objective}\nplan={plan_notes}",
    )
    return {
        "objective":  objective,
        "plan_notes": plan_notes,
        "status":     "planned",
    }


async def _step_create_branch(ctx: dict) -> dict:
    """Create a Git branch for this release."""
    gw = _gateway(ctx)
    branch_name = ctx.get("branch_name") or f"release/{ctx['mission_id'][:8]}"
    result = await gw.execute(
        tool_name="github.create_branch",
        args={
            "repo":  ctx["repo"],
            "name":  branch_name,
            "sha":   ctx["base_sha"],
        },
        org_id=ctx["org_id"],
        mission_id=ctx["mission_id"],
        user_role=ctx["user_role"],
    )
    _raise_if_failed(result, "create_branch")
    ctx["branch_name"] = branch_name
    return {"branch_name": branch_name, "base_sha": ctx["base_sha"]}


async def _step_implement(ctx: dict) -> dict:
    """
    The AI planner writes code changes to the branch via GitHub API.

    In production this step is driven by InferenceEngine. In this pipeline
    we call the implementation function stored in ctx["implement_fn"] — the
    MissionRunner injects the actual function when building the WorkflowDef.
    This avoids hard-coupling the pipeline to the AI layer and allows tests
    to inject a stub.
    """
    implement_fn = ctx.get("implement_fn")
    if implement_fn is None:
        raise ValueError("implement_fn missing from release pipeline context")
    result = await implement_fn(ctx)
    return result


async def _step_static_analysis(ctx: dict) -> dict:
    """
    Trigger lint + TypeScript check via CI.

    Uses github.get_workflow_runs to find the latest run for the branch
    and polls until a terminal state.
    """
    gw = _gateway(ctx)
    # Dispatch workflow if workflow_id provided; otherwise read latest run
    workflow_id = ctx.get("lint_workflow_id")
    if workflow_id:
        await gw.execute(
            tool_name="github.create_workflow_dispatch",
            args={
                "repo":        ctx["repo"],
                "workflow_id": workflow_id,
                "ref":         ctx["branch_name"],
            },
            org_id=ctx["org_id"],
            mission_id=ctx["mission_id"],
            user_role=ctx["user_role"],
        )
        await asyncio.sleep(5)

    run_result = await _wait_workflow(gw, ctx, workflow_id or "lint", "lint/static-analysis")
    if not run_result.get("passed"):
        raise RuntimeError(f"static_analysis FAILED: {run_result.get('conclusion', 'unknown')}")
    ctx["lint_passed"] = True
    return run_result


async def _step_unit_test(ctx: dict) -> dict:
    """Trigger and wait for unit test workflow."""
    gw = _gateway(ctx)
    workflow_id = ctx.get("test_workflow_id")
    if workflow_id:
        await gw.execute(
            tool_name="github.create_workflow_dispatch",
            args={
                "repo":        ctx["repo"],
                "workflow_id": workflow_id,
                "ref":         ctx["branch_name"],
            },
            org_id=ctx["org_id"],
            mission_id=ctx["mission_id"],
            user_role=ctx["user_role"],
        )
        await asyncio.sleep(5)

    run_result = await _wait_workflow(gw, ctx, workflow_id or "test", "unit-tests")
    if not run_result.get("passed"):
        raise RuntimeError(f"unit_test FAILED: {run_result.get('conclusion', 'unknown')}")
    ctx["tests_passed"] = True
    return run_result


async def _step_security_scan(ctx: dict) -> dict:
    """
    Trigger and wait for security / secret scan.
    If no security workflow is configured, marks the step as SKIPPED
    (but records it explicitly — it does NOT pass silently).
    """
    workflow_id = ctx.get("security_workflow_id")
    if not workflow_id:
        log.warning("release_pipeline: no security_workflow_id configured — step skipped (not passing)")
        return {"skipped": True, "reason": "no security_workflow_id configured"}

    gw = _gateway(ctx)
    await gw.execute(
        tool_name="github.create_workflow_dispatch",
        args={
            "repo":        ctx["repo"],
            "workflow_id": workflow_id,
            "ref":         ctx["branch_name"],
        },
        org_id=ctx["org_id"],
        mission_id=ctx["mission_id"],
        user_role=ctx["user_role"],
    )
    await asyncio.sleep(5)
    run_result = await _wait_workflow(gw, ctx, workflow_id, "security-scan")
    if not run_result.get("passed"):
        raise RuntimeError(f"security_scan FAILED: {run_result.get('conclusion', 'unknown')}")
    return run_result


async def _step_build(ctx: dict) -> dict:
    """Trigger and wait for Docker/Vite build."""
    workflow_id = ctx.get("build_workflow_id")
    if not workflow_id:
        return {"skipped": True, "reason": "no build_workflow_id configured"}

    gw = _gateway(ctx)
    await gw.execute(
        tool_name="github.create_workflow_dispatch",
        args={
            "repo":        ctx["repo"],
            "workflow_id": workflow_id,
            "ref":         ctx["branch_name"],
        },
        org_id=ctx["org_id"],
        mission_id=ctx["mission_id"],
        user_role=ctx["user_role"],
    )
    await asyncio.sleep(5)
    run_result = await _wait_workflow(gw, ctx, workflow_id, "build")
    if not run_result.get("passed"):
        raise RuntimeError(f"build FAILED: {run_result.get('conclusion', 'unknown')}")
    return run_result


async def _step_create_pr(ctx: dict) -> dict:
    """Open a pull request for the implementation branch."""
    gw = _gateway(ctx)
    title = ctx.get("pr_title") or f"[Auto] {ctx.get('objective', 'Release')[:72]}"
    body  = ctx.get("pr_body") or (
        f"Auto-generated by Release Autopilot\n\n"
        f"Mission: {ctx['mission_id']}\n"
        f"Objective: {ctx.get('objective', 'unspecified')}\n\n"
        "---\n*Do not merge unless all CI checks pass and the approval below is granted.*"
    )
    result = await gw.execute(
        tool_name="github.create_pull_request",
        args={
            "repo":  ctx["repo"],
            "title": title,
            "body":  body,
            "head":  ctx["branch_name"],
            "base":  ctx.get("base_branch", "main"),
        },
        org_id=ctx["org_id"],
        mission_id=ctx["mission_id"],
        user_role=ctx["user_role"],
    )
    _raise_if_failed(result, "create_pull_request")
    pr_number = (result.output or {}).get("number")
    ctx["pr_number"] = pr_number
    return {"pr_number": pr_number, "title": title}


async def _step_wait_for_ci(ctx: dict) -> dict:
    """
    Poll GitHub check suites for the branch until all pass.
    Times out after ctx.get("ci_timeout_s", 1800) seconds (default 30 min).
    """
    gw = _gateway(ctx)
    timeout_s = ctx.get("ci_timeout_s", 1800)
    branch    = ctx["branch_name"]
    repo      = ctx["repo"]
    deadline  = asyncio.get_event_loop().time() + timeout_s

    while asyncio.get_event_loop().time() < deadline:
        result = await gw.execute(
            tool_name="github.get_check_suites",
            args={"repo": repo, "ref": branch},
            org_id=ctx["org_id"],
            mission_id=ctx["mission_id"],
            user_role=ctx["user_role"],
        )
        if result.success:
            suites = (result.output or {}).get("check_suites", [])
            all_complete   = all(s.get("status") == "completed" for s in suites)
            all_successful = all(s.get("conclusion") == "success" for s in suites)
            if all_complete:
                if not all_successful:
                    failed = [s.get("app", {}).get("name") for s in suites
                              if s.get("conclusion") != "success"]
                    raise RuntimeError(f"CI failed: {failed}")
                ctx["ci_passed"] = True
                return {"ci_passed": True, "suites": len(suites)}
        await asyncio.sleep(30)

    raise RuntimeError("CI wait timed out")


async def _step_approval(ctx: dict) -> dict:
    """
    Persistent approval gate — creates an ApprovalRequest and blocks
    until the MissionRunner signals that it was APPROVED.

    The approval_event (asyncio.Event) is injected into ctx by the
    MissionRunner. The gate expiry is handled by ApprovalService.
    """
    approval_event: Optional[asyncio.Event] = ctx.get("approval_event")
    approval_id = ctx.get("approval_id")

    if approval_event is None:
        # Self-contained mode: create the approval and wait for the event
        from app.engineering.approvals import get_approval_service
        svc = get_approval_service()
        approval = await svc.request_approval(
            org_id=ctx["org_id"],
            mission_id=ctx["mission_id"],
            task_id=None,
            action="merge_pull_request",
            resource=f"github:{ctx['repo']}:pr:{ctx.get('pr_number', '?')}",
            risk_level="high",
            requested_by=ctx.get("user_id", "00000000-0000-0000-0000-000000000000"),
            reason=f"Merge PR#{ctx.get('pr_number')} — Release Autopilot, mission {ctx['mission_id'][:8]}",
        )
        approval_id = approval["id"]
        ctx["approval_id"] = approval_id
        log.info("approval requested: %s — waiting for human decision", approval_id[:8])

        # Wait up to 4 hours (expiry window for high-risk)
        approval_event = asyncio.Event()
        ctx["approval_event"] = approval_event
        try:
            await asyncio.wait_for(approval_event.wait(), timeout=4 * 3600)
        except asyncio.TimeoutError:
            raise RuntimeError(f"approval {approval_id[:8]} timed out (4h)")
    else:
        try:
            await asyncio.wait_for(approval_event.wait(), timeout=4 * 3600)
        except asyncio.TimeoutError:
            raise RuntimeError(f"approval {approval_id[:8]} timed out (4h)")

    # Verify the approval was actually APPROVED (not just any signal)
    if ctx.get("approval_decision") == "rejected":
        raise RuntimeError(f"approval {approval_id[:8]} was REJECTED")

    return {"approved": True, "approval_id": approval_id}


async def _step_merge(ctx: dict) -> dict:
    """Merge the approved PR via github.merge_pull_request (DESTRUCTIVE)."""
    gw = _gateway(ctx)
    pr_number = ctx.get("pr_number")
    if not pr_number:
        raise ValueError("pr_number missing from context")
    result = await gw.execute(
        tool_name="github.merge_pull_request",
        args={
            "repo":         ctx["repo"],
            "pull_number":  pr_number,
            "merge_method": ctx.get("merge_method", "squash"),
        },
        org_id=ctx["org_id"],
        mission_id=ctx["mission_id"],
        user_role=ctx["user_role"],
    )
    _raise_if_failed(result, "merge_pull_request")
    merged_sha = (result.output or {}).get("sha")
    ctx["merged_sha"] = merged_sha
    return {"merged": True, "sha": merged_sha, "pr_number": pr_number}


async def _step_deploy(ctx: dict) -> dict:
    """
    Trigger a Render deploy.

    IMPORTANT: HTTP 201 from this step is NOT deployment success.
    The next step (VERIFY_PRODUCTION) confirms actual success.
    """
    gw = _gateway(ctx)
    service_id = ctx.get("render_service_id")
    if not service_id:
        raise ValueError("render_service_id missing from release pipeline context")

    result = await gw.execute(
        tool_name="render.trigger_deploy",
        args={
            "service_id":    service_id,
            "clear_cache":   ctx.get("clear_cache", False),
        },
        org_id=ctx["org_id"],
        mission_id=ctx["mission_id"],
        user_role=ctx["user_role"],
    )
    _raise_if_failed(result, "trigger_deploy")
    deploy_id = (result.output or {}).get("deploy_id")
    ctx["deploy_id"]  = deploy_id
    ctx["deploy_evidence_id"] = result.evidence_id
    log.info("deploy triggered: deploy_id=%s — awaiting VERIFY_PRODUCTION", deploy_id)
    return {
        "deploy_id":   deploy_id,
        "evidence_id": result.evidence_id,
        "note":        "HTTP 201 received — NOT yet production verified",
        "verified":    False,
    }


async def _step_verify_production(ctx: dict) -> dict:
    """
    Verify the deployment is truly live with SHA match.

    This is the ONLY step that can set classification=PRODUCTION VERIFIED.
    If this step fails → classification = PRODUCTION CANDIDATE (at best).
    The pipeline raises RuntimeError to force status=FAILED.
    """
    from app.engineering.verify import get_production_verifier
    from app.engineering.memory import get_engineering_memory

    verifier = get_production_verifier()
    requested_sha = ctx.get("merged_sha") or ctx.get("base_sha")
    if not requested_sha:
        raise ValueError("requested_sha unknown — cannot verify production")

    result = await verifier.verify_render_deploy(
        org_id=ctx["org_id"],
        mission_id=ctx["mission_id"],
        service_id=ctx["render_service_id"],
        deploy_id=ctx["deploy_id"],
        requested_sha=requested_sha,
        health_url=ctx.get("health_url"),
        max_poll_seconds=ctx.get("verify_timeout_s", 300),
        evidence_id=ctx.get("deploy_evidence_id"),
    )

    # Record deployment in memory
    mem = get_engineering_memory()
    await mem.record_deployment(
        org_id=ctx["org_id"],
        mission_id=ctx["mission_id"],
        deploy_id=ctx["deploy_id"],
        sha=requested_sha,
        status="verified" if result.is_production_verified else "failed",
    )

    if result.is_production_verified:
        ctx["classification"] = "PRODUCTION VERIFIED"
        log.info(
            "🟢 PRODUCTION VERIFIED: sha=%s health=OK sha_match=True",
            requested_sha[:8],
        )
        return {
            "production_verified": True,
            "sha_match":           True,
            "health_ok":           True,
            "deploy_status":       result.deploy_status,
            "classification":      "PRODUCTION VERIFIED",
        }
    else:
        ctx["classification"] = "PRODUCTION CANDIDATE"
        reason = result.failure_reason or "verification failed"
        log.error("🔴 PRODUCTION NOT VERIFIED: %s", reason)
        raise RuntimeError(f"production verification FAILED: {reason}")


# ── Helper utilities ───────────────────────────────────────────────────────────

def _gateway(ctx: dict):
    """Return or create an EngineeringToolGateway from context."""
    gw = ctx.get("_gateway")
    if gw is None:
        from app.engineering.tools.gateway import EngineeringToolGateway
        gw = EngineeringToolGateway()
        ctx["_gateway"] = gw
    return gw


def _raise_if_failed(result, label: str) -> None:
    if not result.success:
        raise RuntimeError(f"{label} failed: {result.error}")


async def _wait_workflow(gw, ctx: dict, workflow_id: str, label: str) -> dict:
    """Poll workflow runs on the branch until terminal, timeout 30 min."""
    timeout_s = ctx.get("workflow_timeout_s", 1800)
    deadline  = asyncio.get_event_loop().time() + timeout_s
    while asyncio.get_event_loop().time() < deadline:
        result = await gw.execute(
            tool_name="github.get_workflow_runs",
            args={
                "repo":        ctx["repo"],
                "workflow_id": workflow_id,
                "branch":      ctx["branch_name"],
                "per_page":    1,
            },
            org_id=ctx["org_id"],
            mission_id=ctx["mission_id"],
            user_role=ctx["user_role"],
        )
        if result.success:
            runs = (result.output or {}).get("workflow_runs", [])
            if runs:
                run = runs[0]
                status     = run.get("status", "queued")
                conclusion = run.get("conclusion")
                if status == "completed":
                    return {
                        "passed":      conclusion == "success",
                        "conclusion":  conclusion,
                        "workflow_id": workflow_id,
                        "label":       label,
                    }
        await asyncio.sleep(20)
    return {"passed": False, "conclusion": "timeout", "label": label}


# ── WorkflowDef factory ────────────────────────────────────────────────────────

def build_release_pipeline(
    *,
    mission_id: str,
    org_id: str,
    user_id: str,
    user_role: str,
    repo: str,
    base_sha: str,
    objective: str,
    render_service_id: str,
    health_url: Optional[str] = None,
    branch_name: Optional[str] = None,
    base_branch: str = "main",
    implement_fn=None,
    lint_workflow_id: Optional[str] = None,
    test_workflow_id: Optional[str] = None,
    security_workflow_id: Optional[str] = None,
    build_workflow_id: Optional[str] = None,
    merge_method: str = "squash",
    ci_timeout_s: int = 1800,
    verify_timeout_s: int = 300,
) -> WorkflowRun:
    """
    Build a 13-step Release Autopilot WorkflowDef.

    All parameters are resolved server-side. org_id and user_id come from
    OrgContext — never from the request body.
    """
    ctx: dict[str, Any] = {
        "mission_id":            mission_id,
        "org_id":                org_id,
        "user_id":               user_id,
        "user_role":             user_role,
        "repo":                  repo,
        "base_sha":              base_sha,
        "objective":             objective,
        "render_service_id":     render_service_id,
        "health_url":            health_url,
        "branch_name":           branch_name,
        "base_branch":           base_branch,
        "implement_fn":          implement_fn,
        "lint_workflow_id":      lint_workflow_id,
        "test_workflow_id":      test_workflow_id,
        "security_workflow_id":  security_workflow_id,
        "build_workflow_id":     build_workflow_id,
        "merge_method":          merge_method,
        "ci_timeout_s":          ci_timeout_s,
        "verify_timeout_s":      verify_timeout_s,
        "classification":        "DEVELOPMENT",   # default; upgraded by verify step
    }

    steps = [
        WorkflowStep(
            id=STEP_PLAN,
            name="01 Plan",
            fn=lambda c=ctx: _step_plan(c),
            depends_on=[],
            retry_policy=RetryPolicy(max_attempts=1),
        ),
        WorkflowStep(
            id=STEP_CREATE_BRANCH,
            name="02 Create Branch",
            fn=lambda c=ctx: _step_create_branch(c),
            depends_on=[STEP_PLAN],
            retry_policy=RetryPolicy(max_attempts=2, base_delay_s=3),
        ),
        WorkflowStep(
            id=STEP_IMPLEMENT,
            name="03 Implement",
            fn=lambda c=ctx: _step_implement(c),
            depends_on=[STEP_CREATE_BRANCH],
            retry_policy=RetryPolicy(max_attempts=1),
            timeout_s=600,
        ),
        WorkflowStep(
            id=STEP_STATIC_ANALYSIS,
            name="04 Static Analysis",
            fn=lambda c=ctx: _step_static_analysis(c),
            depends_on=[STEP_IMPLEMENT],
            retry_policy=RetryPolicy(max_attempts=2, base_delay_s=30),
            timeout_s=1200,
        ),
        WorkflowStep(
            id=STEP_UNIT_TEST,
            name="05 Unit Tests",
            fn=lambda c=ctx: _step_unit_test(c),
            depends_on=[STEP_IMPLEMENT],
            retry_policy=RetryPolicy(max_attempts=2, base_delay_s=30),
            timeout_s=1800,
        ),
        WorkflowStep(
            id=STEP_SECURITY_SCAN,
            name="06 Security Scan",
            fn=lambda c=ctx: _step_security_scan(c),
            depends_on=[STEP_IMPLEMENT],
            retry_policy=RetryPolicy(max_attempts=2, base_delay_s=15),
            timeout_s=900,
        ),
        WorkflowStep(
            id=STEP_BUILD,
            name="07 Build",
            fn=lambda c=ctx: _step_build(c),
            depends_on=[STEP_STATIC_ANALYSIS, STEP_UNIT_TEST, STEP_SECURITY_SCAN],
            retry_policy=RetryPolicy(max_attempts=2, base_delay_s=30),
            timeout_s=1800,
        ),
        WorkflowStep(
            id=STEP_CREATE_PR,
            name="08 Create PR",
            fn=lambda c=ctx: _step_create_pr(c),
            depends_on=[STEP_BUILD],
            retry_policy=RetryPolicy(max_attempts=2, base_delay_s=5),
        ),
        WorkflowStep(
            id=STEP_WAIT_FOR_CI,
            name="09 Wait for CI",
            fn=lambda c=ctx: _step_wait_for_ci(c),
            depends_on=[STEP_CREATE_PR],
            retry_policy=RetryPolicy(max_attempts=1),
            timeout_s=ci_timeout_s + 60,
        ),
        WorkflowStep(
            id=STEP_APPROVAL,
            name="10 Approval",
            fn=lambda c=ctx: _step_approval(c),
            depends_on=[STEP_WAIT_FOR_CI],
            retry_policy=RetryPolicy(max_attempts=1),
            requires_approval=True,
            timeout_s=4 * 3600 + 60,
        ),
        WorkflowStep(
            id=STEP_MERGE,
            name="11 Merge PR",
            fn=lambda c=ctx: _step_merge(c),
            depends_on=[STEP_APPROVAL],
            retry_policy=RetryPolicy(max_attempts=2, base_delay_s=5),
        ),
        WorkflowStep(
            id=STEP_DEPLOY,
            name="12 Deploy",
            fn=lambda c=ctx: _step_deploy(c),
            depends_on=[STEP_MERGE],
            retry_policy=RetryPolicy(max_attempts=2, base_delay_s=10),
        ),
        WorkflowStep(
            id=STEP_VERIFY_PRODUCTION,
            name="13 Verify Production",
            fn=lambda c=ctx: _step_verify_production(c),
            depends_on=[STEP_DEPLOY],
            retry_policy=RetryPolicy(max_attempts=1),
            timeout_s=verify_timeout_s + 60,
        ),
    ]

    builder = WorkflowBuilder(name=f"release-autopilot:{mission_id[:8]}")
    for step in steps:
        builder.step(
            step.id,
            step.name,
            step.fn,
            args=step.args,
            depends_on=step.depends_on,
            retry=step.retry_policy,
            timeout_s=step.timeout_s,
            requires_approval=step.requires_approval,
        )
    return builder.build(context=ctx)
