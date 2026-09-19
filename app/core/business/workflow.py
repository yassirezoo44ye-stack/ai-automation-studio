"""
Business Plan & Validation Engine — BUSINESS_PLAN_ENGINE workflow.

Uses the existing WorkflowEngine (app/core/workflow/engine.py).
16 stages — some run in parallel, each is idempotent and resumable.

Stage order:
  1.  intake           (series)
  2.  company_desc     (series, depends: intake)
  3.  market_intel     (parallel with 4)
  4.  competitor_intel (parallel with 3, depends: intake)
  5.  offer_pricing    (depends: 3, 4)
  6.  go_to_market     (depends: 2, 5)
  7.  ops_finance      (depends: 2, 5)
  8.  score_v1         (depends: 3, 4, 5, 6, 7)
  9.  assembly         (depends: score_v1)
  10. assumption_audit (depends: assembly)
  11. adversarial_rev  (depends: assumption_audit, score_v1)
  12. score_final      (depends: adversarial_rev)
  13. mark_complete    (depends: score_final)
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from app.core.workflow.engine import (
    RetryPolicy, WorkflowBuilder, WorkflowEngine, WorkflowRun, WorkflowStatus,
)
from app.core.business import agents
from app.core.business.scoring import compute_score
from app.core.db import acquire_scoped

log = logging.getLogger(__name__)

_engine = WorkflowEngine()

# ── Shared helpers ─────────────────────────────────────────────────────────────

async def _get_section(plan_id: str, key: str, org_id: str) -> Optional[str]:
    """Fetch a completed section's content from DB."""
    async with acquire_scoped(org_id) as conn:
        row = await conn.fetchrow(
            "SELECT content FROM bp_sections WHERE plan_id=$1 AND section_key=$2 AND status='COMPLETED'",
            plan_id, key,
        )
    return row["content"] if row else None


async def _get_facts(plan_id: str, org_id: str) -> list[dict]:
    async with acquire_scoped(org_id) as conn:
        rows = await conn.fetch(
            "SELECT fact_key, value, status, source_type, confidence FROM bp_facts WHERE plan_id=$1",
            plan_id,
        )
    return [dict(r) for r in rows]


async def _get_competitors(plan_id: str, org_id: str) -> list[dict]:
    async with acquire_scoped(org_id) as conn:
        rows = await conn.fetch(
            "SELECT name, website, description, strengths, weaknesses, pricing, market_position "
            "FROM bp_competitors WHERE plan_id=$1 LIMIT 6",
            plan_id,
        )
    return [dict(r) for r in rows]


async def _mark_section_running(plan_id: str, section_key: str, org_id: str) -> None:
    async with acquire_scoped(org_id) as conn:
        await conn.execute(
            """
            INSERT INTO bp_sections (plan_id, organization_id, section_key, title, status)
            VALUES ($1,$2,$3,$3,'RUNNING')
            ON CONFLICT (plan_id, section_key) DO UPDATE SET status='RUNNING', updated_at=NOW()
            """,
            plan_id, org_id, section_key,
        )


async def _mark_plan_status(plan_id: str, status: str, *, org_id: str) -> None:
    async with acquire_scoped(org_id) as conn:
        await conn.execute(
            "UPDATE bp_plans SET status=$1, updated_at=NOW() WHERE id=$2",
            status, plan_id,
        )


# ── Step functions (each is idempotent) ──────────────────────────────────────

async def step_intake(
    plan_id: str, org_id: str, user_id: str, idea_raw: str,
    industry=None, stage: str = "IDEA",
    _context: dict | None = None, **_
) -> dict:
    await _mark_section_running(plan_id, "intake", org_id)
    async with acquire_scoped(org_id) as conn:
        data = await agents.run_idea_intake(
            conn, plan_id, org_id, user_id, idea_raw, industry, stage,
        )
    return {"intake_data": data}


