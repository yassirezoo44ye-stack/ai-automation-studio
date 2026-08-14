"""Vercel typed tool executors."""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.engineering.tools.gateway import ToolDefinition, RiskLevel, get_tool_registry
from app.integrations.types import IntegrationCredential

log = logging.getLogger(__name__)

_VERCEL_API = "https://api.vercel.com"
_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)


def _headers(credential: IntegrationCredential) -> dict[str, str]:
    token = credential.secrets.get("token", "")
    if not token:
        raise ValueError("vercel credential missing token")
    return {"Authorization": f"Bearer {token}"}


def _team_params(credential: IntegrationCredential) -> dict[str, str]:
    team_id = credential.secrets.get("team_id", "")
    return {"teamId": team_id} if team_id else {}


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=_TIMEOUT)


async def vercel_list_projects(
    credential: IntegrationCredential, args: dict[str, Any], org_id: str
) -> dict:
    params = {**_team_params(credential), "limit": min(int(args.get("limit", 20)), 100)}
    async with _client() as c:
        resp = await c.get(f"{_VERCEL_API}/v9/projects", headers=_headers(credential), params=params)
    resp.raise_for_status()
    data = resp.json()
    projects = data.get("projects", [])
    return {
        "projects": [
            {
                "id":            p["id"],
                "name":          p["name"],
                "framework":     p.get("framework"),
                "git_repo":      (p.get("link") or {}).get("repo"),
                "updated_at":    p.get("updatedAt"),
                "production_url": (p.get("targets") or {}).get("production", {}).get("alias", [None])[0] if p.get("targets") else None,
            }
            for p in projects
        ],
        "count": len(projects),
    }


async def vercel_list_deployments(
    credential: IntegrationCredential, args: dict[str, Any], org_id: str
) -> dict:
    params = {
        **_team_params(credential),
        "limit": min(int(args.get("limit", 10)), 50),
    }
    if args.get("project_id"):
        params["projectId"] = args["project_id"]
    async with _client() as c:
        resp = await c.get(f"{_VERCEL_API}/v6/deployments", headers=_headers(credential), params=params)
    resp.raise_for_status()
    data = resp.json()
    deployments = data.get("deployments", [])
    return {
        "deployments": [
            {
                "uid":        d["uid"],
                "url":        d.get("url"),
                "state":      d.get("state"),
                "target":     d.get("target"),
                "git_sha":    (d.get("meta") or {}).get("githubCommitSha"),
                "created_at": d.get("createdAt"),
            }
            for d in deployments
        ],
    }


async def vercel_get_deployment(
    credential: IntegrationCredential, args: dict[str, Any], org_id: str
) -> dict:
    deployment_id = args["deployment_id"]
    params = {**_team_params(credential)}
    async with _client() as c:
        resp = await c.get(
            f"{_VERCEL_API}/v13/deployments/{deployment_id}",
            headers=_headers(credential),
            params=params,
        )
    resp.raise_for_status()
    d = resp.json()
    return {
        "uid":        d.get("uid"),
        "url":        d.get("url"),
        "state":      d.get("readyState"),
        "target":     d.get("target"),
        "git_sha":    (d.get("meta") or {}).get("githubCommitSha"),
        "is_live":    d.get("readyState") in ("READY", "ready"),
        "created_at": d.get("createdAt"),
    }


_TOOL_FNS = {
    "vercel.list_projects":     vercel_list_projects,
    "vercel.list_deployments":  vercel_list_deployments,
    "vercel.get_deployment":    vercel_get_deployment,
}

VERCEL_TOOLS: dict[str, ToolDefinition] = {
    "vercel.list_projects": ToolDefinition(
        name="vercel.list_projects",
        provider="vercel",
        operation="list_projects",
        description="List Vercel projects",
        risk_level=RiskLevel.READ,
        required_args=[],
    ),
    "vercel.list_deployments": ToolDefinition(
        name="vercel.list_deployments",
        provider="vercel",
        operation="list_deployments",
        description="List recent Vercel deployments",
        risk_level=RiskLevel.READ,
        required_args=[],
    ),
    "vercel.get_deployment": ToolDefinition(
        name="vercel.get_deployment",
        provider="vercel",
        operation="get_deployment",
        description="Get Vercel deployment status and git SHA",
        risk_level=RiskLevel.READ,
        required_args=["deployment_id"],
    ),
}


def _register_vercel_tools() -> None:
    registry = get_tool_registry()
    for defn in VERCEL_TOOLS.values():
        registry.register(defn)
    from app.engineering.tools.gateway import ALL_TOOLS
    for name, fn in _TOOL_FNS.items():
        ALL_TOOLS[name] = fn


_register_vercel_tools()
