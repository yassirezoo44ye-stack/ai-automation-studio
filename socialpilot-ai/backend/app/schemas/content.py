from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.content_generation import GenerationStatus, GenerationType
from app.models.content_item import ContentItemStatus
from app.schemas.common import ORMModel

# Free-text fields are capped well above any legitimate strategy brief, but
# far below "someone is trying to blow up the prompt/DB row" territory —
# Step 10's "excessive payload sizes" concern.
_TEXT_MAX = 4000
_SHORT_MAX = 255


# --------------------------------------------------------------------------- #
# Content Strategy
# --------------------------------------------------------------------------- #

class ContentStrategyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=_SHORT_MAX)
    business_description: str = Field(default="", max_length=_TEXT_MAX)
    target_audience: str = Field(default="", max_length=_TEXT_MAX)
    goals: str = Field(default="", max_length=_TEXT_MAX)
    tone: str = Field(default="engaging", max_length=80)
    language: str = Field(default="english", max_length=40)
    brand_voice: str = Field(default="", max_length=_TEXT_MAX)
    content_preferences: dict[str, Any] = Field(default_factory=dict)


class ContentStrategyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=_SHORT_MAX)
    business_description: str | None = Field(default=None, max_length=_TEXT_MAX)
    target_audience: str | None = Field(default=None, max_length=_TEXT_MAX)
    goals: str | None = Field(default=None, max_length=_TEXT_MAX)
    tone: str | None = Field(default=None, max_length=80)
    language: str | None = Field(default=None, max_length=40)
    brand_voice: str | None = Field(default=None, max_length=_TEXT_MAX)
    content_preferences: dict[str, Any] | None = None


class ContentStrategyPublic(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    business_description: str
    target_audience: str
    goals: str
    tone: str
    language: str
    brand_voice: str
    content_preferences: dict[str, Any]
    created_at: datetime
    updated_at: datetime


# --------------------------------------------------------------------------- #
# Content Pillar
# --------------------------------------------------------------------------- #

class ContentPillarCreate(BaseModel):
    name: str = Field(min_length=1, max_length=_SHORT_MAX)
    description: str | None = Field(default=None, max_length=_TEXT_MAX)
    priority: int = Field(default=0, ge=0, le=1000)


class ContentPillarUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=_SHORT_MAX)
    description: str | None = Field(default=None, max_length=_TEXT_MAX)
    priority: int | None = Field(default=None, ge=0, le=1000)


class ContentPillarPublic(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    strategy_id: uuid.UUID
    name: str
    description: str | None
    priority: int
    created_at: datetime
    updated_at: datetime


# --------------------------------------------------------------------------- #
# Generation requests
# --------------------------------------------------------------------------- #

class GenerateIdeasRequest(BaseModel):
    strategy_id: uuid.UUID
    pillar_id: uuid.UUID | None = None
    platform: str | None = Field(default=None, max_length=40)
    tone: str | None = Field(default=None, max_length=80)
    language: str | None = Field(default=None, max_length=40)
    count: int = Field(default=5, ge=1, le=10)


class GeneratePostRequest(BaseModel):
    strategy_id: uuid.UUID
    pillar_id: uuid.UUID | None = None
    platform: str = Field(max_length=40)
    content_type: str = Field(default="post", max_length=40)
    tone: str | None = Field(default=None, max_length=80)
    language: str | None = Field(default=None, max_length=40)
    # Optional freeform brief carried over from an idea (e.g. its "concept"),
    # so "generate a post from this idea" doesn't need a separate endpoint.
    brief: str | None = Field(default=None, max_length=_TEXT_MAX)


# --------------------------------------------------------------------------- #
# AI structured-output validation (Step 6: validated before persistence)
# --------------------------------------------------------------------------- #

class GeneratedIdea(BaseModel):
    title: str = Field(min_length=1, max_length=_SHORT_MAX)
    hook: str = Field(min_length=1, max_length=_TEXT_MAX)
    concept: str = Field(min_length=1, max_length=_TEXT_MAX)
    pillar: str = Field(min_length=1, max_length=_SHORT_MAX)
    suggested_platform: str = Field(min_length=1, max_length=40)
    cta: str = Field(min_length=1, max_length=_SHORT_MAX)


class GeneratedIdeasResult(BaseModel):
    ideas: list[GeneratedIdea] = Field(min_length=1, max_length=10)


class GeneratedPost(BaseModel):
    hook: str = Field(min_length=1, max_length=_TEXT_MAX)
    body: str = Field(min_length=1, max_length=_TEXT_MAX)
    cta: str = Field(min_length=1, max_length=_SHORT_MAX)
    hashtags: list[str] = Field(default_factory=list, max_length=30)
    platform: str = Field(min_length=1, max_length=40)
    media_concept: str = Field(default="", max_length=_TEXT_MAX)


GENERATED_IDEAS_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "ideas": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "hook": {"type": "string"},
                    "concept": {"type": "string"},
                    "pillar": {"type": "string"},
                    "suggested_platform": {"type": "string"},
                    "cta": {"type": "string"},
                },
                "required": ["title", "hook", "concept", "pillar", "suggested_platform", "cta"],
            },
        },
    },
    "required": ["ideas"],
}

GENERATED_POST_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "hook": {"type": "string"},
        "body": {"type": "string"},
        "cta": {"type": "string"},
        "hashtags": {"type": "array", "items": {"type": "string"}},
        "platform": {"type": "string"},
        "media_concept": {"type": "string"},
    },
    "required": ["hook", "body", "cta", "hashtags", "platform", "media_concept"],
}


# --------------------------------------------------------------------------- #
# Content Generation (audit/history record)
# --------------------------------------------------------------------------- #

class ContentGenerationPublic(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    strategy_id: uuid.UUID
    generation_type: GenerationType
    platform: str | None
    status: GenerationStatus
    model: str
    result: Any
    error: str | None
    created_at: datetime


# --------------------------------------------------------------------------- #
# Content Item
# --------------------------------------------------------------------------- #

class ContentItemCreate(BaseModel):
    strategy_id: uuid.UUID | None = None
    generation_id: uuid.UUID | None = None
    platform: str = Field(max_length=40)
    title: str | None = Field(default=None, max_length=_SHORT_MAX)
    body: str = Field(min_length=1, max_length=_TEXT_MAX)
    hashtags: list[str] = Field(default_factory=list, max_length=30)
    status: ContentItemStatus = ContentItemStatus.DRAFT
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContentItemUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=_SHORT_MAX)
    body: str | None = Field(default=None, min_length=1, max_length=_TEXT_MAX)
    hashtags: list[str] | None = Field(default=None, max_length=30)
    status: ContentItemStatus | None = None
    metadata: dict[str, Any] | None = None


class ContentItemPublic(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    strategy_id: uuid.UUID | None
    generation_id: uuid.UUID | None
    platform: str
    title: str | None
    body: str
    hashtags: list[str]
    status: ContentItemStatus
    metadata: dict[str, Any] = Field(validation_alias="metadata_", serialization_alias="metadata")
    created_at: datetime
    updated_at: datetime
