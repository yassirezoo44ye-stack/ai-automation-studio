"""
Workflow Node registry — the one genuinely new registry this SDK adds.

Confirmed (app/core/workflow/engine.py): workflow steps are always inline
closures passed directly to WorkflowBuilder.step(fn=...); there is no
existing concept of a reusable, named "workflow node" type. A WORKFLOW_NODE
plugin registers a named StepFn here; a workflow author can then look it up
by name and pass it straight into WorkflowBuilder.step(fn=get_node(name)).
"""
from __future__ import annotations

import logging

from app.core.workflow.engine import StepFn

log = logging.getLogger(__name__)


class WorkflowNodeRegistry:
    def __init__(self) -> None:
        self._nodes: dict[str, StepFn] = {}

    def register(self, name: str, fn: StepFn) -> None:
        self._nodes[name] = fn
        log.debug("registered workflow node: %s", name)

    def unregister(self, name: str) -> bool:
        return self._nodes.pop(name, None) is not None

    def get_node(self, name: str) -> StepFn | None:
        return self._nodes.get(name)

    def list_nodes(self) -> list[str]:
        return sorted(self._nodes.keys())


_registry: WorkflowNodeRegistry | None = None


def get_workflow_node_registry() -> WorkflowNodeRegistry:
    global _registry
    if _registry is None:
        _registry = WorkflowNodeRegistry()
    return _registry