async def step_company_desc(
    plan_id: str, org_id: str, user_id: str, idea_raw: str,
    industry=None, stage: str = "IDEA",
    _context: dict | None = None, **_
) -> dict:
    intake_data = (_context or {}).get("intake.intake_data", {})

    await _mark_section_running(plan_id, "company_description", org_id)
    async with acquire_scoped(org_id) as conn:
        text = await agents.run_company_description(
            conn, plan_id, org_id, user_id,
            idea_raw, industry,
            intake_data,
        )
    return {"company_summary": text[:1000]}


async def step_market_intel(
    plan_id: str, org_id: str, user_id: str, idea_raw: str,
    industry=None, stage: str = "IDEA",
    _context: dict | None = None, **_
) -> dict:
    ctx = _context or {}
    intake_data     = ctx.get("intake.intake_data", {})
    company_summary = ctx.get("company_desc.company_summary")

    await _mark_section_running(plan_id, "market_intelligence", org_id)
    async with acquire_scoped(org_id) as conn:
        text = await agents.run_market_intelligence(
            conn, plan_id, org_id, user_id,
            idea_raw, industry,
            company_summary,
            intake_data.get("target_customers"),
        )
    return {"market_summary": text[:1000]}


async def step_competitor_intel(
    plan_id: str, org_id: str, user_id: str, idea_raw: str,
    industry=None, stage: str = "IDEA",
    _context: dict | None = None, **_
) -> dict:
    ctx = _context or {}
    company_summary = ctx.get("company_desc.company_summary")
    market_summary  = ctx.get("market_intel.market_summary")

    await _mark_section_running(plan_id, "competitor_intelligence", org_id)
    async with acquire_scoped(org_id) as conn:
        text = await agents.run_competitor_intelligence(
            conn, plan_id, org_id, user_id,
            idea_raw, industry,
            company_summary,
            market_summary,
        )
    return {"competitor_summary": text[:500]}


async def step_offer_pricing(
    plan_id: str, org_id: str, user_id: str, idea_raw: str,
    industry=None, stage: str = "IDEA",
    _context: dict | None = None, **_
) -> dict:
    ctx = _context or {}
    intake_data    = ctx.get("intake.intake_data", {})
    market_summary = ctx.get("market_intel.market_summary")
    competitors    = await _get_competitors(plan_id, org_id)

    await _mark_section_running(plan_id, "offer_pricing", org_id)
    async with acquire_scoped(org_id) as conn:
        text = await agents.run_offer_pricing(
            conn, plan_id, org_id, user_id,
            idea_raw,
            intake_data.get("target_customers"),
            market_summary,
            competitors,
        )
    return {"offer_summary": text[:500]}


async def step_go_to_market(
    plan_id: str, org_id: str, user_id: str, idea_raw: str,
    industry=None, stage: str = "IDEA",
    _context: dict | None = None, **_
) -> dict:
    ctx = _context or {}
    intake_data     = ctx.get("intake.intake_data", {})
    company_summary = ctx.get("company_desc.company_summary")
    offer_summary   = ctx.get("offer_pricing.offer_summary")
    market_summary  = ctx.get("market_intel.market_summary")

    await _mark_section_running(plan_id, "go_to_market", org_id)
    async with acquire_scoped(org_id) as conn:
        await agents.run_go_to_market(
            conn, plan_id, org_id, user_id,
            company_summary,
            offer_summary,
            intake_data.get("target_customers"),
            market_summary,
        )
    return {}


async def step_ops_finance(
    plan_id: str, org_id: str, user_id: str, idea_raw: str,
    industry=None, stage: str = "IDEA",
    _context: dict | None = None, **_
) -> dict:
    ctx = _context or {}
    company_summary = ctx.get("company_desc.company_summary")
    offer_summary   = ctx.get("offer_pricing.offer_summary")

    await _mark_section_running(plan_id, "ops_finance", org_id)
    async with acquire_scoped(org_id) as conn:
        await agents.run_ops_finance(
            conn, plan_id, org_id, user_id,
            company_summary,
            offer_summary,
            stage,
        )
    return {}


async def step_score(
    plan_id: str, org_id: str,
    _context: dict | None = None, **_
) -> dict:
    async with acquire_scoped(org_id) as conn:
        score_data = await compute_score(conn, plan_id, org_id)
    return {"score": score_data["overall_score"]}


