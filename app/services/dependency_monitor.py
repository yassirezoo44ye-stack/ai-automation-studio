"""Dependency Monitor — detects missing/broken imports and env-var gaps."""
from __future__ import annotations

import importlib
import logging
import os
from app.services.registry import BaseService

log = logging.getLogger(__name__)

_REQUIRED_PACKAGES = [
    "fastapi", "uvicorn", "anthropic", "asyncpg",
    "stripe", "pydantic", "starlette",
]

_REQUIRED_ENV_VARS = [
    "DATABASE_URL", "SESSION_SECRET",
]

_OPTIONAL_ENV_VARS = [
    "ANTHROPIC_API_KEY", "STRIPE_SECRET_KEY",
    "GOOGLE_CLIENT_ID", "GITHUB_CLIENT_ID",
]


class DependencyMonitorService(BaseService):
    name        = "dependency_monitor"
    description = "Checks Python package availability and required env-vars every 5 min"
    interval_s  = 300.0
    auto_restart = True

    async def tick(self) -> None:
        from app.core.observability.metrics import get_metrics
        m = get_metrics()

        # Package checks
        missing_pkgs: list[str] = []
        for pkg in _REQUIRED_PACKAGES:
            try:
                importlib.import_module(pkg)
            except ImportError:
                missing_pkgs.append(pkg)

        # Env-var checks
        missing_required = [v for v in _REQUIRED_ENV_VARS if not os.getenv(v)]
        missing_optional = [v for v in _OPTIONAL_ENV_VARS if not os.getenv(v)]

        m.gauge("dependency_missing_packages", "Required Python packages not installed").set(len(missing_pkgs))
        m.gauge("dependency_missing_env_required", "Missing required env vars").set(len(missing_required))
        m.gauge("dependency_missing_env_optional", "Missing optional env vars").set(len(missing_optional))

        if missing_pkgs:
            log.error("Dependency monitor: missing packages: %s", missing_pkgs)
        if missing_required:
            log.error("Dependency monitor: missing required env vars: %s", missing_required)
        if missing_optional:
            log.warning("Dependency monitor: missing optional env vars: %s", missing_optional)

        log.debug("Dependency monitor tick complete — pkgs=%d env_req=%d env_opt=%d",
                  len(missing_pkgs), len(missing_required), len(missing_optional))
