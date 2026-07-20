"""
Thin publish helpers over the EXISTING platform event bus
(app/core/events/bus.py) — no separate integration-specific bus. The
event types themselves are declared additively in that module's
EVENT_TYPES; this file just gives call sites a typed, named function
instead of hand-building the dict every time (same idiom as
app/core/notifications' dispatcher consuming the same bus).
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)


async def _publish(type_: str, data: dict, organization_id: str) -> None:
    try:
        from app.core.events import get_event_bus
        await get_event_bus().publish(type_, data, organization_id=organization_id)
    except Exception:
        log.warning("integration event publish failed for %s org=%s", type_, organization_id, exc_info=True)


async def publish_connected(provider_id: str, organization_id: str) -> None:
    await _publish("integration.connected", {"provider_id": provider_id}, organization_id)


async def publish_disconnected(provider_id: str, organization_id: str) -> None:
    await _publish("integration.disconnected", {"provider_id": provider_id}, organization_id)


async def publish_sync_started(provider_id: str, organization_id: str) -> None:
    await _publish("integration.sync_started", {"provider_id": provider_id}, organization_id)


async def publish_sync_completed(provider_id: str, organization_id: str, *, items_synced: int) -> None:
    await _publish("integration.sync_completed", {"provider_id": provider_id, "items_synced": items_synced}, organization_id)


async def publish_sync_failed(provider_id: str, organization_id: str, *, message: str) -> None:
    await _publish("integration.sync_failed", {"provider_id": provider_id, "error": message}, organization_id)


async def publish_webhook_received(provider_id: str, organization_id: str) -> None:
    await _publish("integration.webhook_received", {"provider_id": provider_id}, organization_id)


async def publish_health_changed(provider_id: str, organization_id: str, *, status: str) -> None:
    await _publish("integration.health_changed", {"provider_id": provider_id, "status": status}, organization_id)
