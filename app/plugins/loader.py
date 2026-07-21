"""
Plugin Loader — discovery, validation, dependency resolution, version
compatibility, safe loading, hot reload (dev-only), graceful unloading.

Execution is isolated by the Agent Sandbox (app/sandbox/): a plugin's own
code never runs in this process anymore. load() asks SandboxManager for a
live Worker (a Docker container or subprocess running
app/sandbox/runner_entrypoint.py), drives its lifecycle hooks and
register() over that Worker's IPC channel, and wires the JSON-safe
registrations it returns into the real registries via
app.plugins.adapters.adapt_registrations — which hands each registry a
proxy that dispatches every actual call back into the Worker. Dependency
resolution and version-constraint checking are still NOT reimplemented
here — they delegate straight to app.marketplace.dependencies (the same
Kahn's-algorithm resolver and version_satisfies comparator the Marketplace
phase already shipped and tested).
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from typing import Any, Optional

from app.core.observability.context import current_tags
from app.core.observability.tracer import get_tracer

log = logging.getLogger(__name__)

PLATFORM_VERSION = "1.0.0"


def normalize_installation_row(row: dict[str, Any]) -> dict[str, Any]:
    """asyncpg returns JSONB columns as raw text unless a codec is
    registered (none is, in this codebase — see e.g. marketplace/store.py's
    _row_to_item doing the same normalization). Decode config/manifest so
    callers always get dicts, never a JSON string."""
    for field in ("config", "manifest"):
        if isinstance(row.get(field), str):
            row[field] = json.loads(row[field])
    return row


class PluginLoadError(Exception):
    """Base class for every typed loader failure."""


class PluginNotApprovedError(PluginLoadError):
    def __init__(self, plugin_id: str):
        super().__init__(f"plugin {plugin_id} declares a sensitive capability and has not been approved")
        self.plugin_id = plugin_id


class PlatformVersionError(PluginLoadError):
    def __init__(self, plugin_id: str, reason: str):
        super().__init__(f"plugin {plugin_id} is incompatible with platform version {PLATFORM_VERSION}: {reason}")
        self.plugin_id = plugin_id


class PluginImportError(PluginLoadError):
    def __init__(self, plugin_id: str, reason: str):
        super().__init__(f"plugin {plugin_id} failed to load: {reason}")
        self.plugin_id, self.reason = plugin_id, reason


class PluginDependencyError(PluginLoadError):
    def __init__(self, plugin_id: str, depends_on: str, reason: str):
        super().__init__(f"plugin {plugin_id} depends on {depends_on}: {reason}")
        self.plugin_id, self.depends_on, self.reason = plugin_id, depends_on, reason


# Capabilities that require explicit admin approval before a plugin may be enabled.
_SENSITIVE_CAPABILITIES = frozenset({
    "network", "filesystem", "shell_exec", "credentials_read", "third_party_api",
})


class PluginLoader:
    def __init__(self) -> None:
        # installation_id -> live sandbox Worker handle, for enable/disable/unload
        self._instances: dict[str, Any] = {}

    async def load(self, marketplace_item_id: str, *, org_id: str, actor_id: Optional[str] = None) -> dict[str, Any]:
        """Fetch, validate, resolve, and activate a plugin for one org.
        Best-effort by design (see installer.py's stage 7 call site) — never
        raises into the marketplace install transaction; callers that need
        the failure reason should catch PluginLoadError themselves."""
        from app.marketplace.assets import get_asset_service
        from app.marketplace.store import get_marketplace_store
        from app.plugins.manifest import parse_manifest, validate_permissions, ManifestValidationError

        tracer = get_tracer()
        with tracer.start_span("plugin.load", service="plugin_loader") as span:
            for key, val in current_tags().items():
                span.set_tag(key, val)
            span.set_tag("organization_id", org_id)
            span.set_tag("marketplace_item_id", marketplace_item_id)

            item = await get_marketplace_store().get_item(marketplace_item_id, viewer_org_id=org_id)
            if item is None:
                raise PluginLoadError(f"listing {marketplace_item_id} not found")

            assets = await get_asset_service().get_assets(marketplace_item_id, item["version"])
            bundle = self._extract_bundle(assets)
            if bundle is None:
                raise PluginLoadError(f"listing {marketplace_item_id} has no inline plugin bundle asset")

            try:
                manifest = parse_manifest(bundle["manifest"])
            except ManifestValidationError as exc:
                raise PluginLoadError(f"manifest invalid: {exc}") from exc

            span.set_tag("plugin_id", manifest.id)
            span.set_tag("plugin_version", manifest.version)

            # Digital signature verification — advisory unless the bundle
            # itself declares a signature, in which case it must verify or
            # the load is rejected outright.
            signature = bundle.get("signature")
            publisher_public_key = bundle.get("publisher_public_key")
            signature_verified = False
            if signature and publisher_public_key:
                from app.plugins.signing import verify_signature
                if not verify_signature(bundle["code"], signature, publisher_public_key):
                    raise PluginLoadError(f"plugin {manifest.id} signature verification failed")
                signature_verified = True
            else:
                log.warning("plugin %s has no digital signature — loading unsigned code", manifest.id)
            span.set_tag("signature_verified", signature_verified)

            # Plugin Trust Model: signature_verified only proves the bundle
            # wasn't tampered with relative to WHATEVER key it shipped —
            # trusted_publisher additionally proves that key belongs to a
            # REGISTERED, admin-verified marketplace publisher (the same
            # marketplace_publishers.verified flag the admin-verify
            # endpoint already sets), not just any self-declared key.
            trusted_publisher = False
            if signature_verified:
                from app.marketplace.publishers import get_publisher_service
                publisher = await get_publisher_service().get_by_item(marketplace_item_id)
                if (
                    publisher and publisher.get("verified")
                    and publisher.get("public_key_pem") == publisher_public_key
                ):
                    trusted_publisher = True
            span.set_tag("trusted_publisher", trusted_publisher)

            # Version compatibility (reuses the same comparator Marketplace already ships)
            from app.marketplace.dependencies import version_satisfies
            if not version_satisfies(PLATFORM_VERSION, f">={manifest.min_platform_version}"):
                raise PlatformVersionError(manifest.id, f"requires platform >= {manifest.min_platform_version}")
            if manifest.max_platform_version and not version_satisfies(
                PLATFORM_VERSION, f"<={manifest.max_platform_version}"
            ):
                raise PlatformVersionError(manifest.id, f"requires platform <= {manifest.max_platform_version}")

            # Permission declaration validation (reuses Marketplace's allowlist check, not reimplemented)
            unknown = validate_permissions(manifest)
            if unknown:
                raise PluginLoadError(f"manifest declares unknown capabilities: {unknown}")

            # Dependency resolution — same graph, same table, same cycle/missing/
            # version logic the Marketplace phase already shipped and tested.
            from app.marketplace.dependencies import get_dependency_service
            await get_dependency_service().resolve_install_order(marketplace_item_id)

            # Plugin-to-plugin dependency + version-constraint enforcement.
            # manifest.dependencies (PluginDependencySpec, each with its own
            # version_constraint) names other PLUGINS by manifest id, a
            # separate namespace from the marketplace-catalog item graph
            # resolved just above, so it can't be synced into that graph.
            # Checked here instead, against what's actually installed and
            # enabled for this org, reusing the same version_satisfies()
            # comparator already imported above — not reimplemented.
            for dep in manifest.dependencies:
                dep_row = await self._find_installation_by_plugin_id(org_id, dep.plugin_id)
                if dep_row is None or dep_row["status"] != "enabled":
                    if dep.optional:
                        continue
                    raise PluginDependencyError(manifest.id, dep.plugin_id, "not installed and enabled for this organization")
                if not version_satisfies(dep_row["version"], dep.version_constraint):
                    raise PluginDependencyError(
                        manifest.id, dep.plugin_id,
                        f"installed version {dep_row['version']} does not satisfy {dep.version_constraint!r}",
                    )

            # Automatic Migration Support: the previous installation row
            # (if any) is read BEFORE _upsert_installation overwrites its
            # version, so an upgrade can be distinguished from a first
            # install/no-op re-load.
            previous_installation = await self._find_installation(org_id, marketplace_item_id)

            installation = await self._upsert_installation(
                org_id=org_id, marketplace_item_id=marketplace_item_id,
                manifest=manifest, actor_id=actor_id, signature_verified=signature_verified,
                trusted_publisher=trusted_publisher,
            )
            installation_id = str(installation["id"])
            span.set_tag("installation_id", installation_id)
            is_upgrade = (
                previous_installation is not None
                and previous_installation["version"] != manifest.version
            )

            sensitive = [c for c in manifest.required_permissions if c in _SENSITIVE_CAPABILITIES]
            if sensitive and not installation["approved"]:
                await self._log_health(installation_id, "error", "awaiting approval for sensitive capabilities")
                raise PluginNotApprovedError(manifest.id)

            from app.sandbox import get_sandbox_manager
            manager = get_sandbox_manager()
            try:
                worker = await manager.spawn_worker(
                    installation_id=installation_id, org_id=org_id, plugin_id=manifest.id,
                    entry_point=manifest.entry_point, code=bundle["code"], config=installation["config"],
                    network_domains=manifest.network_domains,
                )
            except Exception as exc:
                await self._log_health(installation_id, "error", str(exc))
                await self._set_status(installation_id, "failed")
                raise PluginImportError(manifest.id, str(exc)) from exc

            from app.plugins.adapters import adapt_registrations
            try:
                if is_upgrade:
                    # migrate() sees the OLD (pre-upgrade) config — worker
                    # was just spawned with installation["config"], which
                    # _upsert_installation's ON CONFLICT clause deliberately
                    # never touches. A returned dict is persisted as the
                    # installation's new config for every future load/
                    # enable; a raised exception aborts the upgrade below,
                    # same as a register() failure.
                    migrated_config = await worker.call(
                        "lifecycle", method="migrate",
                        args=[previous_installation["version"], manifest.version], timeout=15,
                    )
                    if isinstance(migrated_config, dict):
                        await self._persist_config(installation_id, migrated_config)
                        installation["config"] = migrated_config
                await worker.call("lifecycle", method="on_install", timeout=15)
                await worker.call("lifecycle", method="on_enable", timeout=15)
                registrations = await worker.call("register", timeout=15)
                # Reconstructing real registry objects (e.g. a pydantic
                # ToolSchema) from the worker's JSON-safe records can itself
                # raise (a plugin-declared tool name failing validation) —
                # this must hit the same failure path as a worker.call()
                # error, not propagate uncaught past load()'s documented
                # "never raises into the marketplace install transaction"
                # contract.
                adapt_registrations(installation_id, registrations)
            except Exception as exc:
                await manager.stop_worker(installation_id)
                await self._log_health(installation_id, "error", f"activation failed: {exc}")
                await self._set_status(installation_id, "failed")
                raise PluginImportError(manifest.id, str(exc)) from exc

            self._instances[installation_id] = worker
            await self._set_status(installation_id, "enabled")
            await self._log_health(installation_id, "load", f"loaded {manifest.id}@{manifest.version}")
            return installation

    async def unload(self, installation_id: str) -> None:
        worker = self._instances.pop(installation_id, None)
        if worker is not None:
            try:
                await worker.call("lifecycle", method="on_disable", timeout=10)
            except Exception as exc:
                log.warning("plugin %s raised during on_disable (unload): %s", installation_id, exc)
            from app.plugins.adapters import unadapt_registrations
            unadapt_registrations(installation_id)
            try:
                await worker.call("lifecycle", method="on_uninstall", timeout=10)
            except Exception as exc:
                log.warning("plugin %s raised during on_uninstall: %s", installation_id, exc)
            from app.sandbox import get_sandbox_manager
            await get_sandbox_manager().stop_worker(installation_id)
        await self._set_status(installation_id, "uninstalled")
        await self._log_health(installation_id, "unload", "unloaded")

    async def find_installation(self, org_id: str, marketplace_item_id: str) -> Optional[dict[str, Any]]:
        return await self._find_installation(org_id, marketplace_item_id)

    async def disable(self, installation_id: str) -> None:
        """Pause a plugin without uninstalling it — unlike unload(), the
        Worker process/container is kept alive (its lifetime matches the
        original in-process design's "keep the instance resident, just
        unregister it" semantics) so enable() can bring it back without
        paying spawn latency again or re-resolving dependencies."""
        worker = self._instances.get(installation_id)
        row = await self._get_installation(installation_id)
        if row is None:
            raise PluginLoadError(f"installation {installation_id} not found")
        if worker is not None:
            try:
                await worker.call("lifecycle", method="on_disable", timeout=10)
            except Exception as exc:
                log.warning("plugin %s raised during disable: %s", installation_id, exc)
            from app.plugins.adapters import unadapt_registrations
            unadapt_registrations(installation_id)
        await self._set_status(installation_id, "disabled")
        await self._log_health(installation_id, "unload", "disabled")

    async def enable(self, installation_id: str) -> None:
        """Re-activate a previously disabled plugin. If the Worker is
        still alive (common case: disable/enable in the same process
        lifetime), just re-register against it; otherwise re-run the full
        load() using the installation's own marketplace_item_id (spawns a
        fresh Worker)."""
        row = await self._get_installation(installation_id)
        if row is None:
            raise PluginLoadError(f"installation {installation_id} not found")

        sensitive_declared = await self._has_sensitive_permissions(installation_id)
        if sensitive_declared and not row["approved"]:
            raise PluginNotApprovedError(row["plugin_id"])

        if row["status"] == "enabled" and installation_id in self._instances:
            # Already active — a redundant enable() call (double-click,
            # retried request) must not call register() a second time
            # without an intervening unregister(); for an EVENT_LISTENER
            # plugin that would subscribe the same handler twice.
            return

        worker = self._instances.get(installation_id)
        if worker is not None and worker.is_alive:
            from app.plugins.adapters import adapt_registrations, unadapt_registrations
            try:
                await worker.call("lifecycle", method="on_enable", timeout=15)
                registrations = await worker.call("register", timeout=15)
                # Unadapt whatever this worker registered last time BEFORE
                # re-adapting the fresh set — without this, a retry after
                # a previously-failed re-register (status left at
                # "failed", stale entries still in _ADAPTED from the last
                # *successful* registration) would re-subscribe an
                # EVENT_LISTENER's handler a second time instead of
                # replacing it, since adapt_registrations always creates
                # new proxy objects and EventBus matches by identity.
                unadapt_registrations(installation_id)
                adapt_registrations(installation_id, registrations)
            except Exception as exc:
                await self._log_health(installation_id, "error", f"re-register failed: {exc}")
                await self._set_status(installation_id, "failed")
                raise PluginImportError(row["plugin_id"], str(exc)) from exc
            await self._set_status(installation_id, "enabled")
            await self._log_health(installation_id, "load", "re-enabled (worker alive)")
        else:
            await self.load(row["marketplace_item_id"], org_id=str(row["organization_id"]))

    async def update_config(self, installation_id: str, new_config: dict[str, Any]) -> None:
        row = await self._persist_config(installation_id, new_config)
        if row is None:
            raise PluginLoadError(f"installation {installation_id} not found")
        worker = self._instances.get(installation_id)
        if worker is not None and worker.is_alive:
            try:
                await worker.call("lifecycle", method="on_config_change", args=[new_config], timeout=10)
            except Exception as exc:
                log.warning("plugin %s raised during on_config_change: %s", installation_id, exc)

    async def _persist_config(self, installation_id: str, new_config: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Raw config UPDATE shared by update_config() (admin-initiated,
        additionally fires on_config_change) and load()'s migrate() step
        (upgrade-initiated — on_config_change is deliberately NOT fired
        there, since migrate() already IS the plugin's chance to react to
        its own config transition)."""
        from app.core.db import get_pool
        async with get_pool().acquire() as conn:
            row = await conn.fetchrow(
                "UPDATE plugin_installations SET config=$2, updated_at=NOW() WHERE id=$1 RETURNING plugin_id, organization_id",
                uuid.UUID(installation_id), json.dumps(new_config),
            )
        return dict(row) if row else None

    async def approve(self, installation_id: str) -> None:
        from app.core.db import get_pool
        async with get_pool().acquire() as conn:
            result = await conn.execute(
                "UPDATE plugin_installations SET approved=true, updated_at=NOW() WHERE id=$1",
                uuid.UUID(installation_id),
            )
        if result == "UPDATE 0":
            raise PluginLoadError(f"installation {installation_id} not found")
        await self._log_health(installation_id, "load", "approved by admin")

    async def _has_sensitive_permissions(self, installation_id: str) -> bool:
        from app.core.db import get_pool
        async with get_pool().acquire() as conn:
            rows = await conn.fetch(
                "SELECT capability FROM plugin_permissions WHERE installation_id=$1", uuid.UUID(installation_id),
            )
        return any(r["capability"] in _SENSITIVE_CAPABILITIES for r in rows)

    async def reload(self, marketplace_item_id: str, *, org_id: str) -> dict[str, Any]:
        if os.getenv("PLUGIN_HOT_RELOAD_ENABLED", "false").lower() != "true":
            raise PermissionError("hot reload is disabled — set PLUGIN_HOT_RELOAD_ENABLED=true (dev only, never in production)")
        installation = await self._find_installation(org_id, marketplace_item_id)
        if installation is not None:
            await self.unload(str(installation["id"]))
        result = await self.load(marketplace_item_id, org_id=org_id)
        await self._log_health(str(result["id"]), "reload", "hot-reloaded")
        return result

    # ── Internal ──────────────────────────────────────────────────────────

    @staticmethod
    def _extract_bundle(assets: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
        """Single-file inline plugins only this phase (see plan's deferred
        scope) — external_url bundles are not fetched/extracted yet."""
        for asset in assets:
            if asset["asset_type"] != "inline" or not asset["content"]:
                continue
            try:
                data = json.loads(asset["content"])
            except (json.JSONDecodeError, TypeError):
                continue
            if "manifest" in data and "code" in data:
                return data
        return None

    async def _upsert_installation(
        self, *, org_id: str, marketplace_item_id: str, manifest, actor_id: Optional[str],
        signature_verified: bool = False, trusted_publisher: bool = False,
    ) -> dict[str, Any]:
        from app.core.db import get_pool
        async with get_pool().acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO plugin_installations
                     (organization_id, marketplace_item_id, plugin_id, version, status, installed_by, manifest, signature_verified, trusted_publisher)
                   VALUES ($1,$2,$3,$4,'installed',$5,$6,$7,$8)
                   ON CONFLICT (organization_id, plugin_id) DO UPDATE SET
                     marketplace_item_id=EXCLUDED.marketplace_item_id,
                     version=EXCLUDED.version, manifest=EXCLUDED.manifest,
                     signature_verified=EXCLUDED.signature_verified,
                     trusted_publisher=EXCLUDED.trusted_publisher, updated_at=NOW()
                   RETURNING *""",
                uuid.UUID(org_id), marketplace_item_id, manifest.id, manifest.version,
                uuid.UUID(actor_id) if actor_id else None, manifest.model_dump_json(),
                signature_verified, trusted_publisher,
            )
            await conn.executemany(
                """INSERT INTO plugin_permissions (installation_id, capability, granted)
                   VALUES ($1,$2,$3) ON CONFLICT (installation_id, capability) DO NOTHING""",
                [(row["id"], cap, cap not in _SENSITIVE_CAPABILITIES) for cap in manifest.required_permissions],
            )
        return normalize_installation_row(dict(row))

    async def _get_installation(self, installation_id: str) -> Optional[dict[str, Any]]:
        from app.core.db import get_pool
        async with get_pool().acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM plugin_installations WHERE id=$1", uuid.UUID(installation_id))
        return normalize_installation_row(dict(row)) if row else None

    async def _find_installation(self, org_id: str, marketplace_item_id: str) -> Optional[dict[str, Any]]:
        from app.core.db import get_pool
        async with get_pool().acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM plugin_installations WHERE organization_id=$1 AND marketplace_item_id=$2",
                uuid.UUID(org_id), marketplace_item_id,
            )
        return normalize_installation_row(dict(row)) if row else None

    async def _find_installation_by_plugin_id(self, org_id: str, plugin_id: str) -> Optional[dict[str, Any]]:
        """Looked up by plugin_id (the manifest's own stable identifier),
        not marketplace_item_id — for checking a declared plugin-to-plugin
        dependency, which names the other plugin this way."""
        from app.core.db import get_pool
        async with get_pool().acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM plugin_installations WHERE organization_id=$1 AND plugin_id=$2",
                uuid.UUID(org_id), plugin_id,
            )
        return normalize_installation_row(dict(row)) if row else None

    async def _set_status(self, installation_id: str, status: str) -> None:
        from app.core.db import get_pool
        async with get_pool().acquire() as conn:
            await conn.execute(
                "UPDATE plugin_installations SET status=$2, updated_at=NOW() WHERE id=$1",
                uuid.UUID(installation_id), status,
            )

    async def _log_health(self, installation_id: str, event: str, message: str) -> None:
        try:
            from app.core.db import get_pool
            async with get_pool().acquire() as conn:
                await conn.execute(
                    "INSERT INTO plugin_health_log (installation_id, event, message) VALUES ($1,$2,$3)",
                    uuid.UUID(installation_id), event, message,
                )
        except Exception:
            log.warning("plugin health log write failed for %s", installation_id, exc_info=True)


_loader: PluginLoader | None = None


def get_plugin_loader() -> PluginLoader:
    global _loader
    if _loader is None:
        _loader = PluginLoader()
    return _loader
