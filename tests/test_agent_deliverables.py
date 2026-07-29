"""
AgentOS deliverables tests — app/agents/deliverables.py's registry
(path-boundary-checked against WORKSPACES) and the authenticated,
org-scoped GET /api/agentos/deliverables/{id} download route in
app/routers/agent_os_api.py (Manus M3: auto-generated downloadable
deliverables).
"""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("SESSION_SECRET", "test-secret-for-unit-tests-do-not-use-in-prod")


def run(coro):
    import asyncio
    return asyncio.new_event_loop().run_until_complete(coro)


# ── register() / get() ───────────────────────────────────────────────────────

class TestDeliverablesRegistry:
    def test_register_inside_workspaces_returns_a_usable_id(self, tmp_path):
        import app.agents.deliverables as deliverables
        with patch.object(deliverables, "WORKSPACES", tmp_path):
            f = tmp_path / "out.zip"
            f.write_bytes(b"fake zip")
            deliverable_id = deliverables.register(
                f, run_id="r1", agent="deploy", label="out.zip",
                organization_id="org-a",
            )
            assert deliverable_id is not None
            entry = deliverables.get(deliverable_id)
            assert entry is not None
            assert entry["path"] == str(f.resolve())
            assert entry["run_id"] == "r1"
            assert entry["agent"] == "deploy"
            assert entry["label"] == "out.zip"
            assert entry["organization_id"] == "org-a"

    def test_register_outside_workspaces_refuses_and_returns_none(self, tmp_path):
        import app.agents.deliverables as deliverables
        workspaces_root = tmp_path / "workspaces"
        workspaces_root.mkdir()
        outside_file = tmp_path / "elsewhere" / "leak.txt"
        outside_file.parent.mkdir()
        outside_file.write_text("nope")

        with patch.object(deliverables, "WORKSPACES", workspaces_root):
            deliverable_id = deliverables.register(
                outside_file, run_id="r1", agent="deploy", label="leak.txt",
            )
        assert deliverable_id is None

    def test_register_without_organization_id_stores_none(self, tmp_path):
        import app.agents.deliverables as deliverables
        with patch.object(deliverables, "WORKSPACES", tmp_path):
            f = tmp_path / "out.zip"
            f.write_bytes(b"x")
            deliverable_id = deliverables.register(f, run_id="r1", agent="deploy", label="out.zip")
            assert deliverables.get(deliverable_id)["organization_id"] is None

    def test_get_unknown_id_returns_none(self):
        import app.agents.deliverables as deliverables
        assert deliverables.get("does-not-exist") is None


# ── GET /api/agentos/deliverables/{id} ──────────────────────────────────────

class TestDownloadDeliverableEndpoint:
    def test_unknown_deliverable_is_404(self):
        from app.routers.agent_os_api import agentos_download_deliverable
        with pytest.raises(Exception) as exc_info:
            run(agentos_download_deliverable("missing-id", MagicMock(), {"id": "u1"}))
        assert getattr(exc_info.value, "status_code", None) == 404

    def test_org_mismatch_is_404_same_as_missing(self, tmp_path):
        from app.routers.agent_os_api import agentos_download_deliverable
        import app.agents.deliverables as deliverables

        with patch.object(deliverables, "WORKSPACES", tmp_path):
            f = tmp_path / "out.zip"
            f.write_bytes(b"x")
            deliverable_id = deliverables.register(
                f, run_id="r1", agent="deploy", label="out.zip",
                organization_id="org-owner",
            )

        with patch("app.tenancy.context.optional_org_id", AsyncMock(return_value="org-other")):
            with pytest.raises(Exception) as exc_info:
                run(agentos_download_deliverable(deliverable_id, MagicMock(), {"id": "u1"}))
        assert getattr(exc_info.value, "status_code", None) == 404

    def test_matching_org_succeeds(self, tmp_path):
        from app.routers.agent_os_api import agentos_download_deliverable
        import app.agents.deliverables as deliverables

        with patch.object(deliverables, "WORKSPACES", tmp_path):
            f = tmp_path / "out.zip"
            f.write_bytes(b"x")
            deliverable_id = deliverables.register(
                f, run_id="r1", agent="deploy", label="out.zip",
                organization_id="org-owner",
            )

        with patch("app.tenancy.context.optional_org_id", AsyncMock(return_value="org-owner")):
            response = run(agentos_download_deliverable(deliverable_id, MagicMock(), {"id": "u1"}))
        assert response.status_code == 200
        assert response.filename == "out.zip"

    def test_no_organization_id_skips_the_org_check(self, tmp_path):
        # A deliverable registered without an org (e.g. a no-tenancy local
        # deployment) is downloadable by any authenticated caller.
        from app.routers.agent_os_api import agentos_download_deliverable
        import app.agents.deliverables as deliverables

        with patch.object(deliverables, "WORKSPACES", tmp_path):
            f = tmp_path / "out.zip"
            f.write_bytes(b"x")
            deliverable_id = deliverables.register(f, run_id="r1", agent="deploy", label="out.zip")

        response = run(agentos_download_deliverable(deliverable_id, MagicMock(), {"id": "u1"}))
        assert response.status_code == 200

    def test_file_deleted_after_registration_is_404(self, tmp_path):
        from app.routers.agent_os_api import agentos_download_deliverable
        import app.agents.deliverables as deliverables

        with patch.object(deliverables, "WORKSPACES", tmp_path):
            f = tmp_path / "out.zip"
            f.write_bytes(b"x")
            deliverable_id = deliverables.register(f, run_id="r1", agent="deploy", label="out.zip")
            f.unlink()

            with pytest.raises(Exception) as exc_info:
                run(agentos_download_deliverable(deliverable_id, MagicMock(), {"id": "u1"}))
        assert getattr(exc_info.value, "status_code", None) == 404


# ── DeployAgent zip-deploy wiring ────────────────────────────────────────────

class TestDeployAgentRegistersDeliverable:
    def test_zip_deploy_registers_a_deliverable_and_narrates_it(self, tmp_path):
        from app.agents.builtin.deploy_agent import DeployAgent
        from app.agents.base import AgentContext
        import app.agents.deliverables as deliverables

        ws = tmp_path / "project"
        ws.mkdir()
        (ws / "file.txt").write_text("hello")

        workspaces_root = tmp_path / "workspaces"
        workspaces_root.mkdir()

        ctx = AgentContext(input="deploy", args=str(ws), kernel=None, memory=None,
                           run_id="r1", organization_id="org-a")
        ctx._agent_name_hint = "deploy"

        fake_publish = AsyncMock()
        with patch("app.agents.builtin.deploy_agent.WORKSPACES", workspaces_root), \
             patch.object(deliverables, "WORKSPACES", workspaces_root), \
             patch("app.agents.liveness.publish_step", fake_publish):
            result = run(DeployAgent()._zip_deploy(ws, [], ctx))

        assert result.success is True
        assert "deliverable_id" in result.data
        entry = deliverables.get(result.data["deliverable_id"])
        assert entry is not None
        assert entry["organization_id"] == "org-a"
        narrated = [c.args[2] for c in fake_publish.call_args_list]
        assert any("Deliverable ready for download" in n for n in narrated)
