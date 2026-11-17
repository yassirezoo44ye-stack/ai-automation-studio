"""Security and lifecycle regressions. No provider, host execution or live DB."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.execution import isolated, runner


@pytest.fixture(autouse=True)
def clean_state(monkeypatch):
    monkeypatch.setattr(isolated, "_sessions", {})
    monkeypatch.setattr(isolated, "_locks", isolated.defaultdict(asyncio.Lock))
    monkeypatch.setattr(isolated, "_capacity", asyncio.Semaphore(isolated.MAX_SESSIONS))
    for key in ("VERCEL_TOKEN", "VERCEL_TEAM_ID", "VERCEL_PROJECT_ID"):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / "index.html").write_text("<h1>Isolated</h1>")
    return tmp_path


@pytest.fixture
def provider():
    vm = MagicMock()
    vm.fs.mkdir = AsyncMock()
    vm.fs.write_bytes = AsyncMock()
    vm.run_command = AsyncMock(return_value=SimpleNamespace(returncode=0, stdout=b"ok", stderr=b""))
    vm.create_command = AsyncMock()
    vm.update_network_policy = AsyncMock()
    vm.destroy = AsyncMock()
    vm.routes = [SimpleNamespace(port=3000, system=False, url="https://preview-example.vercel.run")]
    client = MagicMock()
    client.create_sandbox = AsyncMock(return_value=vm)
    client.aclose = AsyncMock()
    return client, vm


async def events(workspace, project="owned-project", command=None):
    return [json.loads(event[6:]) async for event in runner.run_stream(project, workspace, command)]


async def test_missing_configuration_never_runs_generated_code_on_host(workspace):
    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as host:
        result = await events(workspace)
    assert result[-1]["type"] == "error"
    assert "not configured" in result[-1]["message"]
    host.assert_not_called()


async def test_remote_failure_never_falls_back_to_host(workspace, provider):
    client, vm = provider
    client.create_sandbox.side_effect = RuntimeError("provider error with sensitive details")
    with patch.object(isolated, "_client", return_value=client), \
         patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as host:
        result = await events(workspace)
    assert result[-1]["category"] == "isolation"
    assert "sensitive" not in result[-1]["message"]
    host.assert_not_called()
    client.aclose.assert_awaited_once()
    assert isolated._capacity._value == isolated.MAX_SESSIONS


async def test_preview_has_no_host_secrets_and_is_cross_origin(workspace, provider, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "do-not-upload")
    (workspace / ".env").write_text("SECRET=do-not-upload")
    (workspace / ".env.production").write_text("SECRET=do-not-upload")
    (workspace / ".env.example").write_text("SECRET=")
    client, vm = provider
    with patch.object(isolated, "_client", return_value=client):
        result = await events(workspace)
    options = client.create_sandbox.call_args.kwargs
    assert options["env"] == {}
    assert options["persistent"] is False
    assert options["execution_time_limit"] == 300
    assert options["network_policy"].mode == "deny-all"
    assert options["ports"] == [3000]
    writes = {call.args[0]: call.args[1] for call in vm.fs.write_bytes.call_args_list}
    assert f"{isolated.ROOT}/index.html" in writes
    assert f"{isolated.ROOT}/.env.example" in writes
    assert all(not path.endswith(("/.env", "/.env.production")) for path in writes)
    assert "do-not-upload" not in repr(vm.mock_calls)
    assert result[-1]["type"] == "server_ready"
    assert result[-1]["preview_url"].startswith("https://preview-example.vercel.run/_flow_preview/")
    assert (await isolated.status("owned-project"))["running"]
    vm.destroy.assert_not_awaited()
    await isolated.stop("owned-project")
    vm.destroy.assert_awaited_once()
    assert await isolated.status("owned-project") == {"running": False}
    assert isolated._capacity._value == isolated.MAX_SESSIONS


async def test_unapproved_preview_domain_is_rejected_and_vm_destroyed(workspace, provider):
    client, vm = provider
    vm.routes[0].url = "https://attacker.example"
    with patch.object(isolated, "_client", return_value=client):
        result = await events(workspace)
    assert result[-1]["type"] == "error"
    vm.destroy.assert_awaited_once()
    client.aclose.assert_awaited_once()
    assert isolated._sessions == {}


async def test_failed_setup_cleans_up_vm(workspace, provider):
    client, vm = provider
    vm.fs.write_bytes.side_effect = RuntimeError("failed transfer")
    with patch.object(isolated, "_client", return_value=client):
        result = await events(workspace)
    assert result[-1]["type"] == "error"
    vm.destroy.assert_awaited_once()
    assert isolated._capacity._value == isolated.MAX_SESSIONS


async def test_cancel_during_upload_cleans_up_vm(workspace, provider):
    client, vm = provider
    vm.fs.write_bytes.side_effect = asyncio.CancelledError()
    with patch.object(isolated, "_client", return_value=client):
        with pytest.raises(asyncio.CancelledError):
            await events(workspace)
    vm.destroy.assert_awaited_once()
    client.aclose.assert_awaited_once()


async def test_stop_failure_retains_handle_for_retry(workspace, provider):
    client, vm = provider
    with patch.object(isolated, "_client", return_value=client):
        await events(workspace)
    vm.destroy.side_effect = RuntimeError("temporary provider failure")
    with pytest.raises(RuntimeError):
        await isolated.stop("owned-project")
    assert "owned-project" in isolated._sessions
    vm.destroy.side_effect = None
    await isolated.stop("owned-project")
    assert isolated._sessions == {}


async def test_expired_preview_is_destroyed_without_resume(workspace, provider):
    client, vm = provider
    with patch.object(isolated, "_client", return_value=client):
        await events(workspace)
    isolated._sessions["owned-project"].expires_at = 0
    assert await isolated.status("owned-project") == {"running": False}
    vm.destroy.assert_awaited_once()


async def test_duplicate_start_does_not_create_second_vm(workspace, provider):
    client, vm = provider
    with patch.object(isolated, "_client", return_value=client):
        await events(workspace)
        result = await events(workspace)
    assert result[-1]["type"] == "error"
    client.create_sandbox.assert_awaited_once()
    await isolated.stop("owned-project")


async def test_arbitrary_command_is_rejected_before_provider_call(workspace):
    with patch.object(isolated, "_client") as client:
        result = await events(workspace, command="python -c malicious_code")
    assert result[-1]["type"] == "error"
    client.assert_not_called()


def test_workspace_rejects_symlink_and_bounds_transfer(workspace, tmp_path, monkeypatch):
    secret = tmp_path.parent / "not-a-workspace-secret"
    secret.write_text("outside")
    try:
        (workspace / "link").symlink_to(secret)
        with pytest.raises(ValueError, match="links"):
            isolated.workspace_files(workspace)
    finally:
        secret.unlink()
    (workspace / "link").unlink()
    monkeypatch.setattr(isolated, "MAX_BYTES", 1)
    with pytest.raises(ValueError, match="limit"):
        isolated.workspace_files(workspace)


@pytest.mark.parametrize("url", ["https://x.vercel.run", "https://x.vercel.run/path?x=1"])
def test_allowed_preview_urls(url):
    assert isolated.valid_preview_url(url)


@pytest.mark.parametrize("url", ["/api/projects/p/proxy/", "http://x.vercel.run", "https://vercel.run",
    "https://x.vercel.run.attacker.example", "https://user:secret@x.vercel.run", "https://x.vercel.run:9999"])
def test_untrusted_preview_urls(url):
    assert not isolated.valid_preview_url(url)


async def test_node_dependency_access_is_revoked_before_app_starts(tmp_path, provider):
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"start": "node server.js"}}))
    (tmp_path / "server.js").write_text("require('http').createServer(()=>{}).listen(8080)")
    client, vm = provider
    order = []
    async def policy(value):
        order.append(value.mode)
    async def command(*args, **kwargs):
        order.append(args[0])
    vm.update_network_policy.side_effect = policy
    vm.create_command.side_effect = command
    with patch.object(isolated, "_client", return_value=client):
        result = await events(tmp_path)
    assert result[-1]["type"] == "server_ready"
    assert order[:3] == ["custom", "deny-all", "npm"]
    await isolated.stop("owned-project")


async def test_sdk_auth_stays_in_control_client(monkeypatch):
    from vercel.sandbox import SandboxClient
    for key in ("VERCEL_TOKEN", "VERCEL_TEAM_ID", "VERCEL_PROJECT_ID"):
        monkeypatch.setenv(key, key.lower())
    with patch.object(SandboxClient, "create") as create:
        isolated._client()
    factory = create.call_args.kwargs["options"].credentials_factory
    auth = await factory()
    assert auth.token == "vercel_token"
    assert auth.team_id == "vercel_team_id"
    assert auth.project_id == "vercel_project_id"


async def test_closing_stream_after_ready_releases_lock_and_preserves_preview(workspace, provider):
    client, vm = provider
    with patch.object(isolated, "_client", return_value=client):
        iterator = runner.run_stream("owned-project", workspace, None)
        async for raw in iterator:
            if json.loads(raw[6:])["type"] == "server_ready":
                break
        await iterator.aclose()
    await asyncio.wait_for(isolated.stop("owned-project"), timeout=1)
    vm.destroy.assert_awaited_once()


async def test_failed_cleanup_keeps_vm_handle_for_retry(workspace, provider):
    client, vm = provider
    vm.fs.write_bytes.side_effect = RuntimeError("transfer failed")
    vm.destroy.side_effect = RuntimeError("temporary deletion error")
    with patch.object(isolated, "_client", return_value=client):
        await events(workspace)
    assert "owned-project" in isolated._sessions
    client.aclose.assert_not_awaited()
    assert isolated._capacity._value == isolated.MAX_SESSIONS - 1
    vm.destroy.side_effect = None
    await isolated.stop("owned-project")
    assert isolated._capacity._value == isolated.MAX_SESSIONS


def test_remote_output_is_bounded():
    buffer = isolated._Output()
    assert buffer.write(b"x" * 1000000) == 1000000
    assert len(buffer.getvalue()) == 16000
