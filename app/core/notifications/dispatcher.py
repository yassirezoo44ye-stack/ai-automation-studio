"""
Notification dispatcher — subscribes to the existing platform EventBus
(app/core/events/bus.py) and turns a curated set of already-published
event types into persisted, per-user Notification rows, then pushes them
over the existing WS `_ConnectionManager` (app/routers/ws.py) to topic
`notifications:{user_id}` for anyone connected.

Mirrors the wiring idiom in app/core/observability/bridges.py: idempotent
wire_*() functions subscribing to events that already exist, called once
at startup. Best-effort throughout — a notification failing to persist or
broadcast must never break the workflow/agent/billing/... code that
published the underlying event.

handle_event() is a module-level function (not a closure) so tests can
call it directly against a synthetic Event without touching the process-
wide EventBus singleton.
"""
from __future__ import annotations

import logging

from app.core.notifications.templates import TEMPLATES

log = logging.getLogger(__name__)

_wired = False


async def handle_event(event) -> None:
    template = TEMPLATES.get(event.type)
    if template is None:
        return
    if not event.organization_id:
        # No way to know who should see this without an org to fan out
        # to — best-effort, so we simply skip rather than guess.
        return

    try:
        from app.core.notifications.service import get_notification_service
        svc = get_notification_service()
        member_ids = await svc.org_member_ids(organization_id=event.organization_id)
        if not member_ids:
            return

        title = template.title(event.data)
        message = template.message(event.data)
        severity = template.resolve_severity(event.data)
        action = template.action(event.data) if template.action else None

        from app.routers.ws import manager as ws_manager

        for user_id in member_ids:
            if await svc.is_muted(user_id=user_id, category=template.category):
                continue
            notification = await svc.create(
                user_id=user_id, organization_id=event.organization_id,
                type_=event.type, category=template.category, severity=severity,
                title=title, message=message, source=f"event_bus:{event.type}", action=action,
            )
            await ws_manager.broadcast(f"notifications:{user_id}", notification)
    except Exception:
        log.warning("notification dispatch failed for event %s", event.type, exc_info=True)


def wire_notification_dispatcher() -> None:
    if globals()["_wired"]:
        return
    globals()["_wired"] = True

    from app.core.events import get_event_bus
    for event_type in TEMPLATES:
        get_event_bus().subscribe(event_type, handle_event)

    log.info("notification dispatcher wired for %d event types", len(TEMPLATES))
