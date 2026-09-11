"""
Business Plan & Validation Engine — Export.

Generates Markdown (standard or investor/lender variant).
PDF/DOCX are marked as "Coming Soon" — placeholders only, no deletion.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import asyncpg

log = logging.getLogger(__name__)

# Section display order
_SECTION_ORDER = [
    "intake",
    "company_description",
    "market_intelligence",
    "competitor_intelligence",
    "offer_pricing",
    "go_to_market",
    "ops_finance",
    "assumption_audit",
    "adversarial_review",
]

_SECTION_TITLES_AR = {
    "intake":                  "فكرة العمل",
    "company_description":     "وصف الشركة",
    "market_intelligence":     "تحليل السوق",
    "competitor_intelligence": "تحليل المنافسين",
    "offer_pricing":           "العرض والتسعير",
    "go_to_market":            "استراتيجية الإطلاق",
    "ops_finance":             "العمليات والتمويل",
    "assumption_audit":        "تدقيق الافتراضات",
    "adversarial_review":      "مراجعة المخاطر",
    "full_plan":               "الخطة الكاملة",
}


async def export_plan(
    conn: asyncpg.Connection,
    plan_id: str,
    format_: str = "markdown",
    variant: str = "standard",
) -> tuple[str, str, str]:
    """
    Returns (content, filename, mime_type).
    format_: 'markdown' | 'pdf' | 'docx'
    variant: 'standard' | 'investor' | 'lender'
    """
    if format_ in ("pdf", "docx"):
        # Roadmap feature — not yet implemented
        raise NotImplementedError(f"{format_.upper()} export coming soon")

    # Fetch plan metadata
    plan = await conn.fetchrow(
        "SELECT title, idea_raw, industry, stage, readiness_score, created_at FROM bp_plans WHERE id=$1",
        plan_id,
    )
    if not plan:
        raise ValueError("Plan not found")

    # Prefer assembled full plan if available
    full = await conn.fetchrow(
        "SELECT content FROM bp_sections WHERE plan_id=$1 AND section_key='full_plan'",
        plan_id,
    )

    if full and variant == "standard":
        content = _wrap_markdown(plan, full["content"], variant)
    else:
        # Build section-by-section
        sections = await conn.fetch(
            """
            SELECT section_key, title, content, status, tokens_used
            FROM bp_sections WHERE plan_id=$1
            ORDER BY created_at
            """,
            plan_id,
        )
        sec_map = {r["section_key"]: r for r in sections}
        content = _build_sectioned(plan, sec_map, variant)

    # Add fact registry appendix for investor/lender variant
    if variant in ("investor", "lender"):
        facts_md = await _facts_appendix(conn, plan_id)
        content += "\n\n" + facts_md

    title_slug = (plan["title"] or "business-plan").replace(" ", "-").lower()[:40]
    filename   = f"{title_slug}-{variant}.md"
    return content, filename, "text/markdown; charset=utf-8"


def _wrap_markdown(plan: Any, body: str, variant: str) -> str:
    header = _header(plan, variant)
    return f"{header}\n\n{body}"


def _build_sectioned(plan: Any, sec_map: dict, variant: str) -> str:
    parts = [_header(plan, variant)]

    for key in _SECTION_ORDER:
        rec = sec_map.get(key)
        if not rec:
            continue
        if rec["status"] != "COMPLETED":
            continue
        # Investor variant: skip internal audit sections
        if variant == "investor" and key in ("assumption_audit",):
            continue
        title = _SECTION_TITLES_AR.get(key, rec["title"])
        parts.append(f"\n## {title}\n\n{rec['content']}")

    return "\n".join(parts)


def _header(plan: Any, variant: str) -> str:
    variant_label = {
        "standard": "خطة الأعمال",
        "investor": "خطة الأعمال — نسخة المستثمرين",
        "lender":   "خطة الأعمال — نسخة الممولين",
    }.get(variant, "خطة الأعمال")

    score_line = (
        f"**درجة الجاهزية:** {plan['readiness_score']}/100"
        if plan["readiness_score"] is not None
        else ""
    )
    return (
        f"# {plan['title'] or 'خطة الأعمال'}\n\n"
        f"**{variant_label}**  \n"
        f"**الصناعة:** {plan['industry'] or 'غير محدد'}  \n"
        f"**المرحلة:** {plan['stage']}  \n"
        f"{score_line}  \n"
        f"**تاريخ الإنشاء:** {str(plan['created_at'])[:10]}"
    )


async def _facts_appendix(conn: asyncpg.Connection, plan_id: str) -> str:
    facts = await conn.fetch(
        """
        SELECT fact_key, value, source_type, status, confidence
        FROM bp_facts WHERE plan_id=$1
        ORDER BY status, fact_key
        """,
        plan_id,
    )
    if not facts:
        return ""

    lines = ["## ملحق: سجل الحقائق والافتراضات\n",
             "| الحقيقة | القيمة | المصدر | الحالة | الثقة |",
             "|--------|--------|--------|--------|-------|"]
    for f in facts:
        val = json.loads(f["value"]) if isinstance(f["value"], str) else f["value"]
        val_str = str(val)[:80]
        lines.append(
            f"| {f['fact_key']} | {val_str} | {f['source_type']} "
            f"| {f['status']} | {f['confidence']:.0%} |"
        )
    return "\n".join(lines)
