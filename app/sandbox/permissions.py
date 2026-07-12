"""
Sandbox permission model — derives runtime enforcement limits from a
plugin's already-approved app.marketplace.security capability set. No
second capability list is defined here; ALL_KNOWN_CAPABILITIES stays the
single source of truth for what a plugin can *declare*, this module only
maps a granted subset of it onto concrete sandbox limits.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.marketplace.security import ALL_KNOWN_CAPABILITIES

NetworkPolicy = Literal["none", "internal", "allowlist", "full"]

# Conservative defaults — a plugin gets the least access that still lets
# it run. Only capabilities present in a plugin's *granted* plugin_permissions
# rows widen these.
_DEFAULT_CPU_SECONDS   = 10.0
_DEFAULT_MEMORY_MB     = 256
_DEFAULT_PIDS          = 32
_DEFAULT_TIMEOUT_S     = 15.0

# Capabilities that, when granted, widen the default network policy from
# "none". "network"/"third_party_api" imply outbound access is needed at
# all; "database" alone does not (DB access goes through this platform's
# own Postgres connection, not an arbitrary outbound socket from the worker).
_NETWORK_CAPABILITIES = frozenset({"network", "third_party_api"})


@dataclass
class SandboxLimits:
    """Concrete, enforceable limits for one worker — derived from a
    plugin's approved capabilities, not declared directly by plugin authors."""
    cpu_seconds: float = _DEFAULT_CPU_SECONDS
    memory_mb: int = _DEFAULT_MEMORY_MB
    pids: int = _DEFAULT_PIDS
    timeout_s: float = _DEFAULT_TIMEOUT_S
    network_policy: NetworkPolicy = "none"
    allowed_domains: list[str] = field(default_factory=list)
    filesystem_write: bool = False
    env_vars_allowed: bool = False

    def to_dict(self) -> dict:
        return {
            "cpu_seconds": self.cpu_seconds,
            "memory_mb": self.memory_mb,
            "pids": self.pids,
            "timeout_s": self.timeout_s,
            "network_policy": self.network_policy,
            "allowed_domains": list(self.allowed_domains),
            "filesystem_write": self.filesystem_write,
            "env_vars_allowed": self.env_vars_allowed,
        }


def limits_from_granted_capabilities(granted: set[str]) -> SandboxLimits:
    """Build a SandboxLimits from the set of capability names a plugin
    installation has been granted (plugin_permissions.capability where
    granted=true). Unknown capability names are ignored defensively —
    manifest validation (check_permission_manifest) already rejects them
    at declaration time, this is a second, cheap safety net."""
    granted = {c for c in granted if c in ALL_KNOWN_CAPABILITIES}
    limits = SandboxLimits()
    if granted & _NETWORK_CAPABILITIES:
        limits.network_policy = "allowlist"
    if "filesystem" in granted:
        limits.timeout_s = max(limits.timeout_s, _DEFAULT_TIMEOUT_S)
    if "filesystem_write" in granted:
        limits.filesystem_write = True
    if "environment_variables" in granted:
        limits.env_vars_allowed = True
    if "shell_exec" in granted or "terminal" in granted:
        # A plugin that needs a real shell gets more headroom — still
        # capped, never unlimited.
        limits.cpu_seconds = max(limits.cpu_seconds, 30.0)
        limits.timeout_s = max(limits.timeout_s, 30.0)
    return limits
