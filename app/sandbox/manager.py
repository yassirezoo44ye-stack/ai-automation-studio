"""
SandboxManager — the one object app/plugins/loader.py talks to for
spawning/stopping a plugin's isolated worker. Reads a plugin
installation's already-approved plugin_permissions (Plugin SDK, migration
007) to derive SandboxLimits; no second permission-declaration table.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Optional

from app.sandbox.backends import Worker, WorkerCrashedError, get_sandbox_backend
from app.sandbox.permissions import limits_from_granted_capabilities
from app.sandbox.workspace import WorkerWorkspace

log = logging.getLogger(__name__)

_PLUGIN_BASE_SOURCE_PATH = __import__("pathlib").Path(__file__).parent.parent / "plugins" / "base.py"


class SandboxManager:
    def __init__(self) -> None:
        self._workers: dict[str, Worker] = {}          # installation_id -> Worker
        self._workspaces: dict[str, WorkerWorkspace] = {}
        self._worker_row_ids: dict[str, str] = {}       # installation_id -> sandbox_workers.id
        self._org_ids: dict[str, str] = {}              # installation_id -> organization_id
        # installation_id -> the kwargs spawn_worker() was last called with —
        # cached so _respawn() can call spawn_worker() again after a crash
        # without the caller (a WorkerProxyCallable that only knows
        # installation_id) having to re-supply plugin code/entry_point/config.
        self._spawn_kwargs: dict[str, dict[str, Any]] = {}
        # installation_id -> True while a crash-recovery respawn is already
        # in flight, so concurrent proxy calls that hit the same crashed
        # worker don't each independently spawn a duplicate replacement.
        self._respawn_locks: dict[str, asyncio.Lock] = {}

    async def _granted_capabilities(self, installation_id: str) -> set[str]:
        from app.core.db import get_pool
        async with get_pool().acquire() as conn:
            rows = await conn.fetch(
                "SELECT capability FROM plugin_permissions WHERE installation_id=$1 AND granted=true",
                uuid.UUID(installation_id),
            )
        return {r["capability"] for r in rows}

    async def spawn_worker(
        self, *, installation_id: str, org_id: str, plugin_id: str,
        entry_point: str, code: str, config: Optional[dict] = None,
        network_domains: Optional[list[str]] = None,
    ) -> Worker:
        existing = self._workers.get(installation_id)
        if existing is not None and existing.is_alive:
            return existing

        granted = await self._granted_capabilities(installation_id)
        limits = limits_from_granted_capabilities(granted, network_domains=network_domains)

        workspace = WorkerWorkspace(installation_id)
        paths = workspace.create()
        (paths.workspace).mkdir(parents=True, exist_ok=True)
        (paths.workspace / "plugin_base.py").write_text(
            _PLUGIN_BASE_SOURCE_PATH.read_text(encoding="utf-8"), encoding="utf-8",
        )
        (paths.workspace / "plugin_code.py").write_text(code, encoding="utf-8")

        backend = await get_sandbox_backend()
        row_id = await self._insert_worker_row(
            org_id=org_id, installation_id=installation_id, backend=backend.__class__.__name__.lower().replace("backend", ""),
        )

        async def context_rpc_handler(method: str, args: list, kwargs: dict) -> Any:
            return await self._service_context_rpc(installation_id, method, args, kwargs)

        try:
            worker = await backend.spawn(
                installation_id=installation_id, workspace_dir=paths.workspace,
                entry_point=entry_point, plugin_id=plugin_id, org_id=org_id,
                config=config or {}, limits=limits, secret_env={},
                context_rpc_handler=context_rpc_handler,
            )
        except Exception:
            workspace.cleanup()
            await self._set_worker_status(row_id, "crashed")
            raise

        self._workers[installation_id] = worker
        self._workspaces[installation_id] = workspace
        self._worker_row_ids[installation_id] = row_id
        self._org_ids[installation_id] = org_id
        self._spawn_kwargs[installation_id] = {
            "installation_id": installation_id, "org_id": org_id, "plugin_id": plugin_id,
            "entry_point": entry_point, "code": code, "config": config,
            "network_domains": network_domains,
        }
        await self._set_worker_status(row_id, "running", pid_or_container_id=worker.pid_or_container_id)
        await self._log_event(row_id, org_id, "lifecycle", "info", f"worker started (backend={worker.backend})")
        return worker

    async def stop_worker(self, installation_id: str) -> None:
        worker = self._workers.pop(installation_id, None)
        row_id = self._worker_row_ids.pop(installation_id, None)
        workspace = self._workspaces.pop(installation_id, None)
        self._org_ids.pop(installation_id, None)
        self._spawn_kwargs.pop(installation_id, None)
        self._respawn_locks.pop(installation_id, None)
        if worker is not None:
            try:
                await worker.stop()
            except Exception as exc:
                log.warning("sandbox worker stop failed for %s: %s", installation_id, exc)
        if row_id:
            await self._set_worker_status(row_id, "stopped", stopped=True)
        if workspace is not None:
            workspace.cleanup()

    def get_worker(self, installation_id: str) -> Optional[Worker]:
        return self._workers.get(installation_id)

    async def call_worker(
        self, installation_id: str, call: str, *, method: Optional[str] = None,
        args: Optional[list] = None, kwargs: Optional[dict] = None, timeout: Optional[float] = None,
    ) -> Any:
        """Plugin Crash Recovery: dispatches to installation_id's current
        worker, transparently respawning and retrying exactly once if the
        worker had already died or dies mid-call. A second consecutive
        WorkerCrashedError is NOT retried again — propagates to the caller —
        so a plugin that crashes on every invocation doesn't respawn in an
        infinite loop on every proxy call."""
        worker = self._workers.get(installation_id)
        if worker is None or not worker.is_alive:
            worker = await self._respawn(installation_id)
        try:
            return await worker.call(call, method=method, args=args, kwargs=kwargs, timeout=timeout)
        except WorkerCrashedError:
            log.warning("sandbox worker %s crashed mid-call — attempting one respawn", installation_id)
            worker = await self._respawn(installation_id)
            return await worker.call(call, method=method, args=args, kwargs=kwargs, timeout=timeout)

    async def _respawn(self, installation_id: str) -> Worker:
        lock = self._respawn_locks.setdefault(installation_id, asyncio.Lock())
        async with lock:
            existing = self._workers.get(installation_id)
            if existing is not None and existing.is_alive:
                return existing  # another concurrent caller already respawned it
            spawn_kwargs = self._spawn_kwargs.get(installation_id)
            if spawn_kwargs is None:
                raise WorkerCrashedError(
                    f"worker for installation {installation_id} crashed and there are no "
                    "cached spawn parameters to respawn it (never spawned via this manager instance)"
                )
            row_id = self._worker_row_ids.get(installation_id)
            org_id = self._org_ids.get(installation_id, spawn_kwargs["org_id"])
            if row_id:
                await self._log_event(row_id, org_id, "lifecycle", "warning", "worker crashed — respawning")
            self._workers.pop(installation_id, None)
            return await self.spawn_worker(**spawn_kwargs)

    # ── context_rpc servicing (worker -> main process) ──────────────────────

    async def _service_context_rpc(self, installation_id: str, method: str, args: list, kwargs: dict) -> Any:
        if method == "get_secret":
            from app.plugins.secrets import get_plugin_secret
            return await get_plugin_secret(installation_id, *args, **kwargs)
        if method == "set_secret":
            from app.plugins.secrets import set_plugin_secret
            return await set_plugin_secret(installation_id, *args, **kwargs)
        if method == "storage_get":
            from app.plugins.storage import get_plugin_value
            return await get_plugin_value(installation_id, *args, **kwargs)
        if method == "storage_put":
            from app.plugins.storage import put_plugin_value
            return await put_plugin_value(installation_id, *args, **kwargs)
        if method == "storage_delete":
            from app.plugins.storage import delete_plugin_value
            return await delete_plugin_value(installation_id, *args, **kwargs)
        if method == "emit_event":
            from app.core.events import get_event_bus
            type_, data = args[0], args[1]
            # PluginContext.emit_event(type_, data) scopes by the context's
            # own organization_id field, never from inside `data` — the
            # worker never sends org_id over the wire, so it's looked up
            # here from what spawn_worker recorded for this installation.
            org_id = self._org_ids.get(installation_id)
            await get_event_bus().publish(type_, data, organization_id=org_id)
            return None
        if method == "emit_metric":
            name, value = args[0], args[1]
            row_id = self._worker_row_ids.get(installation_id)
            org_id = self._org_ids.get(installation_id)
            if row_id and org_id:
                await self._log_event(row_id, org_id, "log", "info", f"metric {name}={value}", details=kwargs)
            # Plugin Telemetry: also record into the platform's existing
            # MetricsRegistry (app/core/observability/metrics.py) — this is
            # the piece PluginContext.emit_metric() previously lacked
            # (structured-log-only, per its own docstring). Namespaced by
            # plugin_id so two different plugins' same-named metric (e.g.
            # both emitting "requests") don't collide in one gauge.
            plugin_id = (self._spawn_kwargs.get(installation_id) or {}).get("plugin_id", "unknown")
            safe_name = f"plugin_{plugin_id}_{name}".replace("-", "_").replace(".", "_")
            from app.core.observability.metrics import get_metrics
            try:
                get_metrics().gauge(safe_name, f"Plugin-emitted metric: {plugin_id}.{name}").set(float(value))
            except (TypeError, ValueError):
                log.warning("plugin %s emitted non-numeric metric %s=%r — skipped", plugin_id, name, value)
            return None
        raise ValueError(f"unknown context_rpc method {method!r}")

    # ── sandbox_workers / sandbox_events persistence ────────────────────────

    async def _insert_worker_row(self, *, org_id: str, installation_id: str, backend: str) -> str:
        from app.core.db import get_pool
        async with get_pool().acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO sandbox_workers (organization_id, plugin_installation_id, backend, status)
                   VALUES ($1,$2,$3,'starting')
                   ON CONFLICT (plugin_installation_id) DO UPDATE SET
                     backend=EXCLUDED.backend, status='starting', started_at=NOW(), stopped_at=NULL
                   RETURNING id""",
                uuid.UUID(org_id), uuid.UUID(installation_id), backend,
            )
        return str(row["id"])

    async def _set_worker_status(
        self, row_id: str, status: str, *, pid_or_container_id: Optional[str] = None, stopped: bool = False,
    ) -> None:
        from app.core.db import get_pool
        async with get_pool().acquire() as conn:
            if stopped:
                await conn.execute(
                    "UPDATE sandbox_workers SET status=$2, stopped_at=NOW() WHERE id=$1", uuid.UUID(row_id), status,
                )
            elif pid_or_container_id is not None:
                await conn.execute(
                    "UPDATE sandbox_workers SET status=$2, pid_or_container_id=$3 WHERE id=$1",
                    uuid.UUID(row_id), status, pid_or_container_id,
                )
            else:
                await conn.execute("UPDATE sandbox_workers SET status=$2 WHERE id=$1", uuid.UUID(row_id), status)

    async def _log_event(
        self, worker_row_id: str, org_id: str, event_type: str, severity: str,
        message: str, details: Optional[dict] = None,
    ) -> None:
        try:
            from app.core.db import get_pool
            import json as _json
            async with get_pool().acquire() as conn:
                await conn.execute(
                    """INSERT INTO sandbox_events (worker_id, organization_id, event_type, severity, message, details)
                       VALUES ($1,$2,$3,$4,$5,$6)""",
                    uuid.UUID(worker_row_id), uuid.UUID(org_id),
                    event_type, severity, message, _json.dumps(details or {}),
                )
        except Exception:
            log.warning("sandbox event log write failed", exc_info=True)


_manager: Optional[SandboxManager] = None


def get_sandbox_manager() -> SandboxManager:
    global _manager
    if _manager is None:
        _manager = SandboxManager()
    return _manager