async def step_assembly(
    plan_id: str, org_id: str, user_id: str,
    _context: dict | None = None, **_
) -> dict:
    await _mark_section_running(plan_id, "full_plan", org_id)

    async with acquire_scoped(org_id) as conn:
        rows = await conn.fetch(
            "SELECT section_key, content FROM bp_sections WHERE plan_id=$1 AND status='COMPLETED'",
            plan_id,
        )
        sections = {r["section_key"]: r["content"] for r in rows
                    if r["section_key"] not in ("full_plan", "assumption_audit", "adversarial_review")}
    facts = await _get_facts(plan_id, org_id)
    async with acquire_scoped(org_id) as conn:
        plan_text = await agents.run_assembly(conn, plan_id, org_id, user_id, sections, facts)
    return {"plan_text": plan_text[:2000]}


async def step_assumption_audit(
    plan_id: str, org_id: str, user_id: str,
    _context: dict | None = None, **_
) -> dict:
    await _mark_section_running(plan_id, "assumption_audit", org_id)
    plan_text = (_context or {}).get("assembly.plan_text") or await _get_section(plan_id, "full_plan", org_id) or ""
    facts = await _get_facts(plan_id, org_id)

    async with acquire_scoped(org_id) as conn:
        await agents.run_assumption_auditor(conn, plan_id, org_id, user_id, plan_text, facts)
    return {}


async def step_adversarial(
    plan_id: str, org_id: str, user_id: str,
    _context: dict | None = None, **_
) -> dict:
    ctx = _context or {}
    await _mark_section_running(plan_id, "adversarial_review", org_id)
    plan_text = ctx.get("assembly.plan_text") or await _get_section(plan_id, "full_plan", org_id) or ""
    score     = ctx.get("score_v1.score", 0)

    async with acquire_scoped(org_id) as conn:
        await agents.run_adversarial_reviewer(conn, plan_id, org_id, user_id, plan_text, score)
    return {}


async def step_final_score(
    plan_id: str, org_id: str,
    _context: dict | None = None, **_
) -> dict:
    async with acquire_scoped(org_id) as conn:
        score_data = await compute_score(conn, plan_id, org_id)
    return {"final_score": score_data["overall_score"]}


async def step_mark_complete(
    plan_id: str, org_id: str,
    _context: dict | None = None, **_
) -> dict:
    await _mark_plan_status(plan_id, "COMPLETED", org_id=org_id)
    return {}


# ── Workflow builder ───────────────────────────────────────────────────────────

