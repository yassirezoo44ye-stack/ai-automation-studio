"""Startup checks for persistence configuration; no real mount or Render changes."""
from pathlib import Path
from unittest.mock import patch

import pytest
from app.core import filesystem


def test_required_mount_fails_closed_without_creating_ephemeral_directory(tmp_path, monkeypatch):
    destination = tmp_path / "missing-mount"
    monkeypatch.setattr(filesystem, "WORKSPACES", destination)
    monkeypatch.setenv("REQUIRE_WORKSPACE_MOUNT", "true")
    with pytest.raises(RuntimeError, match="persistent mount"):
        filesystem.verify_workspace_storage()
    assert not destination.exists()


def test_writable_storage_probe_preserves_existing_projects(tmp_path, monkeypatch):
    project = tmp_path / "owned-project"
    project.mkdir()
    source = project / "index.html"
    source.write_text("existing-source")
    monkeypatch.setattr(filesystem, "WORKSPACES", tmp_path)
    monkeypatch.setenv("REQUIRE_WORKSPACE_MOUNT", "true")
    with patch.object(Path, "is_mount", return_value=True):
        filesystem.verify_workspace_storage()
    assert source.read_text() == "existing-source"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["owned-project"]


def test_local_development_can_use_unmounted_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(filesystem, "WORKSPACES", tmp_path / "local")
    monkeypatch.delenv("REQUIRE_WORKSPACE_MOUNT", raising=False)
    filesystem.verify_workspace_storage()
    assert (tmp_path / "local").is_dir()
    assert list((tmp_path / "local").iterdir()) == []


def test_unwritable_storage_probe_propagates_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(filesystem, "WORKSPACES", tmp_path)
    monkeypatch.delenv("REQUIRE_WORKSPACE_MOUNT", raising=False)
    with patch.object(filesystem.tempfile, "TemporaryFile", side_effect=PermissionError("not writable")):
        with pytest.raises(PermissionError):
            filesystem.verify_workspace_storage()
