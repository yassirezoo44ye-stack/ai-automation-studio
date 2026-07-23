"""
Agentic tool loop — extracted from the inference router.

Handles:
- Executing all tool calls in a response
- Building tool result messages
- Looping until no more tool calls or max_rounds reached
- Emitting tool events
- Streaming variant with interleaved tool execution
"""
from __future__ import annotations

import logging
from typing import AsyncGenerator, Optional

from app.ai.models import CompletionRequest, CompletionResponse, Message
from app.core.ai.tools.executor import ToolResult, executor as default_executor

log = logging.getLogger(__name__)

_MAX_ROUNDS = 8


async def run_tool_loop(
    request:     CompletionRequest,
    response:    CompletionResponse,
    *,
    gateway,            # AIGateway or callable (request) → CompletionResponse
    user_id:     Optional[str] = None,
    org_id:      Optional[str] = None,
    max_rounds:  int            = _MAX_ROUNDS,
    tool_executor=None,
) -> CompletionResponse:
    """
    Given a first response that contains tool_calls, execute them and continue
    calling the AI until a final answer is produced (no more tool calls) or
    max_rounds is exhausted.

    Returns the final CompletionResponse.
    """
    tool_exec = tool_executor or default_executor
    current_req  = request
    current_resp = response
    # The exact tools offered to the model for this request — a
    # tool_call naming anything else (hallucinated, prompt-injected, or
    # simply never offered) must not execute, or the caller's tool
    # exposure is effectively "every registered tool platform-wide"
    # regardless of what request.tools actually declared.
    allowed_tools = {t.name for t in (request.tools or [])}

    for _round in range(max_rounds):
        if not current_resp.tool_calls:
            break

        tool_messages: list[Message] = [
            Message(role="assistant", content=current_resp.content or "")
        ]

        for tc in current_resp.tool_calls:
            result: ToolResult = await tool_exec.execute(
                tc.name, tc.arguments,
                call_id=tc.id, user_id=user_id,
                allowed_tools=allowed_tools,
            )
            tool_messages.append(Message(
                role="tool",
                content=result.to_message_content(),
                name=tc.name,
            ))
            log.debug(
                "tool_loop: executed %s -> %s (%.0fms)",
                tc.name, "ok" if result.success else "error", result.duration_ms,
            )

        current_req = current_req.model_copy(update={
            "messages": list(current_req.messages) + tool_messages,
            "conversation_id": (
                current_resp.conversation_id or current_req.conversation_id
            ),
        })

        if callable(gateway):
            current_resp = await gateway(current_req)
        else:
            # Every round of the tool loop is a real completion call — must
            # be quota-checked/usage-recorded like the first one, not just
            # the outer call that triggered the loop.
            current_resp = await gateway.complete(current_req, user_id=user_id, org_id=org_id)

    return current_resp


async def stream_tool_loop(
    request:    CompletionRequest,
    *,
    gateway,             # AIGateway or callable
    user_id:    Optional[str] = None,
    org_id:     Optional[str] = None,
    max_rounds: int            = _MAX_ROUNDS,
    tool_executor=None,
) -> AsyncGenerator[dict, None]:
    """
    Streaming variant of the tool loop.

    Yields raw dicts (not StreamChunk) so they can be forwarded directly as SSE.
    Between stream segments, tool calls are executed synchronously.
    """
    from app.ai.models import StreamChunk

    tool_exec      = tool_executor or default_executor
    current_req    = request
    accumulated_tc = []
    allowed_tools  = {t.name for t in (request.tools or [])}

    # First stream pass
    if callable(gateway):
        stream_gen = gateway(current_req)
    else:
        stream_gen = gateway.stream(current_req, user_id=user_id, org_id=org_id)

    async for chunk in stream_gen:
        if isinstance(chunk, StreamChunk):
            yield chunk.model_dump()
        else:
            yield chunk

        if hasattr(chunk, "type") and chunk.type == "tool_call" and chunk.tool_call:
            accumulated_tc.append(chunk.tool_call)

    # Tool execution rounds
    for _round in range(max_rounds - 1):
        if not accumulated_tc:
            break

        tool_messages: list[Message] = [Message(role="assistant", content="")]
        for tc in accumulated_tc:
            result: ToolResult = await tool_exec.execute(
                tc.name, tc.arguments,
                call_id=tc.id, user_id=user_id,
                allowed_tools=allowed_tools,
            )
            yield {
                "type":      "tool_result",
                "tool_name": tc.name,
                "result":    result.output,
                "success":   result.success,
            }
            tool_messages.append(Message(
                role="tool",
                content=result.to_message_content(),
                name=tc.name,
            ))

        current_req = current_req.model_copy(update={
            "messages": list(current_req.messages) + tool_messages,
        })

        accumulated_tc = []
        if callable(gateway):
            follow_gen = gateway(current_req)
        else:
            follow_gen = gateway.stream(current_req, user_id=user_id, org_id=org_id)

        async for chunk in follow_gen:
            if isinstance(chunk, StreamChunk):
                yield chunk.model_dump()
            else:
                yield chunk
            if hasattr(chunk, "type") and chunk.type == "tool_call" and chunk.tool_call:
                accumulated_tc.append(chunk.tool_call)
