"""Safety properties of the future free-tools compute policy."""
import pytest

from app.ai.compute_policy import (
    ComputeCapabilities, ComputeMode, ComputeUnavailable, choose_compute,
)


@pytest.mark.parametrize("mode", list(ComputeMode))
def test_no_platform_fallback(mode):
    with pytest.raises(ComputeUnavailable):
        choose_compute(mode, ComputeCapabilities())


def test_explicit_user_key():
    caps = ComputeCapabilities(user_key_configured=True, user_key_authorized=True)
    assert choose_compute(ComputeMode.USER_KEY, caps) == ComputeMode.USER_KEY
    with pytest.raises(ComputeUnavailable):
        choose_compute(ComputeMode.LOCAL_AGENT, caps)


def test_explicit_local():
    caps = ComputeCapabilities(local_agent_connected=True, local_agent_authorized=True)
    assert choose_compute(ComputeMode.LOCAL_AGENT, caps) == ComputeMode.LOCAL_AGENT
    with pytest.raises(ComputeUnavailable):
        choose_compute(ComputeMode.USER_KEY, caps)


def test_auto_prefers_local():
    caps = ComputeCapabilities(True, True, True, True)
    assert choose_compute(ComputeMode.AUTO, caps) == ComputeMode.LOCAL_AGENT


def test_auto_uses_authorized_key_only():
    caps = ComputeCapabilities(user_key_configured=True, user_key_authorized=True)
    assert choose_compute(ComputeMode.AUTO, caps) == ComputeMode.USER_KEY


def test_unapproved_credentials_are_not_usable():
    caps = ComputeCapabilities(user_key_configured=True, local_agent_connected=True)
    with pytest.raises(ComputeUnavailable):
        choose_compute(ComputeMode.AUTO, caps)
