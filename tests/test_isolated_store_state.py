"""Store preview commits state before acknowledging writes, without host execution."""
import asyncio
from contextlib import asynccontextmanager
import sqlite3
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.execution import isolated


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(isolated, 'WORKSPACES', tmp_path.parent)
    monkeypatch.setattr(isolated, '_sessions', {})
    monkeypatch.setattr(isolated, '_locks', isolated.defaultdict(asyncio.Lock))
    database = tmp_path / 'snapshot.sqlite3'
    with sqlite3.connect(database) as connection:
        connection.execute('CREATE TABLE orders(id INTEGER PRIMARY KEY, total INTEGER)')
        connection.execute('INSERT INTO orders VALUES(1, 12500)')
    blob = database.read_bytes()
    @asynccontextmanager
    async def open_file(path, mode):
        assert path in ('/tmp/flow-store-backup.sqlite3', f'{isolated.ROOT}/data/owner-setup.txt')
        reader = SimpleNamespace(read=AsyncMock(side_effect=lambda size: blob[:size]))
        yield reader
    current = SimpleNamespace(fs=SimpleNamespace(open=open_file),
                              run_command=AsyncMock(return_value=SimpleNamespace(returncode=0)))
    vm = SimpleNamespace(current_session=current, destroy=AsyncMock())
    session = isolated.Session(SimpleNamespace(aclose=AsyncMock()), vm,
        'https://preview-example.vercel.run/_flow_preview/test-capability',
        'fastapi', ['python3'], time.monotonic() + 300,
        store_workspace=tmp_path, store_dirty=True)
    return session, blob


async def test_committed_store_database_is_saved_and_restored_on_next_upload(store):
    session, blob = store
    with patch('asyncio.create_subprocess_exec', new_callable=AsyncMock) as host:
        await isolated.persist_store(session)
    host.assert_not_called()
    destination = session.store_workspace / 'data/store.sqlite3'
    assert destination.read_bytes() == blob
    with sqlite3.connect(destination) as connection:
        assert connection.execute('SELECT total FROM orders WHERE id=1').fetchone() == (12500,)
    assert dict(isolated.workspace_files(session.store_workspace))['data/store.sqlite3'] == blob
    assert session.store_dirty is False
    assert destination.stat().st_mode & 0o077 == 0


async def test_failed_disk_commit_preserves_previous_database_and_dirty_flag(store):
    session, _ = store
    destination = session.store_workspace / 'data/store.sqlite3'
    destination.parent.mkdir()
    destination.write_bytes(b'previous-durable-state')
    with patch.object(isolated.os, 'replace', side_effect=OSError('disk full')):
        with pytest.raises(isolated.PreviewError, match='could not be saved'):
            await isolated.persist_store(session)
    assert destination.read_bytes() == b'previous-durable-state'
    assert session.store_dirty is True
    assert list(destination.parent.iterdir()) == [destination]


async def test_stop_does_not_destroy_unsaved_store_state(store):
    session, _ = store
    isolated._sessions['project'] = session
    with patch.object(isolated, 'persist_store', AsyncMock(side_effect=isolated.PreviewError('save failed'))):
        with pytest.raises(isolated.PreviewError):
            await isolated.stop('project')
    session.sandbox.destroy.assert_not_awaited()
    assert isolated._sessions['project'] is session


async def test_expired_store_never_auto_resumes_for_state_read(store):
    session, _ = store
    session.expires_at = 0
    session.sandbox.fs = MagicMock()
    with pytest.raises(isolated.PreviewError, match='expired'):
        await isolated._read_current(session, '/tmp/flow-store-backup.sqlite3', 200)
    session.sandbox.fs.assert_not_called()
    session.sandbox.current_session.run_command.assert_not_awaited()