def build_business_plan_workflow(
    plan_id: str,
    org_id: str,
    user_id: str,
    idea_raw: str,
    industry: Optional[str],
    stage: str,
) -> WorkflowRun:
    """
    Construct the BUSINESS_PLAN_ENGINE workflow.
    The initial context is shared across all steps.
    """
    base_ctx: dict[str, Any] = {
        "plan_id":  plan_id,
        "org_id":   org_id,
        "user_id":  user_id,
        "idea_raw": idea_raw,
        "industry": industry,
        "stage":    stage,
    }

    _retry = RetryPolicy(max_attempts=2, base_delay_s=2.0, max_delay_s=20.0)

    builder = (
        WorkflowBuilder("BUSINESS_PLAN_ENGINE")
        .step("intake",           "Idea Intake",
              step_intake,           args=base_ctx,
              retry=_retry,          timeout_s=120.0)
        .step("company_desc",     "Company Description",
              step_company_desc,     args=base_ctx, depends_on=["intake"],
              retry=_retry,          timeout_s=90.0)
        # market_intel and competitor_intel run in parallel after intake
        .step("market_intel",     "Market Intelligence",
              step_market_intel,     args=base_ctx, depends_on=["intake"],
              retry=_retry,          timeout_s=120.0)
        .step("competitor_intel", "Competitor Intelligence",
              step_competitor_intel, args=base_ctx, depends_on=["intake"],
              retry=_retry,          timeout_s=120.0)
        # offer and GTM depend on both parallel branches
        .step("offer_pricing",    "Offer & Pricing",
              step_offer_pricing,    args=base_ctx,
              depends_on=["market_intel", "competitor_intel"],
              retry=_retry,          timeout_s=90.0)
        .step("go_to_market",     "Go-To-Market",
              step_go_to_market,     args=base_ctx,
              depends_on=["company_desc", "offer_pricing"],
              retry=_retry,          timeout_s=90.0)
        .step("ops_finance",      "Operations & Finance",
              step_ops_finance,      args=base_ctx,
              depends_on=["company_desc", "offer_pricing"],
              retry=_retry,          timeout_s=120.0)
        .step("score_v1",         "Readiness Score v1",
              step_score,            args=base_ctx,
              depends_on=["market_intel", "competitor_intel",
                          "offer_pricing", "go_to_market", "ops_finance"],
              timeout_s=30.0)
        .step("assembly",         "Plan Assembly",
              step_assembly,         args=base_ctx, depends_on=["score_v1"],
              retry=_retry,          timeout_s=180.0)
        .step("assumption_audit", "Assumption Audit",
              step_assumption_audit, args=base_ctx, depends_on=["assembly"],
              retry=_retry,          timeout_s=90.0)
        .step("adversarial_rev",  "Adversarial Review",
              step_adversarial,      args=base_ctx,
              depends_on=["assumption_audit", "score_v1"],
              retry=_retry,          timeout_s=90.0)
        .step("score_final",      "Final Readiness Score",
              step_final_score,      args=base_ctx, depends_on=["adversarial_rev"],
              timeout_s=30.0)
        .step("mark_complete",    "Mark Complete",
              step_mark_complete,    args=base_ctx, depends_on=["score_final"],
              timeout_s=10.0)
    )
    return builder.build()


async def start_business_plan(
    plan_id: str,
    org_id: str,
    user_id: str,
    idea_raw: str,
    industry: Optional[str],
    stage: str,
) -> WorkflowRun:
    """Start the workflow and mark plan as GENERATING."""
    await _mark_plan_status(plan_id, "GENERATING", org_id=org_id)
    workflow = build_business_plan_workflow(
        plan_id, org_id, user_id, idea_raw, industry, stage,
    )
    run = await _engine.execute(workflow)
    if run.status == WorkflowStatus.FAILED:
        log.warning("business_plan workflow FAILED for plan %s: %s", plan_id, getattr(run, "error", None))
        async with acquire_scoped(org_id) as conn:
            await conn.execute(
                "UPDATE bp_plans SET status='FAILED', updated_at=NOW() WHERE id=$1",
                plan_id,
            )
    return run


async def retry_sections(
    plan_id: str,
    org_id: str,
    user_id: str,
    idea_raw: str,
    industry: Optional[str],
    stage: str,
    section_keys: list[str],
) -> dict[str, str]:
    """
    Fix Loop: re-run only the specified failing sections.
    Returns {section_key: 'ok'|'error'} mapping.
    """
    results: dict[str, str] = {}

    _section_fns = {
        "intake":                  step_intake,
        "company_description":     step_company_desc,
        "market_intelligence":     step_market_intel,
        "competitor_intelligence": step_competitor_intel,
        "offer_pricing":           step_offer_pricing,
        "go_to_market":            step_go_to_market,
        "ops_finance":             step_ops_finance,
        "assumption_audit":        step_assumption_audit,
        "adversarial_review":      step_adversarial,
        "full_plan":               step_assembly,
    }

    ctx: dict[str, Any] = {
        "plan_id":  plan_id,
        "org_id":   org_id,
        "user_id":  user_id,
        "idea_raw": idea_raw,
        "industry": industry,
        "stage":    stage,
    }

    for key in section_keys:
        fn = _section_fns.get(key)
        if not fn:
            results[key] = "unknown_section"
            continue
        try:
            await fn(**ctx)
            results[key] = "ok"
        except Exception as exc:
            log.exception("retry_sections: failed %s: %s", key, exc)
            results[key] = f"error: {exc}"

    # Recompute score after retries
    async with acquire_scoped(org_id) as conn:
        await compute_score(conn, plan_id, org_id)

    return results
