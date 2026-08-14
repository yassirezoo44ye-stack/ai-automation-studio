"""Sentry typed tool executors."""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.engineering.tools.gateway import ToolDefinition, RiskLevel, get_tool_registry
from app.integrations.types import IntegrationCredential

log = logging.getLogger(__name__)

_SENTRY_API = "https://sentry.io/api/0"
_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)


def _headers(credential: IntegrationCredential) -> dict[str, str]:
    token = credential.secrets.get("auth_token", "")
    if not token:
        raise ValueError("sentry credential missing auth_token")
    return {"Authorization": f"Bearer {token}"}


def _org_slug(credential: IntegrationCredential, args: dict) -> str:
    return args.get("org_slug") or credential.secrets.get("org_slug", "")


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=_TIMEOUT)


async def sentry_list_issues(
    credential: IntegrationCredential, args: dict[str, Any], org_id: str
) -> dict:
    org   = _org_slug(credential, args)
    query = args.get("query", "is:unresolved")
    limit = min(int(args.get("limit", 20)), 100)
    params: dict[str, Any] = {"query": query, "limit": limit}
    if args.get("project"):
        params["project"] = args["project"]
    async with _client() as c:
        resp = await c.get(
            f"{_SENTRY_API}/organizations/{org}/issues/",
            headers=_headers(credential),
            params=params,
        )
    resp.raise_for_status()
    issues = resp.json()
    return {
        "issues": [
            {
                "id":          i["id"],
                "title":       i.get("title", "")[:200],
                "status":      i.get("status"),
                "level":       i.get("level"),
                "count":       i.get("count"),
                "first_seen":  i.get("firstSeen"),
                "last_seen":   i.get("lastSeen"),
                "culprit":     i.get("culprit", "")[:200],
                "permalink":   i.get("permalink"),
            }
            for i in issues
        ],
        "count": len(issues),
        "org_slug": org,
    }


async def sentry_get_issue(
    credential: IntegrationCredential, args: dict[str, Any], org_id: str
) -> dict:
    issue_id = args["issue_id"]
    async with _client() as c:
        resp = await c.get(
            f"{_SENTRY_API}/issues/{issue_id}/",
            headers=_headers(credential),
        )
    resp.raise_for_status()
    i = resp.json()
    return {
        "id":         i["id"],
        "title":      i.get("title", "")[:300],
        "status":     i.get("status"),
        "level":      i.get("level"),
        "count":      i.get("count"),
        "culprit":    i.get("culprit", "")[:300],
        "first_seen": i.get("firstSeen"),
        "last_seen":  i.get("lastSeen"),
        "permalink":  i.get("permalink"),
        # metadata may contain stack trace hints — truncated for LLM safety
        "metadata_type": (i.get("metadata") or {}).get("type", "")[:100],
    }


async def sentry_list_projects(
    credential: IntegrationCredential, args: dict[str, Any], org_id: str
) -> dict:
    org = _org_slug(credential, args)
    async with _client() as c:
        resp = await c.get(
            f"{_SENTRY_API}/organizations/{org}/projects/",
            headers=_headers(credential),
        )
    resp.raise_for_status()
    projects = resp.json()
    return {
        "projects": [
            {"id": p["id"], "slug": p["slug"], "name": p["name"], "platform": p.get("platform")}
            for p in projects
        ],
    }


_TOOL_FNS = {
    "sentry.list_issues":   sentry_list_issues,
    "sentry.get_issue":     sentry_get_issue,
    "sentry.list_projects": sentry_list_projects,
}

SENTRY_TOOLS: dict[str, ToolDefinition] = {
    "sentry.list_issues": ToolDefinition(
        name="sentry.list_issues",
        provider="sentry",
        operation="list_issues",
        description="List Sentry issues (errors and performance problems)",
        risk_level=RiskLevel.READ,
        required_args=[],
    ),
    "sentry.get_issue": ToolDefinition(
        name="sentry.get_issue",
        provider="sentry",
        operation="get_issue",
        description="Get Sentry issue details",
        risk_level=RiskLevel.READ,
        required_args=["issue_id"],
    ),
    "sentry.list_projects": ToolDefinition(
        name="sentry.list_projects",
        provider="sentry",
        operation="list_projects",
        description="List Sentry projects in the organization",
        risk_level=RiskLevel.READ,
        required_args=[],
    ),
}


def _register_sentry_tools() -> None:
    registry = get_tool_registry()
    for defn in SENTRY_TOOLS.values():
        registry.register(defn)
    from app.engineering.tools.gateway import ALL_TOOLS
    for name, fn in _TOOL_FNS.items():
        ALL_TOOLS[name] = fn


_register_sentry_tools()
