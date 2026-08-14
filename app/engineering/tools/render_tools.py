"""
Render typed tool executors.

CRITICAL: render.trigger_deploy HTTP 200 ≠ deployment success.
Real success requires:
  1. Deploy status transitions to "live"
  2. Health endpoint returns 200
  3. observed production SHA == requested SHA

All three are captured as Evidence by the VerifyEngine (app/engineering/verify.py).
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.engineering.tools.gateway import ToolDefinition, RiskLevel, get_tool_registry
from app.integrations.types import IntegrationCredential

log = logging.getLogger(__name__)

_RENDER_API = "https://api.render.com/v1"
_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)


def _headers(credential: IntegrationCredential) -> dict[str, str]:
    api_key = credential.secrets.get("api_key", "")
    if not api_key:
        raise ValueError("render credential missing api_key")
    return {"Authorization": f"Bearer {api_key}"}


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=_TIMEOUT)


# ── Tool executors ─────────────────────────────────────────────────────────────

async def render_list_services(
    credential: IntegrationCredential, args: dict[str, Any], org_id: str
) -> dict:
    params: dict[str, Any] = {"limit": min(int(args.get("limit", 20)), 100)}
    if args.get("name"):
        params["name"] = args["name"]
    async with _client() as c:
        resp = await c.get(f"{_RENDER_API}/services", headers=_headers(credential), params=params)
    resp.raise_for_status()
    services = resp.json()
    return {
        "services": [
            {
                "id":          svc["service"]["id"],
                "name":        svc["service"]["name"],
                "type":        svc["service"]["type"],
                "status":      svc["service"].get("suspended"),
                "environment": svc["service"].get("serviceDetails", {}).get("env"),
                "url":         svc["service"].get("serviceDetails", {}).get("url"),
            }
            for svc in services
        ],
        "count": len(services),
    }


async def render_get_service(
    credential: IntegrationCredential, args: dict[str, Any], org_id: str
) -> dict:
    service_id = args["service_id"]
    async with _client() as c:
        resp = await c.get(f"{_RENDER_API}/services/{service_id}", headers=_headers(credential))
    resp.raise_for_status()
    svc = resp.json()
    return {
        "id":          svc["id"],
        "name":        svc["name"],
        "type":        svc["type"],
        "url":         svc.get("serviceDetails", {}).get("url"),
        "branch":      svc.get("serviceDetails", {}).get("branch"),
        "repo":        svc.get("repo"),
        "environment": svc.get("serviceDetails", {}).get("env"),
    }


async def render_trigger_deploy(
    credential: IntegrationCredential, args: dict[str, Any], org_id: str
) -> dict:
    """Trigger a deployment. Returns deploy_id for status polling.

    DO NOT interpret HTTP 201 as deployment success. Poll render.get_deploy_status
    until status='live' and then run VerifyEngine.verify() for final Evidence.
    """
    service_id  = args["service_id"]
    clear_cache = bool(args.get("clear_cache", False))
    async with _client() as c:
        resp = await c.post(
            f"{_RENDER_API}/services/{service_id}/deploys",
            headers=_headers(credential),
            json={"clearCache": "clear" if clear_cache else "do_not_clear"},
        )
    resp.raise_for_status()
    deploy = resp.json()
    deploy_id = deploy.get("id")
    return {
        "deploy_id":     deploy_id,
        "status":        deploy.get("status", "created"),
        "service_id":    service_id,
        "triggered":     True,
        # Explicitly communicate that this is NOT yet verified
        "verified":      False,
        "note":          "Deploy triggered. Poll render.get_deploy_status until status='live', "
                         "then run production verification to confirm SHA match.",
    }


async def render_get_deploy_status(
    credential: IntegrationCredential, args: dict[str, Any], org_id: str
) -> dict:
    """Poll deployment status. Possible statuses: created, build_in_progress,
    update_in_progress, live, deactivated, build_failed, pre_deploy_failed,
    canceled."""
    service_id = args["service_id"]
    deploy_id  = args["deploy_id"]
    async with _client() as c:
        resp = await c.get(
            f"{_RENDER_API}/services/{service_id}/deploys/{deploy_id}",
            headers=_headers(credential),
        )
    resp.raise_for_status()
    deploy = resp.json()
    status = deploy.get("status", "unknown")
    return {
        "deploy_id":      deploy_id,
        "service_id":     service_id,
        "status":         status,
        "is_live":        status == "live",
        "is_failed":      status in ("build_failed", "pre_deploy_failed", "canceled"),
        "commit_id":      deploy.get("commit", {}).get("id"),
        "commit_message": (deploy.get("commit", {}).get("message") or "")[:200],
        "created_at":     deploy.get("createdAt"),
        "finished_at":    deploy.get("finishedAt"),
        # observed_sha: populated if the deploy tracks the git SHA
        "observed_sha":   deploy.get("commit", {}).get("id"),
    }


async def render_list_deploys(
    credential: IntegrationCredential, args: dict[str, Any], org_id: str
) -> dict:
    service_id = args["service_id"]
    limit      = min(int(args.get("limit", 10)), 50)
    async with _client() as c:
        resp = await c.get(
            f"{_RENDER_API}/services/{service_id}/deploys",
            headers=_headers(credential),
            params={"limit": limit},
        )
    resp.raise_for_status()
    deploys = resp.json()
    return {
        "deploys": [
            {
                "id":          d.get("id"),
                "status":      d.get("status"),
                "commit_id":   d.get("commit", {}).get("id"),
                "created_at":  d.get("createdAt"),
                "finished_at": d.get("finishedAt"),
            }
            for d in deploys
        ],
        "service_id": service_id,
    }


async def render_get_logs(
    credential: IntegrationCredential, args: dict[str, Any], org_id: str
) -> dict:
    """Read recent application logs (last N lines)."""
    service_id = args["service_id"]
    lines      = min(int(args.get("lines", 100)), 500)
    async with _client() as c:
        resp = await c.get(
            f"{_RENDER_API}/services/{service_id}/logs",
            headers=_headers(credential),
            params={"limit": lines},
        )
    resp.raise_for_status()
    data = resp.json()
    log_lines = data if isinstance(data, list) else data.get("logs", [])
    return {
        "logs": [
            {
                "timestamp": entry.get("timestamp"),
                "message":   (entry.get("message") or "")[:1000],
                "level":     entry.get("level", "info"),
            }
            for entry in log_lines[:lines]
        ],
        "service_id": service_id,
        "count":      len(log_lines),
    }


# ── Tool definitions ───────────────────────────────────────────────────────────

_TOOL_FNS = {
    "render.list_services":      render_list_services,
    "render.get_service":        render_get_service,
    "render.trigger_deploy":     render_trigger_deploy,
    "render.get_deploy_status":  render_get_deploy_status,
    "render.list_deploys":       render_list_deploys,
    "render.get_logs":           render_get_logs,
}

RENDER_TOOLS: dict[str, ToolDefinition] = {
    "render.list_services": ToolDefinition(
        name="render.list_services",
        provider="render",
        operation="list_services",
        description="List Render services for this organization",
        risk_level=RiskLevel.READ,
        required_args=[],
    ),
    "render.get_service": ToolDefinition(
        name="render.get_service",
        provider="render",
        operation="get_service",
        description="Get Render service details including URL and branch",
        risk_level=RiskLevel.READ,
        required_args=["service_id"],
    ),
    "render.trigger_deploy": ToolDefinition(
        name="render.trigger_deploy",
        provider="render",
        operation="trigger_deploy",
        description="Trigger a new Render deployment (requires approval in production)",
        risk_level=RiskLevel.DEPLOY,
        required_args=["service_id"],
        idempotent=False,
    ),
    "render.get_deploy_status": ToolDefinition(
        name="render.get_deploy_status",
        provider="render",
        operation="get_deploy_status",
        description="Poll Render deployment status (created/build_in_progress/live/failed)",
        risk_level=RiskLevel.READ,
        required_args=["service_id", "deploy_id"],
    ),
    "render.list_deploys": ToolDefinition(
        name="render.list_deploys",
        provider="render",
        operation="list_deploys",
        description="List recent deployments for a Render service",
        risk_level=RiskLevel.READ,
        required_args=["service_id"],
    ),
    "render.get_logs": ToolDefinition(
        name="render.get_logs",
        provider="render",
        operation="get_logs",
        description="Read recent application logs from a Render service",
        risk_level=RiskLevel.READ,
        required_args=["service_id"],
    ),
}


def _register_render_tools() -> None:
    registry = get_tool_registry()
    for defn in RENDER_TOOLS.values():
        registry.register(defn)

    from app.engineering.tools.gateway import ALL_TOOLS
    for name, fn in _TOOL_FNS.items():
        ALL_TOOLS[name] = fn


_register_render_tools()
