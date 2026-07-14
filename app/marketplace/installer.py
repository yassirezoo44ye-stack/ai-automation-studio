"""
Installation pipeline — the 9-stage engine specified for Production
Marketplace: validate, verify permissions, resolve dependencies, locate
assets, verify integrity, install, register, emit event, rollback on
failure.

Every DB write happens inside stage 6's single `record_install` call
(itself already wrapped in one `acquire_scoped(org_id)` transaction —
see store.py). Every earlier stage only reads and raises; if any of them
raises, nothing has been written yet, so "rollback" is simply "the
transaction in stage 6 never ran" — no Saga/compensation engine is needed
since nothing in this pipeline touches a system outside Postgres.
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Optional

from app.core.observability.context import current_tags
from app.core.observability.tracer import get_tracer

log = logging.getLogger(__name__)


class MarketplaceInstallError(Exception):
    """Base class for every typed installation failure."""


class ItemNotFoundError(MarketplaceInstallError):
    def __init__(self, item_id: str):
        super().__init__(f"listing {item_id} not found")
        self.item_id = item_id


class MarketplacePermissionError(MarketplaceInstallError):
    def __init__(self, org_id: str, actor_id: str):
        super().__init__(f"actor {actor_id} is not a member of org {org_id}")
        self.org_id, self.actor_id = org_id, actor_id


class PlanFeatureNotEnabledError(MarketplaceInstallError):
    def __init__(self, org_id: str, plan_id: str):
        super().__init__(f"org {org_id}'s plan {plan_id!r} does not include the marketplace feature")
        self.org_id, self.plan_id = org_id, plan_id


class IntegrityError(MarketplaceInstallError):
    def __init__(self, item_id: str, asset_id: Optional[str], reason: str):
        super().__init__(f"integrity check failed for {item_id} (asset {asset_id}): {reason}")
        self.item_id, self.asset_id, self.reason = item_id, asset_id, reason


class NotInstalledError(MarketplaceInstallError):
    def __init__(self, item_id: str, org_id: str):
        super().__init__(f"{item_id} is not currently installed for org {org_id}")
        self.item_id, self.org_id = item_id, org_id


class VersionNotFoundError(MarketplaceInstallError):
    def __init__(self, item_id: str, version: str):
        super().__init__(f"{item_id} has no recorded version {version!r}")
        self.item_id, self.version = item_id, version


class InstallationPipeline:
    async def install(
        self, item_id: str, *, org_id: str, actor_id: str,
        actor_email: Optional[str] = None, requested_version: Optional[str] = None,
    ) -> dict[str, Any]:
        tracer = get_tracer()
        with tracer.start_span("marketplace.install", service="marketplace") as span:
            for key, val in current_tags().items():
                span.set_tag(key, val)
            span.set_tag("organization_id", org_id)
            span.set_tag("item_id", item_id)
            try:
                result = await self._install_inner(
                    item_id, org_id=org_id, actor_id=actor_id,
                    actor_email=actor_email, requested_version=requested_version,
                )
            except Exception as exc:
                span.set_tag("error", str(exc))
                try:
                    from app.core.events import get_event_bus
                    await get_event_bus().publish(
                        "marketplace.install_failed",
                        {"listing_id": item_id, "reason": str(exc)},
                        organization_id=org_id,
                    )
                except Exception:
                    pass
                raise
            return result

    async def _install_inner(
        self, item_id: str, *, org_id: str, actor_id: str,
        actor_email: Optional[str], requested_version: Optional[str],
    ) -> dict[str, Any]:
        from app.marketplace.store import get_marketplace_store
        from app.marketplace.dependencies import (
            get_dependency_service,
        )
        from app.marketplace.assets import get_asset_service
        from app.marketplace.security import (
            verify_checksum, scan_for_secrets, scan_for_malware, scan_dependency_vulnerabilities,
        )
        from app.tenancy.service import get_tenancy_service
        from app.billing import get_plan_service, get_usage_service

        store = get_marketplace_store()
        tenancy = get_tenancy_service()

        # 1. validate — item exists, not soft-deleted, visibility permits this org.
        item = await store.get_item(item_id, viewer_org_id=org_id)
        if item is None:
            raise ItemNotFoundError(item_id)
        target_version = requested_version or item["version"]

        # 2. verify permissions — defensive re-check (the router's org_context
        # dependency already DB-verifies membership before this pipeline
        # ever runs; re-checking here matches the defense-in-depth pattern
        # used elsewhere in this codebase). Any active member may install —
        # marketplace install is not gated by a narrower RBAC permission.
        role = await tenancy.get_member_role(org_id, actor_id)
        if role is None:
            raise MarketplacePermissionError(org_id, actor_id)

        org = await tenancy.get_organization(org_id)
        plan = await get_plan_service().get_plan((org or {}).get("plan") or "free")
        if "marketplace" not in plan.features:
            raise PlanFeatureNotEnabledError(org_id, plan.id)
        await get_usage_service().check_quota(org_id, "marketplace_purchases", 1)

        # 3. resolve dependencies — raises on missing/circular/unsatisfied
        # version constraints before anything is written.
        await get_dependency_service().resolve_install_order(item_id)

        # 4. locate assets for the target version.
        assets = await get_asset_service().get_assets(item_id, target_version)

        # 5. verify integrity — checksum + secret scan BLOCK on failure;
        # the two stub hooks only warn (they can't meaningfully fail today).
        for asset in assets:
            if asset["asset_type"] == "inline":
                if not verify_checksum(asset["content"], asset["checksum_sha256"]):
                    raise IntegrityError(item_id, asset["id"], "checksum mismatch")
                findings = scan_for_secrets(asset["content"])
                if findings:
                    raise IntegrityError(item_id, asset["id"], "; ".join(findings))
        malware = scan_for_malware({"item_id": item_id, "assets": assets})
        if not malware.passed:
            log.warning("marketplace malware scan flagged %s: %s", item_id, malware.findings)
        vuln = scan_dependency_vulnerabilities(item_id)
        if not vuln.passed:
            log.warning("marketplace dependency vuln scan flagged %s: %s", item_id, vuln.findings)

        # 6. install — the one and only write, already one atomic transaction
        # inside acquire_scoped(org_id) (see store.py). Anything that raised
        # above never reached here, so nothing needed rolling back (stage 9).
        result = await store.record_install(
            item_id, org_id=org_id, user_email=actor_email, version=target_version,
        )
        if result is None:
            raise ItemNotFoundError(item_id)

        # 7. register — for a plugin listing, actually load and activate the
        # code via the Plugin SDK's loader. Best-effort: a plugin failing to
        # load must not undo the marketplace install that already committed
        # in stage 6 (the failure is recorded in plugin_health_log; the
        # caller can inspect it via GET /plugins/installed/{id}/health).
        if item.get("type") == "plugin":
            try:
                from app.plugins import get_plugin_loader
                await get_plugin_loader().load(item_id, org_id=org_id, actor_id=actor_id)
            except Exception:
                log.warning("plugin registration failed for %s org=%s", item_id, org_id, exc_info=True)

        # 8. emit event (best-effort, never breaks a successful install).
        try:
            from app.core.events import get_event_bus
            await get_event_bus().publish(
                "marketplace.installed",
                {"listing_id": item_id, "name": result["name"], "version": target_version},
                organization_id=org_id,
            )
        except Exception:
            pass

        try:
            from app.tenancy.service import get_tenancy_service
            await get_tenancy_service().log_activity(
                org_id, actor_id, "marketplace.installed",
                resource="marketplace_item", resource_id=item_id,
                details={"name": result["name"], "version": target_version, "type": item.get("type")},
            )
        except Exception:
            pass
        return result

    async def uninstall(self, item_id: str, *, org_id: str, actor_id: str) -> None:
        from app.core.db import acquire_scoped
        from app.tenancy.service import get_tenancy_service

        role = await get_tenancy_service().get_member_role(org_id, actor_id)
        if role is None:
            raise MarketplacePermissionError(org_id, actor_id)

        async with acquire_scoped(org_id) as conn:
            row = await conn.fetchrow(
                """UPDATE marketplace_installs SET uninstalled_at=NOW()
                   WHERE id = (
                       SELECT id FROM marketplace_installs
                       WHERE item_id=$1 AND organization_id=$2 AND uninstalled_at IS NULL
                       ORDER BY created_at DESC LIMIT 1
                   )
                   RETURNING id""",
                item_id, uuid.UUID(str(org_id)),
            )
            if row is None:
                raise NotInstalledError(item_id, org_id)
            await conn.execute(
                "UPDATE marketplace_items SET installs = GREATEST(installs - 1, 0), updated_at=$2 WHERE id=$1",
                item_id, time.time(),
            )
        try:
            from app.core.events import get_event_bus
            await get_event_bus().publish(
                "marketplace.uninstalled", {"listing_id": item_id}, organization_id=org_id,
            )
        except Exception:
            pass

        try:
            from app.tenancy.service import get_tenancy_service
            await get_tenancy_service().log_activity(
                org_id, actor_id, "marketplace.uninstalled",
                resource="marketplace_item", resource_id=item_id,
            )
        except Exception:
            pass

        # Mirror of stage 7's registration hook — deactivate the plugin's
        # code if this was a plugin listing. Looked up directly against
        # plugin_installations (not via store.get_item()) because a
        # publisher may have soft-deleted or unlisted the listing after
        # this org installed it — get_item() would return None in that
        # case and silently skip the unload, leaving the installation
        # stuck at its old status. Best-effort for the same reason as
        # install: the marketplace uninstall above already committed.
        try:
            from app.plugins import get_plugin_loader
            loader = get_plugin_loader()
            installation = await loader.find_installation(org_id, item_id)
            if installation:
                await loader.unload(str(installation["id"]))
        except Exception:
            log.warning("plugin unload failed for %s org=%s", item_id, org_id, exc_info=True)

    async def rollback_version(
        self, item_id: str, *, org_id: str, actor_id: str,
        actor_email: Optional[str] = None, target_version: str,
    ) -> dict[str, Any]:
        from app.core.db import get_pool
        async with get_pool().acquire() as conn:
            exists = await conn.fetchval(
                "SELECT 1 FROM marketplace_versions WHERE item_id=$1 AND version=$2",
                item_id, target_version,
            )
        if not exists:
            raise VersionNotFoundError(item_id, target_version)
        return await self.install(
            item_id, org_id=org_id, actor_id=actor_id, actor_email=actor_email,
            requested_version=target_version,
        )


_pipeline: InstallationPipeline | None = None


def get_installation_pipeline() -> InstallationPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = InstallationPipeline()
    return _pipeline
