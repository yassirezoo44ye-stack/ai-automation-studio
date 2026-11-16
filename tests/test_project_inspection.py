import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import uuid

import pytest
from app.agents.builtin import inspect_project as module


def test_inspection_does_not_execute_code_read_secrets_or_follow_links(tmp_path, monkeypatch):
    monkeypatch.setattr(module, 'WORKSPACES', tmp_path)
    pid = str(uuid.uuid4())
    project = tmp_path / pid
    project.mkdir()
    (project / 'main.py').write_text("raise RuntimeError('must never execute')")
    (project / '.env').write_text('API_KEY=private-test-value')
    (project / 'package.json').write_text(json.dumps({'scripts': {'test': 'DO NOT EXECUTE', 'start': 'DO NOT EXECUTE'}}))
    outside = tmp_path / 'outside.py'
    outside.write_text('SECRET_OUTSIDE')
    (project / 'linked.py').symlink_to(outside)
    report = module.inspect_workspace(pid)
    assert report['source_files'] == 1
    assert report['languages'] == {'python': 1}
    assert report['code_executed'] is False
    assert report['package_scripts'] == ['test', 'start']
    assert 'private-test-value' not in json.dumps(report)
    assert 'DO NOT EXECUTE' not in json.dumps(report)
    assert 'SECRET_OUTSIDE' not in json.dumps(report)
    linked = str(uuid.uuid4())
    (tmp_path / linked).symlink_to(project, target_is_directory=True)
    with pytest.raises(OSError):
        module.inspect_workspace(linked)


@pytest.mark.asyncio
async def test_agent_requires_verified_project_ownership(monkeypatch, tmp_path):
    conn = MagicMock()
    conn.fetchval = AsyncMock(return_value=None)
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    monkeypatch.setattr(module, 'get_pool', lambda: pool)
    monkeypatch.setattr(module, 'WORKSPACES', tmp_path)
    context = SimpleNamespace(project_id=str(uuid.uuid4()), user_id=str(uuid.uuid4()), step=AsyncMock())
    result = await module.InspectProjectAgent().execute(context)
    assert result.success is False and result.error == 'Project not found'
    context.user_id = None
    result = await module.InspectProjectAgent().execute(context)
    assert result.success is False
    assert module.InspectProjectAgent().permissions.can_execute_subprocess is False
    assert module.InspectProjectAgent().permissions.can_access_network is False
