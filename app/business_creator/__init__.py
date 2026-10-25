"""Business Creator capability catalog.

This module is deliberately side-effect free: it does not invoke providers,
charge accounts, publish content, or start workflows. Runtime adapters must
be verified before an execution endpoint is exposed.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class BusinessCapability:
    id: str
    title: str
    engine: str
    deliverables: tuple[str, ...]
    status: str = "requires_runtime_verification"
    approval_required: bool = True


CAPABILITIES: tuple[BusinessCapability, ...] = (
    BusinessCapability("app", "Application or website", "app_builder", ("application", "preview")),
    BusinessCapability("store", "Online store", "app_builder", ("storefront", "product_catalog")),
    BusinessCapability("content", "Content agency", "agentos", ("content_plan", "draft_posts")),
    BusinessCapability("digital_product", "Digital product", "agentos", ("product_draft", "sales_copy")),
    BusinessCapability("youtube", "YouTube production", "youtube", ("topic_plan", "script", "production_brief")),
    BusinessCapability("marketing", "Business marketing", "agentos", ("campaign_plan", "draft_assets")),
    BusinessCapability("voiceover", "Voiceover", "external_voice_provider", ("voice_script", "audio_asset")),
    BusinessCapability("analytics", "Data analysis", "analyze_agent", ("analysis", "report")),
    BusinessCapability("freelance", "Freelance delivery", "business_lab", ("proposal", "delivery_plan")),
)


def list_capabilities() -> list[dict]:
    return [asdict(item) for item in CAPABILITIES]


def get_capability(capability_id: str) -> BusinessCapability:
    for capability in CAPABILITIES:
        if capability.id == capability_id:
            return capability
    raise ValueError(f"Unknown business capability: {capability_id}")


def plan_request(capability_id: str, description: str) -> dict:
    """Return a non-executing plan, never a fabricated completion result."""
    description = description.strip()
    if not 10 <= len(description) <= 3000:
        raise ValueError("Description must contain 10 to 3000 characters")
    capability = get_capability(capability_id)
    return {
        "capability": capability.id,
        "description": description,
        "engine": capability.engine,
        "expected_deliverables": list(capability.deliverables),
        "status": "planned_not_executed",
        "runtime_verified": False,
        "requires_approval_before_external_actions": True,
    }
