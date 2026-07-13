"""
Shared Pydantic models for the AI gateway.
All providers must accept CompletionRequest and return CompletionResponse.
"""
from __future__ import annotations

import uuid
from enum import Enum
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, Field


# ── Provider & model enums ────────────────────────────────────────────────────

class ProviderID(str, Enum):
    anthropic = "anthropic"
    openai    = "openai"
    gemini    = "gemini"


# ── Message primitives ────────────────────────────────────────────────────────

class TextPart(BaseModel):
    type: Literal["text"] = "text"
    text: str

class ImagePart(BaseModel):
    type: Literal["image_url"] = "image_url"
    url: str
    detail: Optional[str] = "auto"

class ToolUsePart(BaseModel):
    type: Literal["tool_use"] = "tool_use"
    id: str
    name: str
    input: dict[str, Any]

class ToolResultPart(BaseModel):
    type: Literal["tool_result"] = "tool_result"
    tool_use_id: str
    content: Union[str, list[TextPart]]
    is_error: bool = False

ContentPart = Union[TextPart, ImagePart, ToolUsePart, ToolResultPart]

class Message(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: Union[str, list[ContentPart]]
    name: Optional[str] = None


# ── Tool / function schema ────────────────────────────────────────────────────

class ToolParameter(BaseModel):
    type: str
    description: Optional[str] = None
    enum: Optional[list[str]] = None
    items: Optional[dict[str, Any]] = None

class ToolSchema(BaseModel):
    """Provider-agnostic tool definition (maps to all provider formats)."""
    name: str = Field(..., pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    description: str
    parameters: dict[str, Any]  # JSON Schema object with "properties" + "required"


# ── Gateway request ───────────────────────────────────────────────────────────

class CompletionRequest(BaseModel):
    messages: list[Message]

    # Provider selection — a plain string, not a closed enum: any provider_id
    # registered with PlatformProviderRegistry (built-in or a Plugin SDK
    # AI_PROVIDER-type plugin's) can be requested. ProviderID's 3 members
    # remain available as string constants for internal call sites; every
    # existing caller passing "anthropic"/"openai"/"gemini" is unaffected —
    # this is a type-widening only, not a routing-behavior change.
    provider: Optional[str] = None                  # None = use default
    model: Optional[str] = None                     # None = use provider default
    fallback_providers: list[str] = []

    # Generation parameters
    max_tokens: int = Field(2048, ge=1, le=32000)
    temperature: float = Field(0.7, ge=0.0, le=2.0)
    top_p: Optional[float] = Field(None, ge=0.0, le=1.0)
    system: Optional[str] = None

    # Features
    tools: Optional[list[ToolSchema]] = None
    stream: bool = False

    # Gateway features
    conversation_id: Optional[str] = None           # Link to stored conversation
    prompt_id: Optional[str] = None                 # Use a versioned prompt template
    prompt_variables: dict[str, str] = {}           # Variables for prompt template
    cache_ttl: Optional[int] = None                 # Cache response for N seconds
    memory_enabled: bool = False                    # Inject long-term memory context
    timeout: float = Field(60.0, ge=1.0, le=300.0)
    max_retries: int = Field(2, ge=0, le=5)


# ── Token / cost tracking ─────────────────────────────────────────────────────

class UsageStats(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    provider: str = ""
    model: str = ""
    cached: bool = False


# ── Tool call in response ─────────────────────────────────────────────────────

class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any]


# ── Gateway response ──────────────────────────────────────────────────────────

class CompletionResponse(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    content: str = ""
    tool_calls: list[ToolCall] = []
    finish_reason: str = "stop"
    usage: UsageStats = Field(default_factory=UsageStats)
    conversation_id: Optional[str] = None
    cached: bool = False


# ── Streaming chunk ───────────────────────────────────────────────────────────

class StreamChunk(BaseModel):
    type: Literal["delta", "tool_call", "usage", "done", "error", "conv_id"]
    text: Optional[str] = None
    tool_call: Optional[ToolCall] = None
    usage: Optional[UsageStats] = None
    error: Optional[str] = None
    conv_id: Optional[str] = None


# ── Prompt versioning ─────────────────────────────────────────────────────────

class PromptVersion(BaseModel):
    id: str
    prompt_id: str
    version: int
    system: Optional[str]
    user_template: Optional[str]
    variables: list[str]
    created_at: str
    is_active: bool


# ── Memory ────────────────────────────────────────────────────────────────────

class MemoryItem(BaseModel):
    id: str
    conversation_id: Optional[str]
    user_id: Optional[str]
    content: str
    importance: float = 1.0
    created_at: str
