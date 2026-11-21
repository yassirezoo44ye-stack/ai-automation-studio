"""Fail-closed selection policy for future user-funded AI execution.

This module is deliberately not connected to the production gateway yet.
No credentials are accepted or stored here.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ComputeMode(str, Enum):
    USER_KEY = "user_key"
    LOCAL_AGENT = "local_agent"
    AUTO = "auto"


class ComputeUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class ComputeCapabilities:
    user_key_configured: bool = False
    local_agent_connected: bool = False
    user_key_authorized: bool = False
    local_agent_authorized: bool = False


def choose_compute(mode: ComputeMode, capabilities: ComputeCapabilities) -> ComputeMode:
    """Select an explicitly authorized user-funded backend, never platform AI.

    AUTO prefers local compute and may use a user key only if separately
    authorized. It fails closed when neither is authorized and available.
    """
    local = capabilities.local_agent_connected and capabilities.local_agent_authorized
    key = capabilities.user_key_configured and capabilities.user_key_authorized
    if mode == ComputeMode.LOCAL_AGENT and local:
        return ComputeMode.LOCAL_AGENT
    if mode == ComputeMode.USER_KEY and key:
        return ComputeMode.USER_KEY
    if mode == ComputeMode.AUTO:
        if local:
            return ComputeMode.LOCAL_AGENT
        if key:
            return ComputeMode.USER_KEY
    raise ComputeUnavailable("No authorized user-funded compute backend is available")
