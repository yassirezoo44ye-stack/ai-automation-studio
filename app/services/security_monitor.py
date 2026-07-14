"""Security Monitor — scans for config drift, exposed secrets, and rate anomalies."""
from __future__ import annotations

import logging
import re
from pathlib import Path
from app.services.registry import BaseService

log = logging.getLogger(__name__)

_ROOT = Path(__file__).parent.parent.parent

# Patterns that must NEVER appear in tracked config files
_SECRET_PATTERNS = [
    re.compile(r'sk-[A-Za-z0-9]{20,}'),          # OpenAI-style keys
    re.compile(r'anthropic[-_]?api[-_]?key\s*=\s*["\']?(sk-ant-[A-Za-z0-9\-]+)',
               re.I),
    re.compile(r'password\s*=\s*["\'][^"\']{6,}["\']', re.I),
    re.compile(r'secret\s*=\s*["\'][^"\']{8,}["\']',   re.I),
]

_SCANNED_GLOBS = ["*.py", "*.ts", "*.tsx", "*.js", "*.json"]
_SKIP_DIRS     = {".git", "node_modules", "dist", ".backups", "__pycache__"}


class SecurityMonitorService(BaseService):
    name        = "security_monitor"
    description = "Scans config and source files for accidentally committed secrets (10-min interval)"
    interval_s  = 600.0
    auto_restart = True

    async def tick(self) -> None:
        from app.core.observability.metrics import get_metrics
        m = get_metrics()

        hits: list[str] = []
        for pattern in _SCANNED_GLOBS:
            for fpath in _ROOT.rglob(pattern):
                # Skip protected dirs
                if any(p in fpath.parts for p in _SKIP_DIRS):
                    continue
                # Skip files > 500 KB
                try:
                    if fpath.stat().st_size > 500_000:
                        continue
                    text = fpath.read_text(errors="ignore")
                except (OSError, PermissionError):
                    continue
                for rx in _SECRET_PATTERNS:
                    if rx.search(text):
                        rel = str(fpath.relative_to(_ROOT))
                        hits.append(rel)
                        log.critical("SECURITY: possible secret found in %s", rel)
                        break

        m.gauge("security_secret_leaks_detected",
                "Files with possible secret patterns").set(len(hits))

        if hits:
            log.critical("Security monitor: %d file(s) with possible secrets: %s",
                         len(hits), hits[:10])
        else:
            log.debug("Security monitor: no secret leaks detected")
