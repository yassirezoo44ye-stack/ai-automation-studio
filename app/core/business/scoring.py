"""
Business Readiness Score (0-100).

Score is evidence-based — not text-length-based.
Each dimension has a max weight; verified facts increase the score,
assumptions reduce it, missing data reduces it more.

Dimensions and weights:
  idea_clarity          10   (intake completeness)
  market_evidence       20   (TAM/SAM/SOM + market facts)
  competitive_analysis  15   (competitor records)
  offer_strength        15   (pricing + value prop facts)
  gtm_readiness         15   (GTM section + channel facts)
  financial_viability   15   (ops/finance section)
  risk_awareness        10   (assumption audit + adversarial review present)
"""
from __future__ import annotations

import json
import logging
from typing import Any

import asyncpg

log = logging.getLogger(__name__)

DIMENSIONS: dict[str, int] = {
    "idea_clarity":         10,
    "market_evidence":      20,
    "competitive_analysis": 15,
    "offer_strength":       15,
    "gtm_readiness":        15,
    "financial_viability":  15,
    "risk_awareness":       10,
}
assert sum(DIMENSIONS.values()) == 100


async def compute_score(
    conn: asyncpg.Connection,
    plan_id: str,
    org_id: str,
) -> dict[str, Any]:
    """
    Compute and persist the Business Readiness Score.
    Returns score record dict.
    """
    # Fetch facts
    facts = await conn.fetch(
        "SELECT fact_key, status, confidence FROM bp_facts WHERE plan_id=$1",
        plan_id,
    )
    fact_list = [dict(f) for f in facts]

    verified    = sum(1 for f in fact_list if f["status"] == "VERIFIED")
    unverified  = sum(1 for f in fact_list if f["status"] == "UNVERIFIED")
    assumptions = sum(1 for f in fact_list if f["status"] == "ASSUMPTION")
    missing     = sum(1 for f in fact_list if f["status"] == "MISSING")

    # Fetch completed sections
    sections = await conn.fetch(
        "SELECT section_key, status FROM bp_sections WHERE plan_id=$1",
        plan_id,
    )
    completed = {r["section_key"] for r in sections if r["status"] == "COMPLETED"}

    # Fetch competitor count
    comp_count = await conn.fetchval(
        "SELECT COUNT(*) FROM bp_competitors WHERE plan_id=$1",
        plan_id,
    ) or 0

    breakdown: dict[str, int] = {}

    # 1. Idea clarity — based on intake completeness
    intake_facts = [f for f in fact_list
                    if f["fact_key"] in ("problem_statement", "solution",
                                         "target_customers", "value_proposition",
                                         "revenue_model")]
    filled = sum(1 for f in intake_facts if f["status"] != "MISSING")
    breakdown["idea_clarity"] = _scale(filled / max(len(intake_facts), 1),
                                       DIMENSIONS["idea_clarity"])

    # 2. Market evidence
    market_facts = [f for f in fact_list if "market_" in f["fact_key"]]
    market_bonus = 1.0 if "market_intelligence" in completed else 0.5
    evidence_ratio = (verified + unverified * 0.5) / max(len(market_facts) + 1, 1)
    breakdown["market_evidence"] = _scale(evidence_ratio * market_bonus,
                                          DIMENSIONS["market_evidence"])

    # 3. Competitive analysis
    comp_score = min(comp_count / 3.0, 1.0)  # 3 competitors = full score
    if "competitor_intelligence" not in completed:
        comp_score *= 0.5
    breakdown["competitive_analysis"] = _scale(comp_score,
                                               DIMENSIONS["competitive_analysis"])

    # 4. Offer strength
    offer_facts = [f for f in fact_list
                   if any(k in f["fact_key"] for k in ("value_prop", "pricing", "revenue"))]
    offer_ratio = (len(offer_facts) + (1 if "offer_pricing" in completed else 0)) / 4.0
    breakdown["offer_strength"] = _scale(min(offer_ratio, 1.0),
                                         DIMENSIONS["offer_strength"])

    # 5. GTM readiness
    gtm_ready = 1.0 if "go_to_market" in completed else 0.3
    breakdown["gtm_readiness"] = _scale(gtm_ready, DIMENSIONS["gtm_readiness"])

    # 6. Financial viability
    fin_ready = 1.0 if "ops_finance" in completed else 0.2
    breakdown["financial_viability"] = _scale(fin_ready, DIMENSIONS["financial_viability"])

    # 7. Risk awareness
    risk_sections = {"assumption_audit", "adversarial_review"}
    risk_ratio = len(risk_sections & completed) / len(risk_sections)
    breakdown["risk_awareness"] = _scale(risk_ratio, DIMENSIONS["risk_awareness"])

    # Penalty for excessive unvalidated assumptions
    assumption_penalty = min(assumptions * 2, 10)
    missing_penalty    = min(missing * 3, 15)

    overall = max(0, min(100, sum(breakdown.values()) - assumption_penalty - missing_penalty))

    # Persist
    await conn.execute(
        """
        INSERT INTO bp_scores
            (plan_id, organization_id, overall_score, breakdown,
             evidence_count, assumption_count, missing_count)
        VALUES ($1,$2,$3,$4,$5,$6,$7)
        """,
        plan_id, org_id, overall, json.dumps(breakdown),
        verified + unverified, assumptions, missing,
    )
    await conn.execute(
        "UPDATE bp_plans SET readiness_score=$1, updated_at=NOW() WHERE id=$2",
        overall, plan_id,
    )

    return {
        "overall_score":    overall,
        "breakdown":        breakdown,
        "evidence_count":   verified + unverified,
        "assumption_count": assumptions,
        "missing_count":    missing,
    }


def _scale(ratio: float, max_weight: int) -> int:
    return round(max(0.0, min(1.0, ratio)) * max_weight)
