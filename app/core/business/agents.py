"""
Business Plan & Validation Engine — 10 AI agents.

Each agent:
- Receives a narrow context package (no full plan sent to every agent).
- Calls InferenceEngine.complete() — all requests go through the AI Gateway.
- Uses ModelRouter for cost routing: cheapest for extraction/formatting,
  best for research/synthesis/review.
- Returns structured output (JSON or Markdown) parsed into DB records.
- Never promotes ASSUMPTION → VERIFIED without external corroboration.
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Optional

import asyncpg

from app.ai.models import CompletionRequest, Message
from app.core.ai.inference.engine import InferenceEngine

log = logging.getLogger(__name__)

_inference = InferenceEngine()

# ── Model aliases (via ModelRouter policy strings) ────────────────────────────
# Passed as `model` — InferenceEngine._apply_model_selection() routes them.
_FAST_MODEL = "claude-haiku-4-5-20251001"    # extraction, formatting
_BEST_MODEL = "claude-sonnet-5"              # research, synthesis, adversarial

# ── Prompt injection guard pattern ────────────────────────────────────────────
_INJECTION_RE = re.compile(
    r"(?:ignore (?:previous|prior|above|all) instructions?"
    r"|forget .*?instructions?"
    r"|you are now"
    r"|act as (?!an? ))",
    re.IGNORECASE,
)


def _sanitize(text: str) -> str:
    """Strip obvious prompt-injection patterns from user-supplied text."""
    return _INJECTION_RE.sub("[REMOVED]", text)


def _extract_json(text: str) -> dict:
    """Extract the first JSON object from an LLM response."""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    return {}


async def _complete(
    system: str,
    user: str,
    *,
    model: str = _BEST_MODEL,
    max_tokens: int = 2048,
    user_id: Optional[str] = None,
    org_id:  Optional[str] = None,
) -> tuple[str, int]:
    """Call InferenceEngine and return (text, total_tokens)."""
    req = CompletionRequest(
        messages=[
            Message(role="system", content=system),
            Message(role="user",   content=user),
        ],
        model=model,
        max_tokens=max_tokens,
        temperature=0.3,
    )
    resp = await _inference.complete(req, user_id=user_id, org_id=org_id, auto_tools=False)
    text   = resp.content if isinstance(resp.content, str) else str(resp.content)
    tokens = getattr(resp.usage, "total_tokens", 0) if resp.usage else 0
    return text, tokens


# ── 1. Idea Intake Agent ──────────────────────────────────────────────────────

async def run_idea_intake(
    conn: asyncpg.Connection,
    plan_id: str,
    org_id: str,
    user_id: str,
    idea_raw: str,
    industry: Optional[str],
    stage: str,
) -> dict[str, Any]:
    """
    Progressive discovery: ask minimal clarifying questions, extract structured
    data from the idea, store USER-sourced facts.
    Returns extracted structure.
    """
    t0 = time.monotonic()
    idea_clean = _sanitize(idea_raw)

    system = (
        "You are a business analyst specializing in startup idea validation. "
        "Extract structured information from the user's business idea. "
        "Return ONLY valid JSON with keys: "
        "title, problem_statement, solution, target_customers, value_proposition, "
        "revenue_model, industry (if not provided), clarifying_questions (list of up to 3). "
        "Never add extra commentary outside the JSON."
    )
    prompt = (
        f"Business idea: {idea_clean}\n"
        f"Industry hint: {industry or 'not specified'}\n"
        f"Stage: {stage}"
    )

    text, tokens = await _complete(system, prompt, model=_FAST_MODEL,
                                   user_id=user_id, org_id=org_id)
    data = _extract_json(text)

    elapsed = int((time.monotonic() - t0) * 1000)
    title   = data.get("title", idea_clean[:60])

    # Store USER-sourced facts
    user_facts = {
        "problem_statement":   data.get("problem_statement", ""),
        "solution":            data.get("solution", ""),
        "target_customers":    data.get("target_customers", ""),
        "value_proposition":   data.get("value_proposition", ""),
        "revenue_model":       data.get("revenue_model", ""),
    }
    for key, val in user_facts.items():
        if val:
            await conn.execute(
                """
                INSERT INTO bp_facts
                    (plan_id, organization_id, fact_key, value, source_type,
                     status, confidence, section, created_by)
                VALUES ($1,$2,$3,$4,'USER','UNVERIFIED',0.8,'intake','idea_intake')
                ON CONFLICT DO NOTHING
                """,
                plan_id, org_id, key, json.dumps(val),
            )

    # Update plan title
    await conn.execute(
        "UPDATE bp_plans SET title=$1, updated_at=NOW() WHERE id=$2",
        title, plan_id,
    )

    # Upsert section
    await _upsert_section(conn, plan_id, org_id, "intake",
                          "فكرة العمل", text, tokens, elapsed, "idea_intake")
    return data


# ── 2. Company Description Agent ─────────────────────────────────────────────

async def run_company_description(
    conn: asyncpg.Connection,
    plan_id: str, org_id: str, user_id: str,
    idea_raw: str, industry: Optional[str],
    intake_data: dict,
) -> str:
    t0 = time.monotonic()

    system = (
        "You are a professional business writer. "
        "Write a concise company description section for a business plan (300-500 words). "
        "Cover: company overview, mission, vision, core product/service, legal structure "
        "(recommended), founding team assumptions, and geographic focus. "
        "Format in Markdown. Mark any assumptions clearly with [ASSUMPTION]."
    )
    prompt = (
        f"Business idea: {_sanitize(idea_raw)}\n"
        f"Industry: {industry or 'Unknown'}\n"
        f"Extracted data: {json.dumps(intake_data, ensure_ascii=False)}"
    )

    text, tokens = await _complete(system, prompt, model=_BEST_MODEL,
                                   user_id=user_id, org_id=org_id)
    elapsed = int((time.monotonic() - t0) * 1000)

    # Tag assumptions in facts
    if "[ASSUMPTION]" in text:
        await _record_assumption(conn, plan_id, org_id, "company_description",
                                 "company_description")

    await _upsert_section(conn, plan_id, org_id, "company_description",
                          "وصف الشركة", text, tokens, elapsed, "company_description")
    return text


# ── 3. Market Intelligence Agent ─────────────────────────────────────────────

async def run_market_intelligence(
    conn: asyncpg.Connection,
    plan_id: str, org_id: str, user_id: str,
    idea_raw: str, industry: Optional[str],
    company_summary: Optional[str],
    target_customers: Optional[str],
) -> str:
    t0 = time.monotonic()

    system = (
        "You are a market research analyst. "
        "Produce a Market Intelligence section for a business plan (400-600 words). "
        "Include: TAM / SAM / SOM estimates (with sources or [ASSUMPTION] tags), "
        "market growth rate, key trends, regulatory environment, customer segments. "
        "Format in Markdown. Label every unverified number as [ASSUMPTION] or [MISSING]."
    )
    prompt = (
        f"Idea: {_sanitize(idea_raw)}\n"
        f"Industry: {industry or 'Unknown'}\n"
        f"Company summary: {company_summary or 'N/A'}\n"
        f"Target customers: {target_customers or 'N/A'}"
    )

    text, tokens = await _complete(system, prompt, model=_BEST_MODEL,
                                   user_id=user_id, org_id=org_id)
    elapsed = int((time.monotonic() - t0) * 1000)

    # Extract TAM/SAM/SOM as AI_INFERENCE facts
    for key in ["tam", "sam", "som"]:
        pattern = re.search(rf"\b{key.upper()}\b.*?\$[\d,\.]+\s*(?:B|M|K)?", text, re.IGNORECASE)
        if pattern:
            await conn.execute(
                """
                INSERT INTO bp_facts
                    (plan_id, organization_id, fact_key, value, source_type,
                     status, confidence, section, created_by)
                VALUES ($1,$2,$3,$4,'AI_INFERENCE','ASSUMPTION',0.4,'market_intelligence','market_intelligence')
                ON CONFLICT DO NOTHING
                """,
                plan_id, org_id, f"market_{key}", json.dumps(pattern.group()),
            )

    await _upsert_section(conn, plan_id, org_id, "market_intelligence",
                          "تحليل السوق", text, tokens, elapsed, "market_intelligence")
    return text


# ── 4. Competitor Intelligence Agent ─────────────────────────────────────────

async def run_competitor_intelligence(
    conn: asyncpg.Connection,
    plan_id: str, org_id: str, user_id: str,
    idea_raw: str, industry: Optional[str],
    company_summary: Optional[str],
    market_summary: Optional[str],
) -> str:
    t0 = time.monotonic()

    system = (
        "You are a competitive intelligence analyst. "
        "Identify 3-5 key competitors and produce a Competitor Intelligence section (400-600 words). "
        "For each competitor include: name, product/service, pricing (or [UNKNOWN]), "
        "strengths, weaknesses, market position. "
        "End with a competitive advantage analysis for our business. "
        "Format in Markdown. Return competitors as a JSON array after the markdown section "
        "under the heading '### COMPETITORS_JSON' — each item: "
        "{name, website, description, strengths[], weaknesses[], pricing, market_position}."
    )
    prompt = (
        f"Idea: {_sanitize(idea_raw)}\n"
        f"Industry: {industry or 'Unknown'}\n"
        f"Company: {company_summary or 'N/A'}\n"
        f"Market: {market_summary or 'N/A'}"
    )

    text, tokens = await _complete(system, prompt, model=_BEST_MODEL,
                                   user_id=user_id, org_id=org_id, max_tokens=3000)
    elapsed = int((time.monotonic() - t0) * 1000)

    # Extract and store competitor records
    json_match = re.search(r"### COMPETITORS_JSON\s*```(?:json)?\s*(\[.*?\])\s*```",
                           text, re.DOTALL)
    if not json_match:
        json_match = re.search(r"### COMPETITORS_JSON\s*(\[.*?\])", text, re.DOTALL)
    if json_match:
        try:
            competitors = json.loads(json_match.group(1))
            for c in competitors[:6]:  # cap at 6
                await conn.execute(
                    """
                    INSERT INTO bp_competitors
                        (plan_id, organization_id, name, website, description,
                         strengths, weaknesses, pricing, market_position)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                    """,
                    plan_id, org_id,
                    str(c.get("name", ""))[:200],
                    str(c.get("website", "") or "")[:500] or None,
                    str(c.get("description", ""))[:1000] or None,
                    json.dumps(c.get("strengths", [])),
                    json.dumps(c.get("weaknesses", [])),
                    str(c.get("pricing", "") or "")[:200] or None,
                    str(c.get("market_position", "") or "")[:200] or None,
                )
        except (json.JSONDecodeError, Exception):
            log.warning("competitor_intelligence: failed to parse COMPETITORS_JSON")

    # Strip the JSON block from the markdown
    clean_text = re.sub(r"### COMPETITORS_JSON.*", "", text, flags=re.DOTALL).strip()
    await _upsert_section(conn, plan_id, org_id, "competitor_intelligence",
                          "تحليل المنافسين", clean_text, tokens, elapsed, "competitor_intelligence")
    return clean_text


# ── 5. Offer & Pricing Agent ──────────────────────────────────────────────────

async def run_offer_pricing(
    conn: asyncpg.Connection,
    plan_id: str, org_id: str, user_id: str,
    idea_raw: str, target_customers: Optional[str],
    market_summary: Optional[str], competitors: list[dict],
) -> str:
    t0 = time.monotonic()

    comp_names = ", ".join(c.get("name", "") for c in competitors[:5])
    system = (
        "You are a pricing strategist. "
        "Write an Offer & Pricing section (300-500 words) covering: "
        "product/service offering tiers, pricing model (freemium/subscription/usage/one-time), "
        "price points with competitive justification, unit economics assumptions (CAC, LTV), "
        "and positioning strategy. "
        "Format in Markdown. Tag unvalidated numbers as [ASSUMPTION]."
    )
    prompt = (
        f"Idea: {_sanitize(idea_raw)}\n"
        f"Customers: {target_customers or 'N/A'}\n"
        f"Market: {market_summary or 'N/A'}\n"
        f"Competitors: {comp_names or 'Unknown'}"
    )

    text, tokens = await _complete(system, prompt, model=_BEST_MODEL,
                                   user_id=user_id, org_id=org_id)
    elapsed = int((time.monotonic() - t0) * 1000)
    await _upsert_section(conn, plan_id, org_id, "offer_pricing",
                          "العرض والتسعير", text, tokens, elapsed, "offer_pricing")
    return text


# ── 6. Go-To-Market Agent ─────────────────────────────────────────────────────

async def run_go_to_market(
    conn: asyncpg.Connection,
    plan_id: str, org_id: str, user_id: str,
    company_summary: Optional[str], offer_summary: Optional[str],
    target_customers: Optional[str], market_summary: Optional[str],
) -> str:
    t0 = time.monotonic()

    system = (
        "You are a go-to-market strategist. "
        "Write a GTM section (400-600 words) covering: "
        "launch strategy, distribution channels, sales motion (PLG/SLG/channel), "
        "marketing channels and budget allocation (%), "
        "key metrics (MQLs, SQL, conversion rates), 6-month milestone plan. "
        "Format in Markdown. Tag assumptions."
    )
    prompt = (
        f"Company: {company_summary or 'N/A'}\n"
        f"Offer: {offer_summary or 'N/A'}\n"
        f"Customers: {target_customers or 'N/A'}\n"
        f"Market: {market_summary or 'N/A'}"
    )

    text, tokens = await _complete(system, prompt, model=_BEST_MODEL,
                                   user_id=user_id, org_id=org_id)
    elapsed = int((time.monotonic() - t0) * 1000)
    await _upsert_section(conn, plan_id, org_id, "go_to_market",
                          "استراتيجية الإطلاق", text, tokens, elapsed, "go_to_market")
    return text


# ── 7. Operations & Finance Agent ────────────────────────────────────────────

async def run_ops_finance(
    conn: asyncpg.Connection,
    plan_id: str, org_id: str, user_id: str,
    company_summary: Optional[str], offer_summary: Optional[str],
    stage: str,
) -> str:
    t0 = time.monotonic()

    system = (
        "You are a financial analyst and operations expert. "
        "Write an Operations & Finance section (400-600 words) covering: "
        "team structure and key hires, tech stack, operating costs breakdown, "
        "12-month financial projection (revenue, COGS, gross margin, burn rate), "
        "funding requirements and use of funds. "
        "Format in Markdown with a simple P&L table. Tag all projections as [ASSUMPTION]."
    )
    prompt = (
        f"Company: {company_summary or 'N/A'}\n"
        f"Offer: {offer_summary or 'N/A'}\n"
        f"Stage: {stage}"
    )

    text, tokens = await _complete(system, prompt, model=_BEST_MODEL,
                                   user_id=user_id, org_id=org_id, max_tokens=3000)
    elapsed = int((time.monotonic() - t0) * 1000)
    await _upsert_section(conn, plan_id, org_id, "ops_finance",
                          "العمليات والتمويل", text, tokens, elapsed, "ops_finance")
    return text


# ── 8. Business Plan Assembly Agent ──────────────────────────────────────────

async def run_assembly(
    conn: asyncpg.Connection,
    plan_id: str, org_id: str, user_id: str,
    sections: dict[str, str],
    facts: list[dict],
) -> str:
    t0 = time.monotonic()

    section_text = "\n\n---\n\n".join(
        f"## {k}\n{v}" for k, v in sections.items() if v
    )
    assumptions = [f for f in facts if f.get("status") in ("ASSUMPTION", "MISSING")]
    assumption_list = "\n".join(
        f"- [{f['status']}] {f['fact_key']}: {f['value']}"
        for f in assumptions[:20]
    )

    system = (
        "You are a senior business plan writer. "
        "Assemble the provided sections into a coherent, polished business plan. "
        "Add an Executive Summary at the top (150-200 words). "
        "Ensure narrative flow between sections. "
        "Include a final 'Key Assumptions & Risks' section listing open assumptions. "
        "Format the complete plan in Markdown."
    )
    prompt = (
        f"SECTIONS:\n{section_text}\n\n"
        f"OPEN ASSUMPTIONS:\n{assumption_list or 'None identified'}"
    )

    text, tokens = await _complete(system, prompt, model=_BEST_MODEL,
                                   user_id=user_id, org_id=org_id, max_tokens=6000)
    elapsed = int((time.monotonic() - t0) * 1000)
    await _upsert_section(conn, plan_id, org_id, "full_plan",
                          "الخطة الكاملة", text, tokens, elapsed, "assembly")
    return text


# ── 9. Assumption Auditor Agent ───────────────────────────────────────────────

async def run_assumption_auditor(
    conn: asyncpg.Connection,
    plan_id: str, org_id: str, user_id: str,
    plan_content: str,
    facts: list[dict],
) -> str:
    t0 = time.monotonic()

    assumptions = [f for f in facts if f.get("status") in ("ASSUMPTION", "UNVERIFIED")]

    system = (
        "You are an independent business plan auditor. "
        "Review the business plan and flag: "
        "1. All unverified claims presented as facts. "
        "2. Missing critical information (marked [MISSING]). "
        "3. Internal inconsistencies. "
        "4. Overly optimistic projections. "
        "Output a structured audit report in Markdown with sections: "
        "## Critical Issues, ## Assumptions to Validate, ## Missing Data, ## Recommendations. "
        "Be rigorous — investors will scrutinize this."
    )
    known = "\n".join(f"- {a['fact_key']}: {a['value']}" for a in assumptions[:20])
    prompt = (
        f"PLAN:\n{plan_content[:6000]}\n\n"
        f"KNOWN ASSUMPTIONS:\n{known or 'None logged'}"
    )

    text, tokens = await _complete(system, prompt, model=_BEST_MODEL,
                                   user_id=user_id, org_id=org_id, max_tokens=3000)
    elapsed = int((time.monotonic() - t0) * 1000)
    await _upsert_section(conn, plan_id, org_id, "assumption_audit",
                          "تدقيق الافتراضات", text, tokens, elapsed, "assumption_auditor")
    return text


# ── 10. Adversarial Reviewer Agent ───────────────────────────────────────────

async def run_adversarial_reviewer(
    conn: asyncpg.Connection,
    plan_id: str, org_id: str, user_id: str,
    plan_content: str,
    score: int,
) -> str:
    t0 = time.monotonic()

    system = (
        "You are a seasoned venture capitalist and devil's advocate. "
        "Your job is to find every reason this business plan could FAIL. "
        "Write a hard-hitting Adversarial Review (400-600 words) covering: "
        "fatal flaws, market timing risks, competitive threats, execution risks, "
        "financial sustainability questions, team gaps, and regulatory red flags. "
        "End with 5 specific questions the founder must answer before seeking funding. "
        "Format in Markdown. Do not soften your critique."
    )
    prompt = (
        f"Current readiness score: {score}/100\n\n"
        f"PLAN:\n{plan_content[:6000]}"
    )

    text, tokens = await _complete(system, prompt, model=_BEST_MODEL,
                                   user_id=user_id, org_id=org_id, max_tokens=3000)
    elapsed = int((time.monotonic() - t0) * 1000)
    await _upsert_section(conn, plan_id, org_id, "adversarial_review",
                          "مراجعة المخاطر", text, tokens, elapsed, "adversarial_reviewer")
    return text


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _upsert_section(
    conn: asyncpg.Connection,
    plan_id: str,
    org_id: str,
    section_key: str,
    title: str,
    content: str,
    tokens: int,
    elapsed_ms: int,
    agent_name: str,
) -> None:
    await conn.execute(
        """
        INSERT INTO bp_sections
            (plan_id, organization_id, section_key, title, content,
             status, agent_name, tokens_used, elapsed_ms)
        VALUES ($1,$2,$3,$4,$5,'COMPLETED',$6,$7,$8)
        ON CONFLICT (plan_id, section_key) DO UPDATE SET
            content=EXCLUDED.content, status='COMPLETED',
            tokens_used=EXCLUDED.tokens_used, elapsed_ms=EXCLUDED.elapsed_ms,
            updated_at=NOW()
        """,
        plan_id, org_id, section_key, title, content, agent_name, tokens, elapsed_ms,
    )


async def _record_assumption(
    conn: asyncpg.Connection,
    plan_id: str,
    org_id: str,
    fact_key: str,
    agent_name: str,
) -> None:
    await conn.execute(
        """
        INSERT INTO bp_facts
            (plan_id, organization_id, fact_key, value, source_type,
             status, confidence, created_by)
        VALUES ($1,$2,$3,'true','AI_INFERENCE','ASSUMPTION',0.3,$4)
        ON CONFLICT DO NOTHING
        """,
        plan_id, org_id, f"{fact_key}_has_assumptions", agent_name,
    )
