"""
AI Kernel — Self-Modifying AI Operating System Runtime.

Public API:

    from app.kernel import get_kernel

    kernel = get_kernel()
    result = await kernel.execute("status")
    result = await kernel.execute("patch --file=app/commands/builtin/run_cmd.py --find=old --replace=new")
    result = await kernel.execute("reload app/commands/plugins/greet.py")
    result = await kernel.execute("rollback 0")

Process-lifetime singleton.  Call get_kernel().boot() once at startup.
"""
from __future__ import annotations

from app.kernel.kernel import AIKernel
from app.kernel.state import KernelState
from app.kernel.policy import PolicyEngine, PolicyViolation
from app.kernel.self_modify import SelfModifyingEngine, ModifyError
from app.kernel.reloader import HotReloader, ReloadError
from app.kernel.middleware import KernelContext, MiddlewareFn
from app.kernel.agents import BaseAgent, AgentState, CommandAgent

_kernel: AIKernel | None = None


def get_kernel() -> AIKernel:
    global _kernel
    if _kernel is None:
        _kernel = AIKernel()
        _kernel.boot()
    return _kernel


__all__ = [
    "AIKernel", "get_kernel",
    "KernelState", "PolicyEngine", "PolicyViolation",
    "SelfModifyingEngine", "ModifyError",
    "HotReloader", "ReloadError",
    "KernelContext", "MiddlewareFn",
    "BaseAgent", "AgentState", "CommandAgent",
]
