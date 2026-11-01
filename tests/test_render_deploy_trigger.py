from io import BytesIO
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

import pytest

from scripts.trigger_render_deploy import DeployError, deploy_url, main, trigger

SERVICE = "srv-d6705koboq4c7384n0cg"
SHA = "a" * 40
HOOK = f"https://api.render.com/deploy/{SERVICE}?key=example-test-key"


def test_replaces_stale_refs_and_keeps_secret_key():
    target = deploy_url(HOOK + "&ref=old&ref=older", SERVICE, SHA)
    assert parse_qs(urlsplit(target).query) == {"key": ["example-test-key"], "ref": [SHA]}


@pytest.mark.parametrize("hook", [
    "http://api.render.com/deploy/" + SERVICE + "?key=example-test-key",
    "https://other.example/deploy/" + SERVICE + "?key=example-test-key",
    "https://api.render.com/deploy/" + SERVICE + "?key=x&key=y",
    "https://api.render.com/deploy/" + SERVICE,
    "https://api.render.com/deploy/" + SERVICE + "?key=x#fragment",
])
def test_rejects_unexpected_hook_shape_without_a_request(hook):
    with patch("scripts.trigger_render_deploy.build_opener") as opener:
        with pytest.raises(DeployError):
            trigger(hook, SERVICE, SHA)
        opener.assert_not_called()


def test_wrong_service_is_identified_without_using_or_printing_its_secret(monkeypatch, capsys):
    monkeypatch.setenv("RENDER_DEPLOY_HOOK_URL", "https://api.render.com/deploy/srv-oldtarget?key=example-test-key")
    monkeypatch.setenv("RENDER_SERVICE_ID", SERVICE)
    monkeypatch.setenv("GITHUB_SHA", SHA)
    with patch("scripts.trigger_render_deploy.build_opener") as opener:
        assert main() == 1
        opener.assert_not_called()
    output = capsys.readouterr().err
    assert "srv-oldtarget" in output and SERVICE in output
    assert "example-test-key" not in output and "https://" not in output


@pytest.mark.parametrize("status", [200, 201, 202])
def test_accepts_supported_success_statuses(status):
    response = MagicMock()
    response.__enter__.return_value.status = status
    with patch("scripts.trigger_render_deploy.build_opener") as opener:
        opener.return_value.open.return_value = response
        assert trigger(HOOK, SERVICE, SHA) == status
        request = opener.return_value.open.call_args.args[0]
        assert request.method == "POST"
        assert parse_qs(urlsplit(request.full_url).query)["ref"] == [SHA]


def test_conflict_is_rejected_and_response_body_is_not_logged(monkeypatch, capsys):
    monkeypatch.setenv("RENDER_DEPLOY_HOOK_URL", HOOK)
    monkeypatch.setenv("RENDER_SERVICE_ID", SERVICE)
    monkeypatch.setenv("GITHUB_SHA", SHA)
    with patch("scripts.trigger_render_deploy.build_opener") as opener:
        opener.return_value.open.side_effect = HTTPError(HOOK, 409, "secret URL", {}, BytesIO(b"example-test-key"))
        assert main() == 1
    output = capsys.readouterr().err
    assert "HTTP 409" in output and "example-test-key" not in output and "https://" not in output


def test_transport_errors_do_not_expose_the_url():
    with patch("scripts.trigger_render_deploy.build_opener") as opener:
        opener.return_value.open.side_effect = URLError(HOOK)
        with pytest.raises(DeployError) as error:
            trigger(HOOK, SERVICE, SHA)
    assert "example-test-key" not in str(error.value) and "https://" not in str(error.value)
