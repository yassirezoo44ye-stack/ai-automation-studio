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
                await asyncio.sleep(base_delay * (2 ** attempt))
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


async def maintenance_loop() -> None:
    """Background task: run on startup then every 6 hours."""
    while True:
        await _maintenance_cycle()
        await asyncio.sleep(6 * 3600)
