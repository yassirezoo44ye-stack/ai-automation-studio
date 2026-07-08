"""
Kernel Middleware Pipeline.

Every command passes through the middleware chain before dispatch.
Middleware functions receive a KernelContext and return it (possibly modified).

Built-in middleware:
  - trim_input       : strip whitespace
  - logging_mw       : log every invocation
  - timing_mw        : attach start time (result gets duration)
  - state_tracker_mw : increment command counter in KernelState
  - alias_resolver_mw: expand shorthand aliases before parsing
  - rate_limit_mw    : basic per-caller rate limiting

Middleware signature:
    async def my_mw(ctx: KernelContext) -> KernelContext:
        ctx.input = ctx.input.upper()  # transform
        return ctx
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.kernel.state import KernelState

log = logging.getLogger(__name__)

MiddlewareFn = Callable[["KernelContext"], Coroutine[Any, Any, "KernelContext"]]

# Per-caller command counts for rate limiting
_call_counts: dict[str, list[float]] = defaultdict(list)
_RATE_WINDOW_S = 60.0
_RATE_LIMIT    = 120   # max commands per caller per minute


@dataclass
class KernelContext:
    """
    Shared context object that flows through the middleware pipeline.
    Middleware may read and write any field.
    """
    input     : str = ""
    caller    : str = "cli"
    user_id   : Optional[str] = None
    started_at: float = field(default_factory=time.time)
    extra     : dict[str, Any] = field(default_factory=dict)

    # Set by middleware / kernel
    command   : str = ""
    args      : list[str] = field(default_factory=list)
    flags     : dict[str, str] = field(default_factory=dict)
    blocked   : bool = False
    block_reason: str = ""


# ── Built-in middleware ───────────────────────────────────────────────────────

async def trim_input(ctx: KernelContext) -> KernelContext:
    ctx.input = ctx.input.strip()
    return ctx


async def logging_mw(ctx: KernelContext) -> KernelContext:
    log.info("kernel ← %r  caller=%s", ctx.input[:120], ctx.caller)
    return ctx


async def timing_mw(ctx: KernelContext) -> KernelContext:
    ctx.started_at = time.time()
    return ctx


def state_tracker_mw(state: "KernelState") -> MiddlewareFn:
    """Factory: returns middleware that records each command in KernelState."""
    async def _mw(ctx: KernelContext) -> KernelContext:
        # Extract command name (first word) for tracking
        if ctx.input:
            state.record_command(ctx.input.split()[0])
        return ctx
    return _mw


def rate_limit_mw(limit: int = _RATE_LIMIT, window_s: float = _RATE_WINDOW_S) -> MiddlewareFn:
    """Factory: returns a rate-limiting middleware."""
    async def _mw(ctx: KernelContext) -> KernelContext:
        caller = ctx.caller or "anonymous"
        now    = time.time()
        calls  = _call_counts[caller]
        # Evict old entries outside the window
        _call_counts[caller] = [t for t in calls if now - t < window_s]
        if len(_call_counts[caller]) >= limit:
            ctx.blocked      = True
            ctx.block_reason = (
                f"Rate limit: {limit} commands/{window_s:.0f}s for caller '{caller}'"
            )
            log.warning("rate limited: %s", caller)
        else:
            _call_counts[caller].append(now)
        return ctx
    return _mw


# Command aliases expanded before parsing
_ALIASES: dict[str, str] = {
    "?"    : "help",
    "ls"   : "inspect commands",
    "ps"   : "inspect overview",
    "top"  : "inspect overview",
    "cat"  : "inspect execution",
    "clear": "status",
}


async def alias_resolver_mw(ctx: KernelContext) -> KernelContext:
    """Expand well-known shell-like aliases."""
    first_word = ctx.input.split()[0] if ctx.input else ""
    if first_word in _ALIASES:
        ctx.input = _ALIASES[first_word] + ctx.input[len(first_word):]
    return ctx


# ── Pipeline builder ──────────────────────────────────────────────────────────

def default_pipeline(state: "KernelState") -> list[MiddlewareFn]:
    """Return the default ordered middleware stack."""
    return [
        trim_input,
        alias_resolver_mw,
        timing_mw,
        logging_mw,
        state_tracker_mw(state),
        rate_limit_mw(),
    ]
