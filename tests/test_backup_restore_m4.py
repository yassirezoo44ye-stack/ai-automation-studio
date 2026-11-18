"""Backup and restore audit (M4, 2026-11-17).

The audit found that project files lived on the Render container's own disk
(wiped on every deploy) and that the database had no copy outside Render.
These tests pin the fixes: a persistent disk for WORKSPACES_DIR, a startup
warning when production runs without one, an entrypoint that makes the disk
writable for the unprivileged user, and a nightly encrypted, restore-tested
backup workflow. The scripts' round trip runs against a real database when
FLOW_BACKUP_TEST_DATABASE_URL points at one (it needs createdb rights).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent


# ── Project files survive deploys ────────────────────────────────────────────

def test_production_without_workspaces_dir_warns(monkeypatch, caplog):
    from app.core.filesystem import workspaces_persistence_warning

    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("WORKSPACES_DIR", raising=False)
    msg = workspaces_persistence_warning()
    assert msg and "WORKSPACES_DIR is not set" in msg
    assert "lost on the next deploy" in caplog.text


@pytest.mark.parametrize("env, ws_dir", [("production", "/var/data/workspaces"), ("development", None)])
def test_no_warning_with_persistent_disk_or_outside_production(monkeypatch, env, ws_dir):
    from app.core.filesystem import workspaces_persistence_warning

    monkeypatch.setenv("ENVIRONMENT", env)
    if ws_dir:
        monkeypatch.setenv("WORKSPACES_DIR", ws_dir)
    else:
        monkeypatch.delenv("WORKSPACES_DIR", raising=False)
    assert workspaces_persistence_warning() is None


def test_render_blueprint_puts_workspaces_on_the_persistent_disk():
    cfg = yaml.safe_load((ROOT / "render.yaml").read_text())
    web = next(s for s in cfg["services"] if s["type"] == "web")
    mount = web["disk"]["mountPath"]
    env = {e["key"]: e.get("value") for e in web["envVars"]}
    assert env["WORKSPACES_DIR"].startswith(mount.rstrip("/") + "/")


def test_container_drops_to_unprivileged_user_after_preparing_the_disk():
    dockerfile = (ROOT / "Dockerfile").read_text()
    entry = (ROOT / "docker-entrypoint.sh").read_text()
    assert 'ENTRYPOINT ["docker-entrypoint.sh"]' in dockerfile
    assert "setpriv --reuid=axon --regid=axon" in entry
    assert 'chown axon:axon "$ws"' in entry
    assert os.access(ROOT / "docker-entrypoint.sh", os.X_OK)


# ── Nightly off-site database backup ────────────────────────────────────────

def _workflow() -> dict:
    return yaml.safe_load((ROOT / ".github/workflows/db-backup.yml").read_text())


def test_backup_workflow_runs_daily_and_tests_the_restore_on_postgres_18():
    wf = _workflow()
    triggers = wf.get("on") or wf.get(True)  # PyYAML reads the key `on` as True
    assert triggers["schedule"][0]["cron"]
    assert "workflow_dispatch" in triggers
    job = wf["jobs"]["backup"]
    assert job["services"]["scratch"]["image"] == "pgvector/pgvector:pg18"
    steps = "\n".join(str(s.get("run", "")) for s in job["steps"])
    assert "pgvector/pgvector:pg18" in steps and "db_backup.sh" in steps
    assert 'age -r "$BACKUP_AGE_RECIPIENT"' in steps


def test_backup_workflow_never_puts_secrets_on_a_command_line_or_in_artifacts_unencrypted():
    wf = _workflow()
    job = wf["jobs"]["backup"]
    for step in job["steps"]:
        assert "secrets." not in str(step.get("run", "")), step.get("name")
    upload = next(s for s in job["steps"] if str(s.get("uses", "")).startswith("actions/upload-artifact"))
    assert upload["with"]["path"].endswith("ARCHIVE }}")
    assert upload["with"]["retention-days"] == 30
    encrypt = next(s for s in job["steps"] if s.get("name") == "Encrypt")
    assert "rm -rf out" in encrypt["run"]  # plaintext dump removed before upload
    assert wf["permissions"] == {"contents": "read"}


def test_backup_workflow_skips_instead_of_failing_when_not_configured():
    job = _workflow()["jobs"]["backup"]
    check = job["steps"][0]
    assert check["id"] == "config" and "::warning::" in check["run"]
    for step in job["steps"][1:]:
        assert step.get("if") == "steps.config.outputs.ready == 'true'", step.get("name") or step.get("uses")


# ── Script round trip against a real database ───────────────────────────────

BASE_URL = os.getenv("FLOW_BACKUP_TEST_DATABASE_URL")
pg_tools = all(shutil.which(t) for t in ("pg_dump", "pg_restore", "psql"))


@pytest.mark.skipif(not (BASE_URL and pg_tools), reason="set FLOW_BACKUP_TEST_DATABASE_URL and install pg client tools")
def test_backup_restore_round_trip_detects_tampering(tmp_path):
    def url_for(db: str) -> str:
        return BASE_URL.rsplit("/", 1)[0] + "/" + db

    def run(*args):
        return subprocess.run(args, check=True, capture_output=True, text=True)

    names = {k: f"m4_{k}_{uuid.uuid4().hex[:8]}" for k in ("src", "scratch", "target")}
    for db in names.values():
        run("psql", BASE_URL, "-c", f'create database "{db}"')
    try:
        run("psql", url_for(names["src"]), "-c",
            "create table users(id serial primary key, email text); create table organizations(id int);"
            "create table projects(id int, data bytea); insert into users(email) values ('a@x'),('b@x');"
            "insert into projects values (1, '\\xdeadbeef')")
        scripts = ROOT / "scripts/backup"
        out = run("bash", scripts / "db_backup.sh", url_for(names["src"]), tmp_path, url_for(names["scratch"])).stdout
        assert "restore test ok: 3 tables, 3 rows" in out
        dump = next(tmp_path.glob("flow-*.dump"))
        fp = next(tmp_path.glob("flow-*.fingerprint.txt"))

        ok = run("bash", scripts / "db_restore.sh", dump, url_for(names["target"]), fp).stdout
        assert "verified: 3 tables match the backup exactly" in ok

        again = subprocess.run(["bash", scripts / "db_restore.sh", dump, url_for(names["target"])], capture_output=True, text=True)
        assert again.returncode == 1 and "refusing" in again.stderr

        bad = tmp_path / "bad.txt"
        bad.write_text(fp.read_text().replace("users|2|", "users|3|"))
        run("psql", url_for(names["scratch"]), "-c", "drop schema public cascade; create schema public")
        tampered = subprocess.run(["bash", scripts / "db_restore.sh", dump, url_for(names["scratch"]), bad], capture_output=True, text=True)
        assert tampered.returncode == 1 and "MISMATCH" in tampered.stderr
    finally:
        for db in names.values():
            subprocess.run(["psql", BASE_URL, "-c", f'drop database if exists "{db}" with (force)'], capture_output=True)
