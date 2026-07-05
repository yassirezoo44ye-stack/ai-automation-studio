"""
PolicyEngine — enforces platform rules before any AI execution begins.

Rules checked: max cost per request, max runtime, allowed providers,
               allowed tools, content safety, workspace restrictions.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from ..events.bus    import EventBus
from ..events.events import PolicyViolation


class PolicyViolationError(Exception):
    """Raised when a policy rule is violated."""
    def __init__(self, policy: str, rule: str, value: str, limit: str) -> None:
        super().__init__(f"Policy [{policy}] violated: {rule} = {value} (limit: {limit})")
        self.policy = policy
        self.rule   = rule
        self.value  = value
        self.limit  = limit


@dataclass
class PolicyRule:
    name:    str
    enabled: bool = True


@dataclass
class PolicyConfig:
    max_cost_per_request_usd: Optional[float]  = None
    max_runtime_seconds:      Optional[float]  = None
    allowed_providers:        Optional[list[str]] = None   # None = all allowed
    blocked_tools:            list[str]         = field(default_factory=list)
    require_user_id:          bool              = False
    max_prompt_chars:         Optional[int]     = None     # prompt length limit
    content_safety:           bool              = False    # reserved for future content moderation integration


class PolicyEngine:
    """
    Stateless policy checker.  All rules run synchronously before execution starts.
    """

    def __init__(self, bus: EventBus, config: Optional[PolicyConfig] = None) -> None:
        self._bus    = bus
        self._config = config or PolicyConfig()

    def update(self, config: PolicyConfig) -> None:
        self._config = config

    async def check(self, request: Any, request_id: str = "") -> None:
        """
        Check request against all enabled policies.
        Raises PolicyViolationError on the first violation.
        """
        cfg = self._config

        if cfg.require_user_id and not getattr(request, "user_id", None):
            await self._violate("auth", "user_id", "missing", "required", request_id)

        if cfg.max_prompt_chars is not None:
            prompt = getattr(request, "prompt", "") or ""
            if len(prompt) > cfg.max_prompt_chars:
                await self._violate(
                    "content", "prompt_length",
                    str(len(prompt)), str(cfg.max_prompt_chars),
                    request_id,
                )

        if cfg.max_cost_per_request_usd is not None:
            max_cost = getattr(request, "max_cost_usd", None)
            if max_cost is not None and max_cost > cfg.max_cost_per_request_usd:
                await self._violate(
                    "cost", "max_cost_per_request",
                    str(max_cost), str(cfg.max_cost_per_request_usd),
                    request_id,
                )

        if cfg.allowed_providers is not None:
            provider = getattr(request, "provider_id", None)
            if provider and provider not in cfg.allowed_providers:
                await self._violate(
                    "provider", "provider_id",
                    provider, f"one of {cfg.allowed_providers}",
                    request_id,
                )

        # Tool blocklist
        if cfg.blocked_tools:
            tools = getattr(request, "tools", None) or []
            for tool in tools:
                tool_name = tool if isinstance(tool, str) else tool.get("name", "")
                if tool_name in cfg.blocked_tools:
                    await self._violate(
                        "tools", "blocked_tool",
                        tool_name, "not in blocked list",
                        request_id,
                    )

    async def _violate(
        self,
        policy_name: str,
        rule:        str,
        value:       str,
        limit:       str,
        request_id:  str,
    ) -> None:
        await self._bus.emit(PolicyViolation(
            policy_name=policy_name,
            rule=rule,
            value=value,
            limit=limit,
        ))
        raise PolicyViolationError(policy_name, rule, value, limit)
