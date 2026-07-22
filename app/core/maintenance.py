"""
Self-healing maintenance subsystem.

- Rolling-window error counter with loud ALERT logging at threshold.
- Exponential-backoff retry helper for transient DB errors.
- Periodic cleanup cycle (stale files + old usage_logs).
"""
import asyncio
import shutil
import sys
import time as _time
from collections import defaultdict
from datetime import datetime

import asyncpg

from app.core.config import WORKSPACES, DIST_DIR
from app.core.reliability import compute_backoff_delay

# ── Error tracking ─────────────────────────────────────────────────────────────
_error_counts: dict[str, int] = defaultdict(int)
_error_window_start: float    = _time.time()
ERROR_WINDOW_SEC: int         = 300        # 5-minute rolling window
ERROR_ALERT_THRESHOLD: int    = 5

_maintenance_state: dict = {"last_run": None, "last_result": None}


def record_error(category: str) -> None:
    """Increment the error counter for `category`; log an ALERT once it hits the threshold."""
    global _error_window_start
    now = _time.time()
    if now - _error_window_start > ERROR_WINDOW_SEC:
        _error_counts.clear()
        _error_window_start = now
    _error_counts[category] += 1
    if _error_counts[category] == ERROR_ALERT_THRESHOLD:
        print(
            f"ALERT: '{category}' failed {_error_counts[category]}+ times "
            f"in the last {ERROR_WINDOW_SEC}s — investigate.",
            file=sys.stderr,
        )


async def with_retry(coro_fn, *args, retries: int = 3, base_delay: float = 0.5, **kwargs):
    """Retry a coroutine on transient DB / OS / timeout errors with exponential backoff."""
    last_exc: Exception = RuntimeError("no attempts made")
    for attempt in range(retries):
        try:
            return await coro_fn(*args, **kwargs)
        except (asyncpg.exceptions.PostgresConnectionError, OSError, asyncio.TimeoutError) as e:
            last_exc = e
            record_error("db_transient")
            if attempt < retries - 1:
                # No jitter here — DB/OS retries are low-volume and don't
                # need thundering-herd smoothing the way provider calls do.
                await asyncio.sleep(compute_backoff_delay(attempt, base_delay, jitter=False))
    raise last_exc


async def _maintenance_cycle() -> None:
    """Delete stale workspace/dist files and old usage_logs rows."""
    from app.core.db import get_pool  # imported here to avoid circular import at module load

    now          = _time.time()
    removed_files = 0
    try:
        for base, max_age_days in ((WORKSPACES, 7), (DIST_DIR, 3)):
            if not base.exists():
                continue
            for child in base.iterdir():
                try:
                    age_days = (now - child.stat().st_mtime) / 86400
                    if age_days > max_age_days:
                        shutil.rmtree(child, ignore_errors=True) if child.is_dir() else child.unlink(missing_ok=True)
                        removed_files += 1
                except OSError:
                    continue

        async with get_pool().acquire() as conn:
            deleted_logs = await conn.fetchval(
                "WITH d AS (DELETE FROM usage_logs WHERE created_at < NOW() - INTERVAL '30 days' RETURNING 1) "
                "SELECT COUNT(*) FROM d"
            )

        await _reconcile_active_users()
        await _reconcile_seat_quantities()

        result = {
            "removed_files": removed_files,
            "deleted_logs": deleted_logs or 0,
            "errors": dict(_error_counts),
        }
        _maintenance_state["last_run"]    = datetime.utcnow().isoformat()
        _maintenance_state["last_result"] = result
        print(f"MAINTENANCE: cleanup cycle done — {result}", file=sys.stderr)
    except Exception as e:
        record_error("maintenance")
        print(f"MAINTENANCE: cycle failed: {e}", file=sys.stderr)


async def _reconcile_active_users() -> None:
    """Gauge-style reconciliation of the active_users usage metric — sets
    (not increments) each org's count to its live member count. Best-effort:
    a failure here must never break the rest of the maintenance cycle."""
    try:
        from app.core.db import get_pool
        from app.billing import get_usage_service
        usage = get_usage_service()
        async with get_pool().acquire() as conn:
            org_ids = await conn.fetch(
                "SELECT id FROM organizations WHERE deleted_at IS NULL"
            )
            for row in org_ids:
                org_id = str(row["id"])
                count = await conn.fetchval(
                    "SELECT COUNT(*) FROM organization_members "
                    "WHERE organization_id=$1 AND deleted_at IS NULL",
                    row["id"],
                )
                try:
                    await usage.set_metric(org_id, "active_users", int(count or 0))
                except Exception:
                    continue
    except Exception:
        record_error("usage_reconciliation")


async def _reconcile_seat_quantities() -> None:
    """Periodic recovery for the best-effort seat->Stripe quantity sync
    (app/billing/subscriptions.py's sync_seat_quantity, normally triggered
    on membership change). Without this, a single failed Stripe call at
    invite/remove time would leave the subscription's billed seat count
    silently stale forever — this re-syncs every org with a real Stripe
    subscription on each maintenance cycle, matching _reconcile_active_users'
    "best-effort, never break the cycle" shape."""
    try:
        from app.core.db import get_pool
        from app.billing.subscriptions import get_org_subscription_service
        sub_svc = get_org_subscription_service()
        async with get_pool().acquire() as conn:
            org_ids = await conn.fetch(
                "SELECT organization_id FROM org_subscriptions WHERE stripe_subscription_id IS NOT NULL"
            )
        for row in org_ids:
            org_id = str(row["organization_id"])
            try:
                await sub_svc.sync_seat_quantity(org_id)
            except Exception:
                continue
    except Exception:
        record_error("seat_quantity_reconciliation")


async def maintenance_loop() -> None:
    """Background task: run on startup then every 6 hours."""
    while True:
        await _maintenance_cycle()
        await asyncio.sleep(6 * 3600)


async def process_cleanup_loop() -> None:
    """Background task: kill idle project server processes every 60 s."""
    from app.execution import process_mgr  # avoid circular import at module load
    while True:
        await asyncio.sleep(60)
        await process_mgr.cleanup_idle()
