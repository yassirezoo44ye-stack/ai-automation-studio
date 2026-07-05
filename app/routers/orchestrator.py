"""
Orchestrator router — Phase 3 enterprise AI endpoints.

Transport layer only: validates inputs, delegates to platform, returns results.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.core.ai.orchestrator.orchestrator import OrchestratorRequest
from app.core.ai.platform import platform
from app.core.ai.policy.engine import PolicyViolationError

router = APIRouter(prefix="/api/ai", tags=["orchestrator"])


# ── Models ────────────────────────────────────────────────────────────────────

class OrchestrateIn(BaseModel):
    prompt:          str
    mode:            str                     = "auto"
    conversation_id: Optional[str]           = None
    project_id:      Optional[str]           = None
    max_cost_usd:    Optional[float]         = None
    context:         dict[str, Any]          = Field(default_factory=dict)


class AgentRunIn(BaseModel):
    agent_name: str
    prompt:     str
    user_id:    Optional[str] = None


class WorkflowRunIn(BaseModel):
    definition: dict[str, Any]
    context:    dict[str, Any] = Field(default_factory=dict)


class WorkflowResumeIn(BaseModel):
    from_node_id: Optional[str] = None


# ── Orchestrator ──────────────────────────────────────────────────────────────

@router.post("/orchestrate")
async def orchestrate(body: OrchestrateIn):
    try:
        req = OrchestratorRequest(
            prompt=body.prompt,
            mode=body.mode,
            conversation_id=body.conversation_id,
            project_id=body.project_id,
            max_cost_usd=body.max_cost_usd,
            context=body.context,
        )
        result = await platform.orchestrate(req)
        return result.__dict__
    except PolicyViolationError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/orchestrate/stream")
async def orchestrate_stream(body: OrchestrateIn):
    req = OrchestratorRequest(
        prompt=body.prompt,
        mode=body.mode,
        conversation_id=body.conversation_id,
        project_id=body.project_id,
        max_cost_usd=body.max_cost_usd,
        context=body.context,
    )

    async def _gen():
        try:
            async for chunk in platform.orchestrator.stream(req):
                yield f"data: {json.dumps(chunk)}\n\n"
        except PolicyViolationError as exc:
            yield f"event: error\ndata: {json.dumps({'message': str(exc), 'code': 403})}\n\n"
        except Exception as exc:
            yield f"event: error\ndata: {json.dumps({'message': str(exc)})}\n\n"

    return StreamingResponse(_gen(), media_type="text/event-stream")


# ── Built-in Agents ───────────────────────────────────────────────────────────

@router.get("/agents/builtin")
async def list_builtin_agents():
    return {"agents": platform.list_agents()}


@router.post("/agents/builtin/run")
async def run_builtin_agent(body: AgentRunIn):
    agent = platform.get_agent(body.agent_name)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent not found: {body.agent_name!r}")
    try:
        result = await agent.run(body.prompt, body.user_id)
        return {
            "success":    result.success,
            "content":    result.content,
            "tool_calls": [tc.__dict__ for tc in result.tool_calls],
            "rounds":     result.rounds,
            "error":      result.error,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/agents/builtin/stream")
async def stream_builtin_agent(body: AgentRunIn):
    agent = platform.get_agent(body.agent_name)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent not found: {body.agent_name!r}")

    async def _gen():
        try:
            async for chunk in agent.stream(body.prompt, body.user_id):
                yield f"data: {json.dumps(chunk)}\n\n"
        except Exception as exc:
            yield f"event: error\ndata: {json.dumps({'message': str(exc)})}\n\n"

    return StreamingResponse(_gen(), media_type="text/event-stream")


# ── Workflows ─────────────────────────────────────────────────────────────────

@router.post("/workflows/run")
async def run_workflow(body: WorkflowRunIn):
    from app.core.ai.workflow.engine import WorkflowDefinition, WorkflowNode

    raw = body.definition
    nodes = {
        nid: WorkflowNode(
            id=nid,
            node_type=ndata.get("node_type", "task"),
            config=ndata.get("config", {}),
            next_nodes=ndata.get("next_nodes", []),
            condition_map=ndata.get("condition_map", {}),
            retry=ndata.get("retry", 0),
            timeout_s=ndata.get("timeout_s", 120.0),
        )
        for nid, ndata in raw.get("nodes", {}).items()
    }
    definition = WorkflowDefinition(
        id=raw.get("id", ""),
        name=raw.get("name", "workflow"),
        nodes=nodes,
        start_node_id=raw.get("start_node_id", ""),
        version=raw.get("version", 1),
    )

    async def _runner(node_id: str, context: dict) -> dict:
        node = definition.nodes[node_id]
        task_prompt = node.config.get("prompt", node.config.get("description", node_id))
        req = OrchestratorRequest(prompt=str(task_prompt))
        result = await platform.orchestrate(req)
        return {"content": result.content, "success": result.success}

    try:
        execution = await platform.workflow.run(definition, _runner, body.context)
        return {
            "execution_id":    execution.execution_id,
            "workflow_id":     execution.workflow_id,
            "state":           execution.state,
            "completed_nodes": execution.completed_nodes,
            "error":           execution.error,
            "context":         execution.context,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/workflows/{execution_id}/resume")
async def resume_workflow(execution_id: str, body: WorkflowResumeIn):
    execution = platform.workflow.get_execution(execution_id)
    if execution is None:
        raise HTTPException(status_code=404, detail=f"Execution not found: {execution_id}")
    raise HTTPException(status_code=501, detail="Resume requires re-submitting the workflow definition")


@router.get("/workflows/{execution_id}")
async def get_execution(execution_id: str):
    execution = platform.workflow.get_execution(execution_id)
    if execution is None:
        raise HTTPException(status_code=404, detail=f"Execution not found: {execution_id}")
    return {
        "execution_id":    execution.execution_id,
        "workflow_id":     execution.workflow_id,
        "state":           execution.state,
        "completed_nodes": execution.completed_nodes,
        "current_node":    execution.current_node,
        "error":           execution.error,
    }


# ── Cost ──────────────────────────────────────────────────────────────────────

@router.get("/cost/summary")
async def cost_summary():
    return platform.cost.summary()
