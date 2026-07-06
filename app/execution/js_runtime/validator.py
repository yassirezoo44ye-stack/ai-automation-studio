"""
Pre-execution validator.

Checks the workspace state before any process is spawned and returns
a structured diagnostics report. The RuntimeManager calls this before
every execution attempt.
"""
from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


@dataclass
class ValidationReport:
    """Result of pre-execution workspace validation."""
    ok: bool
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    diagnostics: dict = field(default_factory=dict)

    def add_issue(self, msg: str) -> None:
        self.issues.append(msg)
        self.ok = False

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)


class WorkspaceValidator:
    """
    Validates a JavaScript workspace before execution.

    Checks:
      - package.json exists
      - lockfile consistency (no conflicts)
      - node_modules presence
      - node binary version
      - requested script existence
      - external service dependencies (DB, queues) that can't run in sandbox
    """

    # Dependencies that require external services to be running.
    _EXTERNAL_DEPS: dict[str, str] = {
        "pg": "PostgreSQL", "pg-pool": "PostgreSQL",
        "mysql": "MySQL", "mysql2": "MySQL",
        "mongoose": "MongoDB", "mongodb": "MongoDB",
        "redis": "Redis", "ioredis": "Redis",
        "bullmq": "Redis/BullMQ", "bull": "Redis/Bull",
        "prisma": "Database (Prisma)", "@prisma/client": "Database (Prisma)",
        "typeorm": "Database (TypeORM)", "sequelize": "Database (Sequelize)",
        "knex": "Database (Knex)", "amqplib": "RabbitMQ", "kafkajs": "Kafka",
    }

    def validate(
        self,
        ws: Path,
        *,
        script: Optional[str] = None,
        require_modules: bool = False,
    ) -> ValidationReport:
        report = ValidationReport(ok=True)

        self._check_package_json(ws, report, script)
        self._check_lockfile_conflicts(ws, report)
        if require_modules:
            self._check_node_modules(ws, report)
        self._check_node_version(report)
        self._check_external_services(ws, report)

        report.diagnostics["workspace"] = str(ws)
        report.diagnostics["has_package_json"] = (ws / "package.json").exists()
        report.diagnostics["has_node_modules"] = (ws / "node_modules").exists()

        return report

    # ── Private checks ────────────────────────────────────────────────────────

    def _check_package_json(
        self, ws: Path, report: ValidationReport, script: Optional[str]
    ) -> None:
        pkg_json = ws / "package.json"
        if not pkg_json.exists():
            report.add_issue("package.json not found")
            return
        try:
            data = json.loads(pkg_json.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            report.add_issue(f"package.json is not valid JSON: {exc}")
            return

        if script:
            scripts = data.get("scripts", {})
            if script not in scripts:
                available = sorted(scripts.keys())
                report.add_issue(
                    f'Script "{script}" not defined in package.json. '
                    f"Available: {', '.join(available) or 'none'}"
                )
        report.diagnostics["package_name"] = data.get("name", "<unnamed>")
        report.diagnostics["package_version"] = data.get("version", "?")

    def _check_lockfile_conflicts(self, ws: Path, report: ValidationReport) -> None:
        from .detector import _LOCKFILE_PRIORITY
        found = [lf for lf in _LOCKFILE_PRIORITY if (ws / lf).exists()]
        report.diagnostics["lockfiles"] = found
        if len(found) > 1:
            report.add_warning(
                f"Multiple lockfiles found ({', '.join(found)}). "
                "Using highest-priority one. Remove extras to avoid confusion."
            )

    def _check_node_modules(self, ws: Path, report: ValidationReport) -> None:
        if not (ws / "node_modules").exists():
            report.add_issue(
                "node_modules not found. Dependencies must be installed first."
            )

    def _check_node_version(self, report: ValidationReport) -> None:
        try:
            r = subprocess.run(
                ["node", "--version"], capture_output=True, timeout=5
            )
            if r.returncode == 0:
                ver = r.stdout.decode().strip()
                report.diagnostics["node_version"] = ver
            else:
                report.add_issue("node --version returned non-zero exit code")
        except FileNotFoundError:
            report.add_issue("node executable not found")
        except subprocess.TimeoutExpired:
            report.add_warning("node --version timed out")
        except Exception as exc:
            report.add_warning(f"Could not determine node version: {exc}")

    def _check_external_services(self, ws: Path, report: ValidationReport) -> None:
        pkg_json = ws / "package.json"
        if not pkg_json.exists():
            return
        try:
            data = json.loads(pkg_json.read_text(encoding="utf-8"))
        except Exception:
            return

        all_deps = {
            **data.get("dependencies", {}),
            **data.get("devDependencies", {}),
        }
        services: dict[str, str] = {}
        for dep, service in self._EXTERNAL_DEPS.items():
            if dep in all_deps:
                services[service] = service

        if services:
            report.diagnostics["external_services"] = list(services.values())
            report.add_warning(
                f"Project requires external services: {', '.join(services.values())}. "
                "These are not available in the sandbox — run locally with Docker."
            )
