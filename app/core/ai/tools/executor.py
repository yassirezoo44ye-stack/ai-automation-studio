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
from typing import Any, Optional

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
    ) -> ToolResult:
        """
        Execute a registered tool and return a ToolResult.

        Always returns — never raises. Errors are captured inside ToolResult.
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
