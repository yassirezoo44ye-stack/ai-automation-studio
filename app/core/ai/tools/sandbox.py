"""
Tool sandbox — timeout enforcement and permission checks.

Every tool execution passes through ToolSandbox before running.
Keeps tool execution safe without restricting what tools can do.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Set

log = logging.getLogger(__name__)

# Default limits
_DEFAULT_TIMEOUT_S = 30.0
_DEFAULT_MAX_RESULT_CHARS = 8_000  # prevent huge outputs from flooding the context window


@dataclass
class ToolPermissions:
    """
    Declares what a tool is allowed to do.

    The sandbox only enforces timeout and result size here.
    Future versions can add process/network/filesystem restrictions.
    """
    timeout_s:       float = _DEFAULT_TIMEOUT_S
    max_result_chars: int   = _DEFAULT_MAX_RESULT_CHARS
    allowed_for:     Set[str] = field(default_factory=lambda: {"*"})  # user IDs or "*"
    requires_auth:   bool  = False  # If True, user_id must be provided


@dataclass
class SandboxResult:
    success:  bool
    output:   str
    error:    str | None = None
    timed_out: bool       = False
    truncated: bool       = False
    duration_ms: float    = 0.0


class ToolSandbox:
    """
    Wraps any tool call with:
    - Timeout enforcement (asyncio.wait_for)
    - Output size limiting
    - Permission checking
    - Structured result production
    """

    def __init__(
        self,
        default_timeout_s: float = _DEFAULT_TIMEOUT_S,
        max_result_chars: int    = _DEFAULT_MAX_RESULT_CHARS,
    ) -> None:
        self._timeout   = default_timeout_s
        self._max_chars = max_result_chars

    async def run(
        self,
        tool_name: str,
        fn,  # async callable that returns str
        *,
        permissions: ToolPermissions | None = None,
        user_id: str | None = None,
    ) -> SandboxResult:
        import time
        perm    = permissions or ToolPermissions(timeout_s=self._timeout)
        timeout = perm.timeout_s

        # Permission check
        if perm.requires_auth and not user_id:
            return SandboxResult(
                success=False, output="",
                error=f"Tool '{tool_name}' requires authentication",
            )
        if "*" not in perm.allowed_for and user_id not in perm.allowed_for:
            return SandboxResult(
                success=False, output="",
                error=f"User '{user_id}' is not authorized to use tool '{tool_name}'",
            )

        t0 = time.perf_counter()
        try:
            output = await asyncio.wait_for(fn(), timeout=timeout)
            if output is None:
                output = ""
            elif not isinstance(output, str):
                output = str(output)
            duration_ms = (time.perf_counter() - t0) * 1000

            truncated = False
            if len(output) > perm.max_result_chars:
                output    = output[:perm.max_result_chars] + "\n[output truncated]"
                truncated = True
                log.debug("Tool '%s' output truncated to %d chars", tool_name, perm.max_result_chars)

            return SandboxResult(
                success=True, output=output,
                truncated=truncated, duration_ms=duration_ms,
            )

        except asyncio.TimeoutError:
            duration_ms = (time.perf_counter() - t0) * 1000
            log.warning("Tool '%s' timed out after %.1fs", tool_name, timeout)
            return SandboxResult(
                success=False, output="",
                error=f"Tool '{tool_name}' timed out after {timeout}s",
                timed_out=True, duration_ms=duration_ms,
            )
        except Exception as exc:
            duration_ms = (time.perf_counter() - t0) * 1000
            log.exception("Tool '%s' raised %s", tool_name, type(exc).__name__)
            return SandboxResult(
                success=False, output="",
                error=f"Tool '{tool_name}' failed: {exc}",
                duration_ms=duration_ms,
            )


# Module-level default sandbox
sandbox = ToolSandbox()
