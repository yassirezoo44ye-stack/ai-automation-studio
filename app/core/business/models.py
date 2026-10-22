"""
Business Plan & Validation Engine — Pydantic models.
Used for API request/response and internal data transfer.
"""
from __future__ import annotations

from enum import Enum
from typing import Any
from pydantic import BaseModel, Field


# ── Enumerations ──────────────────────────────────────────────────────────────

class PlanStage(str, Enum):
    IDEA   = "IDEA"
    MVP    = "MVP"
    GROWTH = "GROWTH"
    SCALE  = "SCALE"


class PlanStatus(str, Enum):
    DRAFT      = "DRAFT"
    GENERATING = "GENERATING"
    COMPLETED  = "COMPLETED"
    FAILED     = "FAILED"
    PAUSED     = "PAUSED"


class FactSourceType(str, Enum):
    USER          = "USER"
    WEB           = "WEB"
    CALCULATION   = "CALCULATION"
    DOCUMENT      = "DOCUMENT"
    AI_INFERENCE  = "AI_INFERENCE"


class FactStatus(str, Enum):
    VERIFIED    = "VERIFIED"
    UNVERIFIED  = "UNVERIFIED"
    ASSUMPTION  = "ASSUMPTION"
    MISSING     = "MISSING"
    CONFLICTING = "CONFLICTING"


class SectionStatus(str, Enum):
    PENDING      = "PENDING"
    RUNNING      = "RUNNING"
    COMPLETED    = "COMPLETED"
    FAILED       = "FAILED"
    NEEDS_REVIEW = "NEEDS_REVIEW"


# ── API request/response models ───────────────────────────────────────────────

class CreatePlanRequest(BaseModel):
    idea_raw:  str = Field(..., min_length=10, max_length=4000,
                           description="Free-text description of the business idea")
    industry:  str | None = None
    stage:     PlanStage     = PlanStage.IDEA


class PlanOut(BaseModel):
    id:              str
    title:           str
    idea_raw:        str
    industry:        str | None
    stage:           str
    status:          str
    readiness_score: int | None
    workflow_run_id: str | None
    created_at:      str
    updated_at:      str


class FactOut(BaseModel):
    id:           str
    plan_id:      str
    fact_key:     str
    value:        Any
    source_type:  str
    source_url:   str | None
    source_note:  str | None
    status:       str
    confidence:   float
    section:      str | None
    created_by:   str | None
    created_at:   str


class SectionOut(BaseModel):
    id:           str
    plan_id:      str
    section_key:  str
    title:        str
    content:      str
    status:       str
    agent_name:   str | None
    model_used:   str | None
    tokens_used:  int
    elapsed_ms:   int | None
    retry_count:  int
    error_msg:    str | None
    updated_at:   str


class CompetitorOut(BaseModel):
    id:              str
    plan_id:         str
    name:            str
    website:         str | None
    description:     str | None
    strengths:       list[str]
    weaknesses:      list[str]
    pricing:         str | None
    market_position: str | None
    source_url:      str | None
    verified:        bool


class ScoreOut(BaseModel):
    overall_score:    int
    breakdown:        dict[str, Any]
    evidence_count:   int
    assumption_count: int
    missing_count:    int
    computed_at:      str


class PlanDetailOut(BaseModel):
    plan:        PlanOut
    sections:    list[SectionOut]
    facts:       list[FactOut]
    competitors: list[CompetitorOut]
    score:       ScoreOut | None


class RetryRequest(BaseModel):
    section_keys: list[str] = Field(..., min_length=1,
                                    description="Section keys to re-run (Fix Loop)")


class ExportRequest(BaseModel):
    format:  str = Field("markdown", pattern=r"^(markdown|pdf|docx)$")
    variant: str = Field("standard", pattern=r"^(standard|investor|lender)$")


# ── Internal context packages (per-agent slices) ──────────────────────────────

class IdeaContext(BaseModel):
    """Minimal context for intake agent."""
    plan_id:  str
    idea_raw: str
    industry: str | None
    stage:    str


class MarketContext(BaseModel):
    """Context slice for Market Intelligence agent."""
    plan_id:          str
    idea_raw:         str
    industry:         str | None
    company_summary:  str | None
    target_customers: str | None


class CompetitorContext(BaseModel):
    """Context slice for Competitor Intelligence agent."""
    plan_id:          str
    idea_raw:         str
    industry:         str | None
    company_summary:  str | None
    market_summary:   str | None


class OfferContext(BaseModel):
    """Context slice for Offer & Pricing agent."""
    plan_id:          str
    idea_raw:         str
    target_customers: str | None
    market_summary:   str | None
    competitors:      list[dict]


class GTMContext(BaseModel):
    """Context slice for Go-To-Market agent."""
    plan_id:          str
    company_summary:  str | None
    offer_summary:    str | None
    target_customers: str | None
    market_summary:   str | None


class OpsFinanceContext(BaseModel):
    """Context slice for Operations & Finance agent."""
    plan_id:         str
    company_summary: str | None
    offer_summary:   str | None
    stage:           str


class AssemblyContext(BaseModel):
    """Context passed to Business Plan Assembly agent."""
    plan_id:  str
    sections: dict[str, str]   # section_key → content
    facts:    list[dict]        # subset of fact records


class AuditContext(BaseModel):
    """Context for Assumption Auditor."""
    plan_id:      str
    plan_content: str           # full assembled plan markdown
    facts:        list[dict]


class AdversarialContext(BaseModel):
    """Context for Adversarial Reviewer."""
    plan_id:      str
    plan_content: str
    score:        int
