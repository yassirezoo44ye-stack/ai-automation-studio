"""
Plugin Loader — discovery, validation, dependency resolution, version
compatibility, safe loading, hot reload (dev-only), graceful unloading.

Directly generalizes app/commands/loader.py's proven mechanism:
importlib.util.spec_from_file_location -> module_from_spec ->
sys.modules[...] -> exec_module, wrapped in try/except so one broken
plugin can never crash the loader or take down another plugin. Dependency
resolution and version-constraint checking are NOT reimplemented here —
they delegate straight to app.marketplace.dependencies (the same
Kahn's-algorithm resolver and version_satisfies comparator the Marketplace
phase already shipped and tested).
"""
from __future__ import annotations

import importlib.util
import json
import logging
import os
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Optional

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

_TMP_DIR = Path(tempfile.gettempdir()) / "axon_plugins"


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


# Capabilities that require explicit admin approval before a plugin may be enabled.
_SENSITIVE_CAPABILITIES = frozenset({
    "network", "filesystem", "shell_exec", "credentials_read", "third_party_api",
})


class PluginLoader:
    def __init__(self) -> None:
        # installation_id -> live PluginBase instance, for enable/disable/unload
        self._instances: dict[str, Any] = {}

    async def load(self, marketplace_item_id: str, *, org_id: str, actor_id: Optional[str] = None) -> dict[str, Any]:
        """Fetch, validate, resolve, and activate a plugin for one org.
        Best-effort by design (see installer.py's stage 7 call site) — never
        raises into the marketplace install transaction; callers that need
        the failure reason should catch PluginLoadError themselves."""
        from app.marketplace.assets import get_asset_service
        from app.marketplace.store import get_marketplace_store
        from app.plugins.manifest import parse_manifest, validate_permissions, ManifestValidationError

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

        installation = await self._upsert_installation(
            org_id=org_id, marketplace_item_id=marketplace_item_id,
            manifest=manifest, actor_id=actor_id,
        )
        installation_id = str(installation["id"])

        sensitive = [c for c in manifest.required_permissions if c in _SENSITIVE_CAPABILITIES]
        if sensitive and not installation["approved"]:
            await self._log_health(installation_id, "error", "awaiting approval for sensitive capabilities")
            raise PluginNotApprovedError(manifest.id)

        try:
            instance = self._import_and_instantiate(installation_id, manifest, bundle["code"])
        except Exception as exc:
            await self._log_health(installation_id, "error", str(exc))
            await self._set_status(installation_id, "failed")
            raise PluginImportError(manifest.id, str(exc)) from exc

        ctx = self._make_context(installation_id, manifest.id, org_id, installation["config"])
        try:
            await instance.on_install(ctx)
            await instance.on_enable(ctx)
            instance.register(ctx)
        except Exception as exc:
            self._cleanup_module(installation_id)
            await self._log_health(installation_id, "error", f"register() failed: {exc}")
            await self._set_status(installation_id, "failed")
            raise PluginImportError(manifest.id, str(exc)) from exc

        self._instances[installation_id] = instance
        await self._set_status(installation_id, "enabled")
        await self._log_health(installation_id, "load", f"loaded {manifest.id}@{manifest.version}")
        return installation

    async def unload(self, installation_id: str) -> None:
        instance = self._instances.pop(installation_id, None)
        if instance is not None:
            row = await self._get_installation(installation_id)
            ctx = self._make_context(
                installation_id, row["plugin_id"], str(row["organization_id"]) if row else None,
                row["config"] if row else {},
            )
            try:
                await instance.on_disable(ctx)
                instance.unregister(ctx)
                await instance.on_uninstall(ctx)
            except Exception as exc:
                log.warning("plugin %s raised during unload: %s", installation_id, exc)
        module_name = f"_axon_plugin_{installation_id}"
        sys.modules.pop(module_name, None)
        await self._set_status(installation_id, "uninstalled")
        await self._log_health(installation_id, "unload", "unloaded")

    async def find_installation(self, org_id: str, marketplace_item_id: str) -> Optional[dict[str, Any]]:
        return await self._find_installation(org_id, marketplace_item_id)

    async def disable(self, installation_id: str) -> None:
        """Pause a plugin without uninstalling it — unlike unload(), the
        plugin_installations row survives with status='disabled' so
        enable() can bring it back without re-resolving dependencies."""
        instance = self._instances.get(installation_id)
        row = await self._get_installation(installation_id)
        if row is None:
            raise PluginLoadError(f"installation {installation_id} not found")
        if instance is not None:
            ctx = self._make_context(installation_id, row["plugin_id"], str(row["organization_id"]), row["config"])
            try:
                await instance.on_disable(ctx)
                instance.unregister(ctx)
            except Exception as exc:
                log.warning("plugin %s raised during disable: %s", installation_id, exc)
        await self._set_status(installation_id, "disabled")
        await self._log_health(installation_id, "unload", "disabled")

    async def enable(self, installation_id: str) -> None:
        """Re-activate a previously disabled plugin. If the process still
        holds the loaded module (common case: disable/enable in the same
        process lifetime), just re-register; otherwise re-run the full
        load() using the installation's own marketplace_item_id."""
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

        instance = self._instances.get(installation_id)
        if instance is not None:
            ctx = self._make_context(installation_id, row["plugin_id"], str(row["organization_id"]), row["config"])
            try:
                await instance.on_enable(ctx)
                instance.register(ctx)
            except Exception as exc:
                await self._log_health(installation_id, "error", f"re-register failed: {exc}")
                await self._set_status(installation_id, "failed")
                raise PluginImportError(row["plugin_id"], str(exc)) from exc
            await self._set_status(installation_id, "enabled")
            await self._log_health(installation_id, "load", "re-enabled (in-memory)")
        else:
            await self.load(row["marketplace_item_id"], org_id=str(row["organization_id"]))

    async def update_config(self, installation_id: str, new_config: dict[str, Any]) -> None:
        from app.core.db import get_pool
        async with get_pool().acquire() as conn:
            row = await conn.fetchrow(
                "UPDATE plugin_installations SET config=$2, updated_at=NOW() WHERE id=$1 RETURNING plugin_id, organization_id",
                uuid.UUID(installation_id), json.dumps(new_config),
            )
        if row is None:
            raise PluginLoadError(f"installation {installation_id} not found")
        instance = self._instances.get(installation_id)
        if instance is not None:
            ctx = self._make_context(installation_id, row["plugin_id"], str(row["organization_id"]), new_config)
            try:
                await instance.on_config_change(ctx, new_config)
            except Exception as exc:
                log.warning("plugin %s raised during on_config_change: %s", installation_id, exc)

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

    def _import_and_instantiate(self, installation_id: str, manifest, code: str) -> Any:
        from app.plugins.base import PluginBase

        _TMP_DIR.mkdir(parents=True, exist_ok=True)
        module_name = f"_axon_plugin_{installation_id}"
        file_path = _TMP_DIR / f"{module_name}.py"
        file_path.write_text(code, encoding="utf-8")

        spec = importlib.util.spec_from_file_location(module_name, file_path)
        if spec is None or spec.loader is None:
            raise PluginImportError(manifest.id, "could not create module spec")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)  # type: ignore[attr-defined]
        except Exception as exc:
            # Mirrors app/commands/loader.py's isolation guarantee: a
            # SyntaxError or any other exception while executing the
            # plugin's own module body must not propagate as a raw,
            # untyped exception — every caller of this method (not just
            # load(), which happens to also wrap this call) can rely on
            # only ever seeing PluginImportError from a broken plugin.
            self._cleanup_module(installation_id)
            raise PluginImportError(manifest.id, f"module exec failed: {exc}") from exc

        class_name = manifest.entry_point.split(":", 1)[1]
        cls = getattr(module, class_name, None)
        if cls is None or not (isinstance(cls, type) and issubclass(cls, PluginBase)):
            self._cleanup_module(installation_id)
            raise PluginImportError(manifest.id, f"entry_point class {class_name!r} not found or not a PluginBase subclass")
        return cls()

    @staticmethod
    def _cleanup_module(installation_id: str) -> None:
        """Remove a failed load's stale sys.modules entry and temp source
        file — otherwise both leak indefinitely for any installation that
        fails after exec_module succeeds (e.g. register() itself raising)."""
        module_name = f"_axon_plugin_{installation_id}"
        sys.modules.pop(module_name, None)
        file_path = _TMP_DIR / f"{module_name}.py"
        try:
            file_path.unlink(missing_ok=True)
        except OSError:
            pass

    def _make_context(self, installation_id: str, plugin_id: str, org_id: Optional[str], config: dict) -> Any:
        from app.plugins.base import PluginContext
        return PluginContext(
            plugin_id=plugin_id, installation_id=installation_id, organization_id=org_id,
            config=config or {}, logger=logging.getLogger(f"plugin.{plugin_id}"),
        )

    async def _upsert_installation(self, *, org_id: str, marketplace_item_id: str, manifest, actor_id: Optional[str]) -> dict[str, Any]:
        from app.core.db import get_pool
        async with get_pool().acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO plugin_installations
                     (organization_id, marketplace_item_id, plugin_id, version, status, installed_by, manifest)
                   VALUES ($1,$2,$3,$4,'installed',$5,$6)
                   ON CONFLICT (organization_id, plugin_id) DO UPDATE SET
                     marketplace_item_id=EXCLUDED.marketplace_item_id,
                     version=EXCLUDED.version, manifest=EXCLUDED.manifest, updated_at=NOW()
                   RETURNING *""",
                uuid.UUID(org_id), marketplace_item_id, manifest.id, manifest.version,
                uuid.UUID(actor_id) if actor_id else None, manifest.model_dump_json(),
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
