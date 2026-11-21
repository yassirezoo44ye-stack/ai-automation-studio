"""Read-only configuration evidence for isolated App Builder activation.

Run this file directly with python -B. It deliberately imports no Flow modules,
AI/provider SDKs, or database clients. It never creates files, probes with a
write, starts a VM, authenticates to a provider, or prints environment values.
A successful configuration check is not live verification or deployment approval.
"""
from __future__ import annotations

import argparse
from collections.abc import Mapping
from importlib import metadata
import json
import os
from pathlib import Path
import re

SANDBOX_KEYS = ("VERCEL_TOKEN", "VERCEL_TEAM_ID", "VERCEL_PROJECT_ID")
SDK_VERSION = "1.0.0"


def configuration_report(
    environment: Mapping[str, str] | None = None,
    *,
    expected_commit: str | None = None,
    expected_service: str | None = None,
) -> dict:
    """Read presence/metadata only. Supplied targets must be public identifiers."""
    env = os.environ if environment is None else environment
    if expected_commit is not None and not re.fullmatch(r"[a-fA-F0-9]{40}", expected_commit):
        raise ValueError("Invalid expected commit")
    if expected_service is not None and not re.fullmatch(r"srv-[a-z0-9]+", expected_service):
        raise ValueError("Invalid expected service")
    checks = {}

    def record(name, status, **evidence):
        checks[name] = {"status": status, **evidence}

    present = {key: bool(env.get(key, "").strip()) for key in SANDBOX_KEYS}
    record("sandbox_configuration", "PASS" if all(present.values()) else "FAIL", present=present)
    record("service_identity", "NOT_RUN" if expected_service is None else
           "PASS" if env.get("RENDER_SERVICE_ID") == expected_service else "FAIL")
    record("release_identity", "NOT_RUN" if expected_commit is None else
           "PASS" if env.get("RENDER_GIT_COMMIT", "").lower() == expected_commit.lower() else "FAIL")
    record("mount_enforcement", "PASS" if env.get("REQUIRE_WORKSPACE_MOUNT", "").lower() == "true" else "FAIL")
    # A reviewed copy can be piped into python -B -. In that mode __file__
    # is <stdin>; use the service Shell's working directory, not its parent.
    project_root = Path.cwd() if __file__ == "<stdin>" else Path(__file__).resolve().parent.parent
    root = Path(env.get("WORKSPACES_DIR") or str(project_root / "workspaces"))
    try:
        directory = root.is_dir()
        mounted = directory and root.is_mount()
        record("workspace_mount", "PASS" if mounted else "FAIL", exists=directory, mounted=mounted)
        # os.access is advisory; do not pretend a read-only check proves writes.
        record("write_permission_hint", "INCONCLUSIVE", permission_hint=directory and os.access(root, os.W_OK),
               write_probe_executed=False)
        if directory:
            projects = 0
            links = 0
            for child in root.iterdir():
                if child.is_symlink():
                    links += 1
                elif child.is_dir():
                    projects += 1
            record("workspace_inventory", "PASS", directories_at_root=projects, symlinks_skipped=links)
        else:
            record("workspace_inventory", "NOT_RUN")
    except OSError:
        # Error strings and paths can contain sensitive configuration. Omit them.
        record("workspace_mount", "INCONCLUSIVE")
        record("workspace_inventory", "INCONCLUSIVE")
        record("write_permission_hint", "INCONCLUSIVE", write_probe_executed=False)
    try:
        installed = metadata.version("vercel-sandbox")
        record("sandbox_sdk", "PASS" if installed == SDK_VERSION else "FAIL",
               installed=True, expected_version=SDK_VERSION, version_matches=installed == SDK_VERSION)
    except metadata.PackageNotFoundError:
        record("sandbox_sdk", "FAIL", installed=False, expected_version=SDK_VERSION)
    except Exception:
        record("sandbox_sdk", "INCONCLUSIVE")
    required = ("sandbox_configuration", "service_identity", "release_identity", "mount_enforcement",
                "workspace_mount", "sandbox_sdk", "workspace_inventory")
    statuses = {checks[name]["status"] for name in required}
    result = "FAIL" if "FAIL" in statuses else "PASS" if statuses == {"PASS"} else "INCONCLUSIVE"
    return {
        "scope": "read_only_configuration",
        "result": result,
        "checks": checks,
        "not_verified": ["provider_authentication", "provider_capacity_and_billing", "actual_writes",
                         "backup_and_restore", "cross_restart_persistence", "browser_and_customer_journeys", "automatic_deploy_settings"],
        "deployment_authorized": False,
        "live_activation_verified": False,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-commit", help="Reviewed release SHA, not a secret")
    parser.add_argument("--expected-service", help="Confirmed Render service ID, not a secret")
    args = parser.parse_args(argv)
    try:
        report = configuration_report(expected_commit=args.expected_commit, expected_service=args.expected_service)
    except ValueError:
        report = {"scope": "read_only_configuration", "result": "FAIL", "error": "invalid_expected_target"}
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return {"PASS": 0, "FAIL": 1, "INCONCLUSIVE": 2}[report["result"]]


if __name__ == "__main__":
    raise SystemExit(main())
