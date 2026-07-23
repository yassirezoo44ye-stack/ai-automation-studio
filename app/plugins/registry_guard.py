"""
Shared collision guard for every plugin-fed name registry (tools,
workflow nodes, agents, memory/storage/auth providers) — all five are
populated from the same untrusted source (a plugin manifest's
self-declared names, via app.plugins.adapters.adapt_registrations())
and were, before this module existed, keyed only by that self-declared
name with no per-tenant namespace: a plain `dict[name] = value` that a
second registration silently overwrote.

Concretely: Org A installs a plugin whose manifest declares a tool named
"send_email". Org B installs a different (or malicious/typosquatting)
plugin that also declares a tool named "send_email". Whichever loads
last wins the shared slot platform-wide — Org A's agent, which still
correctly lists "send_email" in its own tool allowlist, has its calls
(and whatever arguments it constructs) silently redirected into Org B's
sandboxed worker. Neither org sees an error. This is a cross-tenant
code-execution/data hijack, not a compatibility nuisance.

OwnershipTracker closes it by remembering which owner (a plugin's
installation_id, or None for a built-in/core registration) currently
holds each name, and refusing a claim by a different owner. Re-claiming
your own name (a plugin hot-reload, a built-in module re-import) stays
allowed and silent, matching prior behavior for that case.
"""
from __future__ import annotations

import threading
from typing import Optional

_UNCLAIMED = object()


class RegistrationConflictError(ValueError):
    """A plugin tried to register a name a DIFFERENT owner already holds."""


class OwnershipTracker:
    def __init__(self, kind: str) -> None:
        self._kind = kind
        self._owners: dict[str, Optional[str]] = {}
        # Matches the threading.Lock() convention already used by
        # AgentMemory/LayeredMemory for shared mutable registry state.
        # Without it, claim()'s check-then-act (read _owners, then write
        # it) is two separate dict ops — two threads can both observe a
        # name as unclaimed and both "win" it, recreating the exact
        # silent-overwrite hijack this module exists to prevent.
        self._lock = threading.Lock()

    def claim(self, name: str, owner: Optional[str]) -> None:
        with self._lock:
            existing = self._owners.get(name, _UNCLAIMED)
            if existing is not _UNCLAIMED and existing != owner:
                owner_desc = "a built-in" if existing is None else f"installation {existing!r}"
                raise RegistrationConflictError(
                    f"{self._kind} name {name!r} is already registered by {owner_desc} "
                    "— refusing to let a different installation claim it"
                )
            self._owners[name] = owner

    def release(self, name: str) -> None:
        with self._lock:
            self._owners.pop(name, None)

    def owner_of(self, name: str) -> Optional[str]:
        """Current owner of `name`, or None if it's a built-in (or was
        never claimed — callers that only query names known to exist in
        the corresponding registry, e.g. AgentKernel._agents, don't need
        to distinguish the two: an entry there was always claimed first)."""
        with self._lock:
            return self._owners.get(name)
