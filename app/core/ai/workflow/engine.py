"""
WorkflowEngine — graph-based workflow execution.

Node types: start | end | task | condition | parallel | merge | checkpoint
Supports: sequential, parallel, conditional branching, retry, timeout,
          checkpoint/resume, rollback.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, Optional

from ..events.bus import EventBus
from ..events.events import (
    WorkflowStarted, WorkflowNodeEntered,
    WorkflowNodeCompleted, WorkflowCompleted, WorkflowFailed,
)


NodeRunner = Callable[[str, dict[str, Any]], Coroutine[Any, Any, dict[str, Any]]]


@dataclass
class WorkflowNode:
    id:            str
    node_type:     str                    # "start"|"end"|"task"|"condition"|"parallel"|"merge"|"checkpoint"
    config:        dict[str, Any]         = field(default_factory=dict)
    next_nodes:    list[str]              = field(default_factory=list)   # default outgoing edges
    condition_map: dict[str, str]         = field(default_factory=dict)   # condition value → node_id
    retry:         int                    = 0
    timeout_s:     float                  = 120.0


@dataclass
class WorkflowDefinition:
    id:            str
    name:          str
    nodes:         dict[str, WorkflowNode]   # node_id → node
    start_node_id: str
    version:       int = 1
    metadata:      dict[str, Any] = field(default_factory=dict)

    @classmethod
    def simple_sequence(cls, steps: list[dict[str, Any]]) -> "WorkflowDefinition":
        """Factory: build a linear workflow from a list of step configs."""
        wf_id = str(uuid.uuid4())
        nodes: dict[str, WorkflowNode] = {}
        node_ids = [str(uuid.uuid4()) for _ in range(len(steps) + 2)]
        start_id, end_id = node_ids[0], node_ids[-1]

        nodes[start_id] = WorkflowNode(id=start_id, node_type="start", next_nodes=[node_ids[1]])
        for i, step in enumerate(steps):
            nid = node_ids[i + 1]
            nxt = [node_ids[i + 2]]
            nodes[nid] = WorkflowNode(id=nid, node_type="task", config=step, next_nodes=nxt)
        nodes[end_id] = WorkflowNode(id=end_id, node_type="end")

        return cls(
            id=wf_id,
            name="sequence",
            nodes=nodes,
            start_node_id=start_id,
        )


@dataclass
class WorkflowExecution:
    execution_id:   str                   = field(default_factory=lambda: str(uuid.uuid4()))
    workflow_id:    str                   = ""
    state:          str                   = "pending"   # pending|running|completed|failed|paused
    context:        dict[str, Any]        = field(default_factory=dict)
    checkpoints:    dict[str, Any]        = field(default_factory=dict)   # node_id → state snapshot
    completed_nodes: list[str]            = field(default_factory=list)
    current_node:   Optional[str]         = None
    error:          Optional[str]         = None
    started_at:     float                 = field(default_factory=time.time)
    finished_at:    Optional[float]       = None


class WorkflowEngine:
    """
    Executes WorkflowDefinitions as directed graphs.

    Usage:
        engine = WorkflowEngine(bus)
        exec_  = await engine.run(definition, runner, initial_context)
    """

    def __init__(self, bus: EventBus) -> None:
        self._bus         = bus
        self._executions: dict[str, WorkflowExecution] = {}

    async def run(
        self,
        definition: WorkflowDefinition,
        runner:     NodeRunner,
        context:    Optional[dict[str, Any]] = None,
    ) -> WorkflowExecution:
        execution = WorkflowExecution(
            workflow_id=definition.id,
            context=context or {},
        )
        self._executions[execution.execution_id] = execution
        execution.state = "running"

        await self._bus.emit(WorkflowStarted(
            workflow_id=definition.id,
            execution_id=execution.execution_id,
            node_count=len(definition.nodes),
        ))

        try:
            await self._execute_node(definition, execution, definition.start_node_id, runner)
            execution.state = "completed"
            execution.finished_at = time.time()
            await self._bus.emit(WorkflowCompleted(
                execution_id=execution.execution_id,
                workflow_id=definition.id,
                duration_ms=(execution.finished_at - execution.started_at) * 1000,
                nodes_executed=len(execution.completed_nodes),
            ))
        except Exception as exc:
            execution.state = "failed"
            execution.error = str(exc)
            execution.finished_at = time.time()
            await self._bus.emit(WorkflowFailed(
                execution_id=execution.execution_id,
                workflow_id=definition.id,
                node_id=execution.current_node or "",
                error=str(exc),
            ))
            raise

        return execution

    async def resume(
        self,
        execution_id: str,
        definition:   WorkflowDefinition,
        runner:       NodeRunner,
        from_node_id: Optional[str] = None,
    ) -> WorkflowExecution:
        execution = self._executions.get(execution_id)
        if execution is None:
            raise ValueError(f"Unknown execution: {execution_id}")
        if execution.state not in ("paused", "failed"):
            raise RuntimeError(f"Cannot resume execution in state: {execution.state}")

        start = from_node_id or execution.current_node or definition.start_node_id
        execution.state = "running"

        # Restore from checkpoint if available
        if start in execution.checkpoints:
            execution.context.update(execution.checkpoints[start])

        await self._execute_node(definition, execution, start, runner)
        execution.state = "completed"
        execution.finished_at = time.time()
        return execution

    def get_execution(self, execution_id: str) -> Optional[WorkflowExecution]:
        return self._executions.get(execution_id)

    # ── Node dispatch ──────────────────────────────────────────────────────────

    async def _execute_node(
        self,
        definition: WorkflowDefinition,
        execution:  WorkflowExecution,
        node_id:    str,
        runner:     NodeRunner,
    ) -> None:
        if node_id not in definition.nodes:
            raise ValueError(f"Node not found: {node_id}")

        node = definition.nodes[node_id]
        if node_id in execution.completed_nodes:
            return   # already done (merge node convergence guard)

        execution.current_node = node_id
        t0 = time.perf_counter()

        await self._bus.emit(WorkflowNodeEntered(
            execution_id=execution.execution_id,
            node_id=node_id,
            node_type=node.node_type,
        ))

        if node.node_type == "start":
            execution.completed_nodes.append(node_id)
            for nxt in node.next_nodes:
                await self._execute_node(definition, execution, nxt, runner)

        elif node.node_type == "end":
            execution.completed_nodes.append(node_id)

        elif node.node_type == "task":
            result = await self._run_with_retry(node, runner, execution.context)
            execution.context[f"node_{node_id}"] = result
            execution.completed_nodes.append(node_id)
            for nxt in node.next_nodes:
                await self._execute_node(definition, execution, nxt, runner)

        elif node.node_type == "condition":
            result = await self._run_with_retry(node, runner, execution.context)
            outcome = str(result.get("outcome", "default"))
            next_id = node.condition_map.get(outcome) or (node.next_nodes[0] if node.next_nodes else None)
            execution.completed_nodes.append(node_id)
            if next_id:
                await self._execute_node(definition, execution, next_id, runner)

        elif node.node_type == "parallel":
            await asyncio.gather(*[
                self._execute_node(definition, execution, nxt, runner)
                for nxt in node.next_nodes
            ])
            execution.completed_nodes.append(node_id)

        elif node.node_type == "merge":
            execution.completed_nodes.append(node_id)
            for nxt in node.next_nodes:
                await self._execute_node(definition, execution, nxt, runner)

        elif node.node_type == "checkpoint":
            execution.checkpoints[node_id] = dict(execution.context)
            execution.completed_nodes.append(node_id)
            for nxt in node.next_nodes:
                await self._execute_node(definition, execution, nxt, runner)

        duration_ms = (time.perf_counter() - t0) * 1000
        await self._bus.emit(WorkflowNodeCompleted(
            execution_id=execution.execution_id,
            node_id=node_id,
            duration_ms=duration_ms,
        ))

    async def _run_with_retry(
        self,
        node:    WorkflowNode,
        runner:  NodeRunner,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        last_exc: Optional[Exception] = None
        for attempt in range(node.retry + 1):
            try:
                return await asyncio.wait_for(
                    runner(node.id, context),
                    timeout=node.timeout_s,
                )
            except asyncio.TimeoutError:
                last_exc = TimeoutError(f"Node {node.id} timed out")
            except Exception as exc:
                last_exc = exc
            if attempt < node.retry:
                await asyncio.sleep(0.5 * (attempt + 1))
        raise last_exc or RuntimeError(f"Node {node.id} failed")
