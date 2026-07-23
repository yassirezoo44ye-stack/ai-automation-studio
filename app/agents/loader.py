"""
Agent Loader — dynamic discovery and registration.

Scans:
  1. app/agents/builtin/  (shipped built-in agents)
  2. agents/              (user-defined agents at repo root)

A valid agent file must:
  - Define a class that inherits EvolvableAgent  OR
  - Export an `agent` module-level variable that is an EvolvableAgent instance  OR
  - Export a `register(kernel)` function (plugin-style)

Files starting with _ are skipped.
"""
from __future__ import annotations

import importlib
import importlib.util
import logging
import sys
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from app.agents.base import EvolvableAgent

if TYPE_CHECKING:
    from app.agents.kernel import AgentKernel

log = logging.getLogger(__name__)

_BUILTIN_DIR = Path(__file__).parent / "builtin"
_USER_DIR    = Path(__file__).parent.parent.parent / "agents"


def load_all(kernel: "AgentKernel") -> int:
    """
    Discover and register all agents.
    Returns count of successfully loaded agents.
    """
    count = 0
    count += _load_dir(_BUILTIN_DIR, kernel, package="app.agents.builtin")
    if _USER_DIR.exists():
        count += _load_dir(_USER_DIR, kernel, package="agents")
    return count


def load_file(path: Path, kernel: "AgentKernel", *, owner: Optional[str] = None) -> bool:
    """Dynamically load a single agent file at runtime. `owner` should be
    the requesting org's id when this is reachable from an API call (e.g.
    AutonomyEngine.generate_agent) — the loaded agent is then scoped to
    that org (see AgentKernel.visible_agents) instead of being registered
    as owner=None, which marks it as a protected built-in indistinguishable
    from shipped platform code and invocable by every other tenant."""
    return _load_file(path, kernel, package="agents.dynamic", owner=owner)


# ── Internal ──────────────────────────────────────────────────────────────────

def _load_dir(directory: Path, kernel: "AgentKernel", package: str) -> int:
    if not directory.exists():
        return 0
    count = 0
    for file in sorted(directory.glob("*.py")):
        if file.name.startswith("_"):
            continue
        if _load_file(file, kernel, package):
            count += 1
    return count


def _load_file(file: Path, kernel: "AgentKernel", package: str, *, owner: Optional[str] = None) -> bool:
    module_name = f"{package}.{file.stem}"
    try:
        if module_name in sys.modules:
            mod = importlib.reload(sys.modules[module_name])
        else:
            spec = importlib.util.spec_from_file_location(module_name, file)
            if spec is None or spec.loader is None:
                return False
            mod = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = mod
            spec.loader.exec_module(mod)

        # Strategy 1: register(kernel) function
        if hasattr(mod, "register") and callable(mod.register):
            mod.register(kernel)
            log.debug("loaded agent plugin: %s", file.name)
            return True

        # Strategy 2: `agent` variable = EvolvableAgent instance
        if hasattr(mod, "agent") and isinstance(mod.agent, EvolvableAgent):
            kernel.register_agent(mod.agent, owner=owner)
            log.debug("loaded agent instance: %s from %s", mod.agent.name, file.name)
            return True

        # Strategy 3: class in module that subclasses EvolvableAgent
        for attr_name in dir(mod):
            obj = getattr(mod, attr_name)
            if (
                isinstance(obj, type)
                and issubclass(obj, EvolvableAgent)
                and obj is not EvolvableAgent
                and not attr_name.startswith("_")
            ):
                instance = obj()
                kernel.register_agent(instance, owner=owner)
                log.debug("loaded agent class: %s from %s", instance.name, file.name)
                return True

    except Exception as exc:
        log.warning("agent load failed [%s]: %s", file.name, exc)

    return False
