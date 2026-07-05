"""
AgentRuntime — reusable base for all AI agents.

Every agent owns:
- provider / model preference
- system prompt
- registered tools
- memory scope
- execution policy (max rounds, timeout)
- permissions

Future agents inherit AgentRuntime and override hooks.

Usage::

    class ResearchAgent(AgentRuntime):
        async def on_tool_result(self, result: ToolResult) -> str | None:
            # post-process tool results
            return result.output

    agent  = ResearchAgent(config=AgentConfig(name="researcher", ...))
    result = await agent.run("Find the latest AI papers")
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Optional

from app.ai.models import (
    CompletionRequest, CompletionResponse, Message, ToolSchema,
)
from app.core.ai.tools.executor import ToolResult, executor as default_executor
from app.core.ai.memory.types import MemoryType

log = logging.getLogger(__name__)


@dataclass
class AgentConfig:
    name:            str
    system_prompt:   str          = ""
    provider_id:     Optional[str] = None
    model:           Optional[str] = None
    max_tokens:      int           = 4096
    temperature:     float         = 0.7
    max_rounds:      int           = 8         # agentic loop limit
    timeout_s:       float         = 120.0
    memory_type:     MemoryType    = MemoryType.agent
    tools:           list[str]     = field(default_factory=list)   # tool names to enable
    memory_enabled:  bool          = False
    conversation_id: Optional[str] = None
    agent_id:        Optional[str] = None
    metadata:        dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentRunResult:
    success:      bool
    content:      str
    tool_calls:   list[dict] = field(default_factory=list)
    rounds:       int        = 0
    error:        Optional[str] = None
    conversation_id: Optional[str] = None
    usage:        Optional[dict] = None


class AgentRuntime:
    """
    Base agent execution runtime.

    Subclass to override hooks and add domain-specific behaviour.
    All AI calls go through the platform registry — no direct provider imports.
    """

    def __init__(
        self,
        config: AgentConfig,
        pool=None,
        executor=None,
    ) -> None:
        self.config   = config
        self._pool    = pool
        self._executor = executor or default_executor
        self._run_id   = str(uuid.uuid4())

    # ── Hooks (override in subclasses) ────────────────────────────────────────

    async def on_start(self, prompt: str) -> str:
        """Called with the user prompt before the first LLM call. Return enriched prompt."""
        return prompt

    async def on_tool_result(self, result: ToolResult) -> Optional[str]:
        """Called after each tool execution. Return a comment to inject or None."""
        return None

    async def on_response(self, response: CompletionResponse) -> None:
        """Called with each LLM response before continuing the loop."""

    async def on_complete(self, result: AgentRunResult) -> None:
        """Called when the agent run finishes (success or error)."""

    # ── Primary API ───────────────────────────────────────────────────────────

    async def run(
        self,
        prompt: str,
        *,
        user_id: Optional[str] = None,
    ) -> AgentRunResult:
        """
        Run the agent until done or max_rounds reached.
        Returns a structured AgentRunResult.
        """
        from app.core.ai.registry.registry import platform_registry
        from app.ai.models import ProviderID

        prompt = await self.on_start(prompt)

        # Resolve tools
        tool_schemas: list[ToolSchema] = []
        if self.config.tools:
            for name in self.config.tools:
                schema = self._executor.get_schema(name)
                if schema:
                    tool_schemas.append(schema)

        messages: list[Message] = [Message(role="user", content=prompt)]
        system   = self.config.system_prompt or None
        all_tool_calls: list[dict] = []
        last_response: Optional[CompletionResponse] = None
        rounds = 0

        try:
            for round_num in range(self.config.max_rounds):
                rounds = round_num + 1

                provider_enum = None
                if self.config.provider_id:
                    try:
                        provider_enum = ProviderID(self.config.provider_id)
                    except ValueError:
                        pass  # openrouter/local — pass as-is via model string

                req = CompletionRequest(
                    messages=messages,
                    system=system,
                    provider=provider_enum,
                    model=self.config.model,
                    max_tokens=self.config.max_tokens,
                    temperature=self.config.temperature,
                    tools=tool_schemas or None,
                    timeout=self.config.timeout_s,
                    memory_enabled=self.config.memory_enabled,
                    conversation_id=self.config.conversation_id,
                )

                resp, provider_used = await platform_registry.complete_with_events(
                    req, request_id=self._run_id
                )
                last_response = resp
                await self.on_response(resp)

                # No tool calls → done
                if not resp.tool_calls:
                    break

                # Execute tool calls
                tool_messages: list[Message] = [
                    Message(role="assistant", content=resp.content or "")
                ]

                for tc in resp.tool_calls:
                    all_tool_calls.append(tc.model_dump())
                    result = await self._executor.execute(
                        tc.name, tc.arguments,
                        call_id=tc.id, user_id=user_id,
                    )
                    comment = await self.on_tool_result(result)
                    tool_messages.append(Message(
                        role="tool",
                        content=result.to_message_content(),
                        name=tc.name,
                    ))
                    if comment:
                        tool_messages.append(Message(role="user", content=comment))

                messages = messages + tool_messages

            result = AgentRunResult(
                success=True,
                content=last_response.content if last_response else "",
                tool_calls=all_tool_calls,
                rounds=rounds,
                conversation_id=self.config.conversation_id,
                usage=last_response.usage.model_dump() if last_response else None,
            )

        except Exception as exc:
            log.error("AgentRuntime[%s] failed: %s", self.config.name, exc)
            result = AgentRunResult(
                success=False,
                content="",
                rounds=rounds,
                error=str(exc),
            )

        await self.on_complete(result)
        return result

    async def stream(
        self,
        prompt: str,
        *,
        user_id: Optional[str] = None,
    ) -> AsyncGenerator[dict, None]:
        """
        Streaming variant — yields SSE-compatible dicts.
        Tool calls are still executed server-side between stream segments.
        """
        from app.core.ai.registry.registry import platform_registry
        from app.ai.models import ProviderID

        prompt = await self.on_start(prompt)
        messages: list[Message] = [Message(role="user", content=prompt)]
        system   = self.config.system_prompt or None

        tool_schemas: list[ToolSchema] = []
        if self.config.tools:
            for name in self.config.tools:
                schema = self._executor.get_schema(name)
                if schema:
                    tool_schemas.append(schema)

        for round_num in range(self.config.max_rounds):
            provider_enum = None
            if self.config.provider_id:
                try:
                    provider_enum = ProviderID(self.config.provider_id)
                except ValueError:
                    pass

            req = CompletionRequest(
                messages=messages,
                system=system,
                provider=provider_enum,
                model=self.config.model,
                max_tokens=self.config.max_tokens,
                temperature=self.config.temperature,
                tools=tool_schemas or None,
                timeout=self.config.timeout_s,
            )

            accumulated_tools = []
            async for chunk in platform_registry.stream_with_events(req):
                yield chunk.model_dump()
                if chunk.type == "tool_call" and chunk.tool_call:
                    accumulated_tools.append(chunk.tool_call)

            if not accumulated_tools:
                break

            # Execute tool calls and continue
            tool_messages: list[Message] = [Message(role="assistant", content="")]
            for tc in accumulated_tools:
                result = await self._executor.execute(
                    tc.name, tc.arguments, call_id=tc.id, user_id=user_id,
                )
                yield {"type": "tool_result", "tool_name": tc.name, "result": result.output}
                tool_messages.append(Message(role="tool", content=result.to_message_content(), name=tc.name))

            messages = messages + tool_messages
