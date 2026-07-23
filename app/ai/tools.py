"""
Tool / function calling registry.

Register tools server-side; they are resolved by name when the AI
requests a function call. Never expose internal tool logic to the frontend.
"""
from __future__ import annotations

import inspect
import json
import logging
from typing import Any, Callable

from app.ai.models import ToolSchema
from app.plugins.registry_guard import OwnershipTracker

log = logging.getLogger(__name__)

_REGISTRY: dict[str, "_ToolEntry"] = {}
# Tracks which owner (a plugin installation_id, or None for a built-in)
# holds each tool name — see registry_guard's docstring for why this
# matters: without it, one org's plugin can silently hijack another
# org's (or a built-in's) tool name.
_owners = OwnershipTracker("tool")


class _ToolEntry:
    __slots__ = ("schema", "fn")

    def __init__(self, schema: ToolSchema, fn: Callable) -> None:
        self.schema = schema
        self.fn     = fn


# ── Decorator ─────────────────────────────────────────────────────────────────

def tool(
    *,
    description: str,
    parameters: dict[str, Any],
    name: str | None = None,
) -> Callable:
    """
    Register a function as an AI-callable tool.

    Example::

        @tool(
            description="Search the web for a query",
            parameters={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        )
        async def web_search(query: str) -> str:
            ...
    """
    def decorator(fn: Callable) -> Callable:
        tool_name = name or fn.__name__
        schema = ToolSchema(
            name=tool_name,
            description=description,
            parameters=parameters,
        )
        _owners.claim(tool_name, None)  # built-in — owner=None, protected from plugin takeover
        _REGISTRY[tool_name] = _ToolEntry(schema=schema, fn=fn)
        log.debug("Registered tool: %s", tool_name)
        return fn
    return decorator


def register_tool(schema: ToolSchema, fn: Callable, *, owner: str | None = None) -> None:
    """Non-decorator registration — for callers that build a ToolSchema
    dynamically (e.g. a Plugin SDK TOOL-type plugin loaded from a
    marketplace asset, where there's no source-level `@tool(...)` to
    decorate). Same _REGISTRY the decorator writes to.

    `owner` should be the plugin's installation_id for any plugin-sourced
    tool (app.plugins.adapters.adapt_tool always supplies it) — raises
    RegistrationConflictError if the name is already held by a different
    owner, rather than silently overwriting it. See registry_guard's
    module docstring for why this matters."""
    _owners.claim(schema.name, owner)
    _REGISTRY[schema.name] = _ToolEntry(schema=schema, fn=fn)
    log.debug("Registered tool (dynamic): %s (owner=%s)", schema.name, owner)


def unregister_tool(tool_name: str) -> bool:
    _owners.release(tool_name)
    return _REGISTRY.pop(tool_name, None) is not None


# ── Execution ─────────────────────────────────────────────────────────────────

async def execute(tool_name: str, arguments: dict[str, Any]) -> str:
    """Execute a registered tool and return its string result."""
    entry = _REGISTRY.get(tool_name)
    if not entry:
        return json.dumps({"error": f"Unknown tool: {tool_name!r}"})

    try:
        result = entry.fn(**arguments)
        if inspect.isawaitable(result):
            result = await result
        return json.dumps(result) if not isinstance(result, str) else result
    except Exception as exc:
        log.exception("Tool %r execution error", tool_name)
        return json.dumps({"error": str(exc)})


def list_schemas() -> list[ToolSchema]:
    return [e.schema for e in _REGISTRY.values()]


def get_schema(tool_name: str) -> ToolSchema | None:
    entry = _REGISTRY.get(tool_name)
    return entry.schema if entry else None


# ── Built-in tools ─────────────────────────────────────────────────────────────

@tool(
    description="Get the current UTC date and time as an ISO 8601 string.",
    parameters={"type": "object", "properties": {}, "required": []},
    name="get_current_time",
)
async def _get_current_time() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


@tool(
    description="Calculate a mathematical expression and return the result.",
    parameters={
        "type": "object",
        "properties": {
            "expression": {
                "type":        "string",
                "description": "A safe mathematical expression (e.g. '2 + 2 * 3')",
            }
        },
        "required": ["expression"],
    },
    name="calculate",
)
async def _calculate(expression: str) -> str:
    import ast
    import operator as op

    _OPERATORS = {
        ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul,
        ast.Div: op.truediv, ast.Pow: op.pow, ast.Mod: op.mod,
        ast.USub: op.neg, ast.UAdd: op.pos,
    }

    def _eval(node: ast.AST) -> float:
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        elif isinstance(node, ast.BinOp):
            op_fn = _OPERATORS.get(type(node.op))
            if not op_fn:
                raise ValueError(f"Unsupported operator: {type(node.op).__name__}")
            return op_fn(_eval(node.left), _eval(node.right))
        elif isinstance(node, ast.UnaryOp):
            op_fn = _OPERATORS.get(type(node.op))
            if not op_fn:
                raise ValueError(f"Unsupported unary op: {type(node.op).__name__}")
            return op_fn(_eval(node.operand))
        else:
            raise ValueError(f"Unsupported expression node: {type(node).__name__}")

    try:
        tree = ast.parse(expression, mode="eval")
        result = _eval(tree.body)
        return str(result)
    except Exception as exc:
        return f"Error: {exc}"
