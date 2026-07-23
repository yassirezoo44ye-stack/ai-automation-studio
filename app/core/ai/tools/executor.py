"""
ToolExecutor — centralized tool execution with events, timeout, and structured results.

This wraps app.ai.tools (the decorator registry) and adds:
- Event emission (ToolCalled, ToolFinished)
- Sandbox enforcement (timeout, output size)
- Structured ToolResult instead of raw strings
- Retry support for transient failures
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Optional, Set

from app.ai.models import ToolSchema
from app.core.ai.events.bus import bus
from app.core.ai.events.events import ToolCalled, ToolFinished
from app.core.ai.tools.sandbox import ToolSandbox, ToolPermissions, sandbox as default_sandbox

log = logging.getLogger(__name__)


@dataclass
class ToolResult:
    tool_name:   str
    call_id:     str
    success:     bool
    output:      str           # JSON string for structured results, plain text for errors
    error:       Optional[str] = None
    duration_ms: float         = 0.0
    timed_out:   bool          = False
    truncated:   bool          = False

    def to_message_content(self) -> str:
        """Format for inclusion as a message in the conversation."""
        if self.success:
            return self.output
        return json.dumps({"error": self.error or "Tool execution failed"})


class ToolExecutor:
    """
    Executes registered tools via the sandbox with event emission.

    Use the module-level singleton `executor` in production code.
    """

    def __init__(self, sandbox: ToolSandbox | None = None) -> None:
        self._sandbox = sandbox or default_sandbox

    async def execute(
        self,
        tool_name:    str,
        arguments:    dict[str, Any],
        *,
        call_id:      str         = "",
        user_id:      Optional[str] = None,
        permissions:  ToolPermissions | None = None,
        max_retries:  int         = 0,
        allowed_tools: Optional[Set[str]] = None,
    ) -> ToolResult:
        """
        Execute a registered tool and return a ToolResult.

        Always returns — never raises. Errors are captured inside ToolResult.

        `allowed_tools`, when given, is the exact set of tool names that
        were actually offered to the model for this request/agent (e.g.
        AgentConfig.tools, or CompletionRequest.tools's names) — the
        server-side re-check that a returned tool_call names one of them.
        Without this, _REGISTRY.get(tool_name) resolves ANY tool ever
        registered platform-wide (every plugin from every org, including
        admin-only ones), so a hallucinated or prompt-injected tool_call
        naming a tool that was never offered — or that belongs to another
        org's plugin install entirely — would still execute. `None` (the
        default) means the caller isn't enforcing an allowlist here;
        every caller reachable from an agent/HTTP request must pass one.
        """
        from app.ai import tools as _registry  # lazy import to avoid circular deps

        import uuid
        call_id = call_id or str(uuid.uuid4())

        await bus.emit(ToolCalled(
            tool_name=tool_name,
            arguments=arguments,
            call_id=call_id,
            user_id=user_id,
        ))

        if allowed_tools is not None and tool_name not in allowed_tools:
            result = ToolResult(
                tool_name=tool_name, call_id=call_id,
                success=False,
                output=json.dumps({"error": f"Tool '{tool_name}' was not offered for this request"}),
                error=f"Tool '{tool_name}' is not among the tools available to this caller",
            )
            await bus.emit(ToolFinished(
                tool_name=tool_name, call_id=call_id,
                success=False, error=result.error,
            ))
            return result

        entry = _registry._REGISTRY.get(tool_name)
        if not entry:
            result = ToolResult(
                tool_name=tool_name, call_id=call_id,
                success=False,
                output=json.dumps({"error": f"Unknown tool: {tool_name!r}"}),
                error=f"Tool '{tool_name}' is not registered",
            )
            await bus.emit(ToolFinished(
                tool_name=tool_name, call_id=call_id,
                success=False, error=result.error,
            ))
            return result

        attempt = 0
        while True:
            sandbox_result = await self._sandbox.run(
                tool_name,
                lambda: entry.fn(**arguments),
                permissions=permissions,
                user_id=user_id,
            )

            if sandbox_result.success or attempt >= max_retries:
                break

            attempt += 1
            log.debug("Retrying tool '%s' (attempt %d)", tool_name, attempt)

        # Normalize output to string
        output = sandbox_result.output
        if not isinstance(output, str):
            output = json.dumps(output)

        result = ToolResult(
            tool_name=tool_name,
            call_id=call_id,
            success=sandbox_result.success,
            output=output if sandbox_result.success else json.dumps({"error": sandbox_result.error}),
            error=sandbox_result.error,
            duration_ms=sandbox_result.duration_ms,
            timed_out=sandbox_result.timed_out,
            truncated=sandbox_result.truncated,
        )

        await bus.emit(ToolFinished(
            tool_name=tool_name,
            call_id=call_id,
            success=result.success,
            latency_ms=result.duration_ms,
            error=result.error,
        ))

        return result

    async def execute_many(
        self,
        calls: list[dict],  # list of {tool_name, arguments, call_id}
        *,
        user_id: Optional[str] = None,
    ) -> list[ToolResult]:
        """Execute multiple tool calls concurrently."""
        import asyncio
        return await asyncio.gather(*[
            self.execute(
                c["tool_name"],
                c.get("arguments", {}),
                call_id=c.get("call_id", ""),
                user_id=user_id,
            )
            for c in calls
        ])

    def list_schemas(self) -> list[ToolSchema]:
        from app.ai import tools as _registry
        return _registry.list_schemas()

    def get_schema(self, tool_name: str) -> Optional[ToolSchema]:
        from app.ai import tools as _registry
        return _registry.get_schema(tool_name)


# Module-level singleton
executor = ToolExecutor()
