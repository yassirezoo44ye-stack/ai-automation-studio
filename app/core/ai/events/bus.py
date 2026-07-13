"""
Async event bus — lightweight pub/sub for decoupled AI platform communication.

Usage::

    from app.core.ai.events import bus, PromptCompleted

    # Subscribe
    @bus.on(PromptCompleted)
    async def handle_prompt_done(event: PromptCompleted) -> None:
        print(f"Cost: ${event.cost_usd}")

    # Emit
    await bus.emit(PromptCompleted(provider_id="anthropic", cost_usd=0.002, ...))

Handlers run concurrently and failures are isolated — one broken handler
never prevents others from running.
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Callable, Awaitable, Type, TypeVar

from .events import AIEvent
from app.core.observability.context import current_tags
from app.core.observability.tracer import get_tracer

log = logging.getLogger(__name__)

T = TypeVar("T", bound=AIEvent)
Handler = Callable[[AIEvent], Awaitable[None]]


class EventBus:
    """
    Process-local async pub/sub bus.

    Thread-safe under asyncio single-event-loop assumption.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = defaultdict(list)

    # ── Subscription ──────────────────────────────────────────────────────────

    def on(self, event_class: Type[T]) -> Callable[[Handler], Handler]:
        """Decorator: subscribe a handler to an event type."""
        def decorator(fn: Handler) -> Handler:
            self._handlers[event_class.__name__].append(fn)
            log.debug("EventBus: registered handler %s → %s", event_class.__name__, fn.__qualname__)
            return fn
        return decorator

    def subscribe(self, event_class: Type[T], handler: Handler) -> None:
        """Imperative subscription (alternative to @on decorator)."""
        self._handlers[event_class.__name__].append(handler)

    def unsubscribe(self, event_class: Type[T], handler: Handler) -> None:
        handlers = self._handlers.get(event_class.__name__, [])
        if handler in handlers:
            handlers.remove(handler)

    # ── Emission ──────────────────────────────────────────────────────────────

    async def emit(self, event: AIEvent) -> None:
        """
        Emit an event to all subscribers.

        Runs all handlers concurrently; exceptions are logged but do not
        propagate — callers must never fail because of a subscriber bug.
        """
        key = type(event).__name__
        handlers = self._handlers.get(key, [])
        if not handlers:
            return

        tracer = get_tracer()
        with tracer.start_span("ai_event_bus.emit", service="ai_gateway") as span:
            for tk, tv in current_tags().items():
                span.set_tag(tk, tv)
            span.set_tag("event_type", key)
            span.set_tag("handler_count", len(handlers))

            results = await asyncio.gather(
                *(h(event) for h in handlers),
                return_exceptions=True,
            )
            errors = []
            for h, result in zip(handlers, results):
                if isinstance(result, Exception):
                    errors.append(f"{h.__qualname__}: {result}")
                    log.error(
                        "EventBus handler %s raised %s: %s",
                        h.__qualname__, type(result).__name__, result,
                    )
            if errors:
                span.set_tag("error", "; ".join(errors))

    def emit_sync(self, event: AIEvent) -> None:
        """
        Fire-and-forget from sync context.
        Schedules emission on the running event loop if one exists.
        """
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(self.emit(event))
        except RuntimeError:
            pass

    # ── Introspection ─────────────────────────────────────────────────────────

    def handler_count(self, event_class: Type[T]) -> int:
        return len(self._handlers.get(event_class.__name__, []))

    def all_handlers(self) -> dict[str, list[str]]:
        return {k: [h.__qualname__ for h in v] for k, v in self._handlers.items()}


# Module-level singleton — import this everywhere
bus = EventBus()
