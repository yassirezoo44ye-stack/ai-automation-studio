"""Configuration evidence must not leak secrets, write files, or certify activation."""
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pytest
from app import activation_check

SHA = "a" * 40
SERVICE = "srv-testfixture"


@pytest.fixture
def configured(tmp_path, monkeypatch):
    monkeypatch.setattr(activation_check.metadata, "version", lambda _: "1.0.0")
    monkeypatch.setattr(Path, "is_mount", lambda _: True)
    return {
        "REDIS_URL": "rediss://user:never-disclose-redis-fixture@cache.example:6379/0",
        "VERCEL_TOKEN": "never-disclose-token-fixture",
        "VERCEL_TEAM_ID": "never-disclose-team-fixture",
        "VERCEL_PROJECT_ID": "never-disclose-project-fixture",
        "RENDER_SERVICE_ID": SERVICE, "RENDER_GIT_COMMIT": SHA,
        "REQUIRE_WORKSPACE_MOUNT": "true", "WORKSPACES_DIR": str(tmp_path),
    }


def report(environment):
    return activation_check.configuration_report(environment, expected_commit=SHA, expected_service=SERVICE)


def test_reports_only_presence_and_never_certifies_live_activation(configured):
    result = report(configured)
    assert result["result"] == "PASS"
    serialized = json.dumps(result)
    assert configured["REDIS_URL"] not in serialized
    assert "never-disclose-redis-fixture" not in serialized
    assert result["checks"]["shared_redis_configuration"]["connectivity_verified"] is False
    for key in activation_check.SANDBOX_KEYS:
        assert configured[key] not in serialized
        assert result["checks"]["sandbox_configuration"]["present"][key] is True
    assert result["deployment_authorized"] is False
    assert result["live_activation_verified"] is False
    assert "provider_authentication" in result["not_verified"]
    assert result["checks"]["write_permission_hint"]["status"] == "INCONCLUSIVE"


def test_inventory_never_reads_project_contents_or_writes_probes(configured):
    root = Path(configured["WORKSPACES_DIR"])
    private = root / "project"
    private.mkdir()
    source = private / "customer-records.txt"
    source.write_text("private-customer-fixture")
    before = sorted(str(path.relative_to(root)) for path in root.rglob("*"))
    with patch.object(Path, "read_text", side_effect=AssertionError("must not read source")), \
         patch.object(Path, "read_bytes", side_effect=AssertionError("must not read source")), \
         patch.object(Path, "write_text", side_effect=AssertionError("must not write")), \
         patch.object(Path, "mkdir", side_effect=AssertionError("must not create directories")):
        result = report(configured)
    assert result["checks"]["workspace_inventory"]["directories_at_root"] == 1
    assert "private-customer-fixture" not in json.dumps(result)
    assert before == sorted(str(path.relative_to(root)) for path in root.rglob("*"))
    assert source.read_text() == "private-customer-fixture"


def test_missing_credentials_and_wrong_target_fail_closed(configured):
    configured["VERCEL_TOKEN"] = "   "
    configured["RENDER_SERVICE_ID"] = "srv-other"
    configured["RENDER_GIT_COMMIT"] = "b" * 40
    result = report(configured)
    assert result["result"] == "FAIL"
    for name in ("sandbox_configuration", "service_identity", "release_identity"):
        assert result["checks"][name]["status"] == "FAIL"


def test_ephemeral_directory_is_not_treated_as_persistent(configured, monkeypatch):
    monkeypatch.setattr(Path, "is_mount", lambda _: False)
    assert report(configured)["checks"]["workspace_mount"]["status"] == "FAIL"
    configured["REQUIRE_WORKSPACE_MOUNT"] = "false"
    assert report(configured)["checks"]["mount_enforcement"]["status"] == "FAIL"


def test_unconfirmed_release_or_service_cannot_pass(configured):
    result = activation_check.configuration_report(configured)
    assert result["result"] == "INCONCLUSIVE"
    assert result["checks"]["release_identity"]["status"] == "NOT_RUN"
    assert result["checks"]["service_identity"]["status"] == "NOT_RUN"


def test_inventory_does_not_follow_linked_projects(configured, tmp_path):
    outside = tmp_path.parent / (tmp_path.name + "-outside")
    outside.mkdir()
    try:
        (outside / "private").mkdir()
        (tmp_path / "linked").symlink_to(outside, target_is_directory=True)
        result = report(configured)
        inventory = result["checks"]["workspace_inventory"]
        assert inventory["directories_at_root"] == 0
        assert inventory["symlinks_skipped"] == 1
    finally:
        (tmp_path / "linked").unlink()
        (outside / "private").rmdir()
        outside.rmdir()


def test_unreadable_storage_reports_no_sensitive_error_detail(configured):
    with patch.object(Path, "iterdir", side_effect=PermissionError("sensitive/path-fixture")):
        result = report(configured)
    assert result["result"] == "INCONCLUSIVE"
    assert "sensitive/path-fixture" not in json.dumps(result)


def test_cli_runs_without_database_config_or_backend_imports(tmp_path):
    script = Path(activation_check.__file__).resolve()
    environment = {"PATH": os.defpath, "WORKSPACES_DIR": str(tmp_path),
                   "VERCEL_TOKEN": "cli-token-must-remain-private"}
    result = subprocess.run([sys.executable, "-B", str(script)], env=environment,
                            capture_output=True, text=True, check=False)
    assert result.returncode == 1
    parsed = json.loads(result.stdout)
    assert parsed["scope"] == "read_only_configuration"
    assert parsed["result"] == "FAIL"
    assert "cli-token-must-remain-private" not in result.stdout + result.stderr
    assert not list(tmp_path.iterdir())


def test_cli_rejects_invalid_target_without_echoing_input(capsys):
    assert activation_check.main(["--expected-commit", "private-invalid-fixture"]) == 1
    output = capsys.readouterr().out
    assert "private-invalid-fixture" not in output
    assert json.loads(output)["error"] == "invalid_expected_target"


def test_reviewed_stdin_copy_uses_shell_working_directory(tmp_path):
    root = tmp_path / 'workspaces'
    root.mkdir()
    source = Path(activation_check.__file__).read_text()
    result = subprocess.run([sys.executable, '-B', '-'], input=source,
                            cwd=tmp_path, env={'PATH': os.defpath},
                            capture_output=True, text=True, check=False)
    assert result.returncode == 1
    assert json.loads(result.stdout)['checks']['workspace_mount']['exists'] is True
    assert list(tmp_path.iterdir()) == [root]


@pytest.mark.parametrize("value", ["", "   ", "https://cache.example", "redis://", "redis://cache.example:broken", "redis://cache.example:0"])
def test_invalid_or_missing_shared_redis_blocks_activation(configured, value):
    configured["REDIS_URL"] = value
    result = report(configured)
    assert result["result"] == "FAIL"
    assert result["checks"]["shared_redis_configuration"]["status"] == "FAIL"


@pytest.mark.parametrize("value", ["redis://localhost:6379/0", "rediss://user:private-fixture@cache.example:6380/1", "redis://[::1]:6379/0"])
def test_redis_presence_is_not_connectivity_or_durability_evidence(configured, value):
    configured["REDIS_URL"] = value
    result = report(configured)
    check = result["checks"]["shared_redis_configuration"]
    assert check["status"] == "PASS"
    assert check["connectivity_verified"] is False
    assert "redis_persistence_and_eviction_policy" in result["not_verified"]
    assert value not in json.dumps(result)
