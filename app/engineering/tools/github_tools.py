"""
GitHub typed tool executors for the Engineering Control Plane.

Each function signature:
  async def fn(credential, args, org_id) -> dict

These functions are called ONLY by EngineeringToolGateway after:
  - authentication (credential loaded from CredentialStore)
  - permission check (role validated)
  - approval check (for DEPLOY/DESTRUCTIVE)
  - budget check (steps_used < budget_steps)

They return sanitized output dicts. They NEVER:
  - log the credential
  - include secrets in return values
  - execute arbitrary commands
  - make requests to non-GitHub URLs

All HTTP calls use httpx with explicit timeouts.

GITHUB_TOOLS maps tool_name → ToolDefinition (registered in gateway.py).
The corresponding fn for each tool is stored in _FN_REGISTRY and looked
up by the gateway at call time.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.engineering.tools.gateway import ToolDefinition, RiskLevel, get_tool_registry
from app.integrations.types import IntegrationCredential

log = logging.getLogger(__name__)

_GITHUB_API = "https://api.github.com"
_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)


def _headers(credential: IntegrationCredential) -> dict[str, str]:
    token = credential.secrets.get("token") or credential.secrets.get("installation_token")
    if not token:
        raise ValueError("github credential has no usable token")
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=_TIMEOUT)


# ── Tool executors ─────────────────────────────────────────────────────────────

async def github_list_repositories(
    credential: IntegrationCredential, args: dict[str, Any], org_id: str
) -> dict:
    """List repositories the token can access."""
    params: dict[str, Any] = {
        "visibility": args.get("visibility", "all"),
        "per_page":   min(int(args.get("per_page", 30)), 100),
        "page":       int(args.get("page", 1)),
    }
    async with _client() as c:
        resp = await c.get(f"{_GITHUB_API}/user/repos", headers=_headers(credential), params=params)
    resp.raise_for_status()
    repos = resp.json()
    return {
        "repositories": [
            {
                "full_name":    r["full_name"],
                "default_branch": r.get("default_branch", "main"),
                "private":      r["private"],
                "description":  r.get("description"),
                "pushed_at":    r.get("pushed_at"),
            }
            for r in repos
        ],
        "count": len(repos),
    }


async def github_get_commit(
    credential: IntegrationCredential, args: dict[str, Any], org_id: str
) -> dict:
    """Get a specific commit's SHA and metadata."""
    repo = args["repo"]
    ref  = args.get("ref", "HEAD")
    async with _client() as c:
        resp = await c.get(
            f"{_GITHUB_API}/repos/{repo}/commits/{ref}",
            headers=_headers(credential),
        )
    resp.raise_for_status()
    data = resp.json()
    return {
        "sha":     data["sha"],
        "message": data["commit"]["message"].splitlines()[0][:200],
        "author":  data["commit"]["author"].get("name"),
        "date":    data["commit"]["author"].get("date"),
        "ref":     ref,
        "repo":    repo,
    }


async def github_list_branches(
    credential: IntegrationCredential, args: dict[str, Any], org_id: str
) -> dict:
    repo = args["repo"]
    params = {"per_page": min(int(args.get("per_page", 30)), 100)}
    async with _client() as c:
        resp = await c.get(
            f"{_GITHUB_API}/repos/{repo}/branches",
            headers=_headers(credential),
            params=params,
        )
    resp.raise_for_status()
    branches = resp.json()
    return {
        "branches": [
            {"name": b["name"], "sha": b["commit"]["sha"]}
            for b in branches
        ],
        "repo": repo,
    }


async def github_create_branch(
    credential: IntegrationCredential, args: dict[str, Any], org_id: str
) -> dict:
    """Create a new branch from a given SHA."""
    repo       = args["repo"]
    branch     = args["branch"]
    from_sha   = args["from_sha"]
    async with _client() as c:
        resp = await c.post(
            f"{_GITHUB_API}/repos/{repo}/git/refs",
            headers=_headers(credential),
            json={"ref": f"refs/heads/{branch}", "sha": from_sha},
        )
    if resp.status_code == 422 and "already exists" in resp.text:
        return {"created": False, "branch": branch, "message": "branch already exists"}
    resp.raise_for_status()
    return {"created": True, "branch": branch, "sha": from_sha, "repo": repo}


async def github_list_pull_requests(
    credential: IntegrationCredential, args: dict[str, Any], org_id: str
) -> dict:
    repo   = args["repo"]
    state  = args.get("state", "open")
    params = {"state": state, "per_page": min(int(args.get("per_page", 20)), 100)}
    async with _client() as c:
        resp = await c.get(
            f"{_GITHUB_API}/repos/{repo}/pulls",
            headers=_headers(credential),
            params=params,
        )
    resp.raise_for_status()
    prs = resp.json()
    return {
        "pull_requests": [
            {
                "number": pr["number"],
                "title":  pr["title"],
                "state":  pr["state"],
                "head":   pr["head"]["ref"],
                "base":   pr["base"]["ref"],
                "url":    pr["html_url"],
                "draft":  pr.get("draft", False),
                "mergeable": pr.get("mergeable"),
            }
            for pr in prs
        ],
        "repo": repo,
    }


async def github_create_pull_request(
    credential: IntegrationCredential, args: dict[str, Any], org_id: str
) -> dict:
    repo   = args["repo"]
    title  = args["title"]
    head   = args["head"]
    base   = args.get("base", "main")
    body   = args.get("body", "")
    draft  = bool(args.get("draft", False))
    async with _client() as c:
        resp = await c.post(
            f"{_GITHUB_API}/repos/{repo}/pulls",
            headers=_headers(credential),
            json={"title": title, "head": head, "base": base, "body": body, "draft": draft},
        )
    resp.raise_for_status()
    pr = resp.json()
    return {
        "number":   pr["number"],
        "url":      pr["html_url"],
        "title":    pr["title"],
        "state":    pr["state"],
        "head":     pr["head"]["ref"],
        "base":     pr["base"]["ref"],
        "draft":    pr.get("draft", False),
        "repo":     repo,
    }


async def github_get_pull_request(
    credential: IntegrationCredential, args: dict[str, Any], org_id: str
) -> dict:
    repo   = args["repo"]
    number = int(args["number"])
    async with _client() as c:
        resp = await c.get(
            f"{_GITHUB_API}/repos/{repo}/pulls/{number}",
            headers=_headers(credential),
        )
    resp.raise_for_status()
    pr = resp.json()
    return {
        "number":       pr["number"],
        "title":        pr["title"],
        "state":        pr["state"],
        "head_sha":     pr["head"]["sha"],
        "base":         pr["base"]["ref"],
        "url":          pr["html_url"],
        "mergeable":    pr.get("mergeable"),
        "draft":        pr.get("draft", False),
        "ci_status":    pr.get("head", {}).get("sha"),   # will be enriched by checks
        "body":         (pr.get("body") or "")[:500],
    }


async def github_merge_pull_request(
    credential: IntegrationCredential, args: dict[str, Any], org_id: str
) -> dict:
    """Merge a PR — DESTRUCTIVE. Requires active approval."""
    repo           = args["repo"]
    number         = int(args["number"])
    merge_method   = args.get("merge_method", "squash")  # merge|squash|rebase
    commit_title   = args.get("commit_title", "")
    async with _client() as c:
        resp = await c.put(
            f"{_GITHUB_API}/repos/{repo}/pulls/{number}/merge",
            headers=_headers(credential),
            json={
                "merge_method":  merge_method,
                "commit_title":  commit_title or f"Merge PR #{number}",
            },
        )
    if resp.status_code == 405:
        return {"merged": False, "reason": "not_mergeable", "pr_number": number}
    resp.raise_for_status()
    data = resp.json()
    return {
        "merged":    data.get("merged", False),
        "sha":       data.get("sha"),
        "message":   data.get("message"),
        "pr_number": number,
        "repo":      repo,
    }


async def github_list_checks(
    credential: IntegrationCredential, args: dict[str, Any], org_id: str
) -> dict:
    """List check runs for a given commit SHA."""
    repo = args["repo"]
    ref  = args["ref"]   # commit SHA or branch name
    async with _client() as c:
        resp = await c.get(
            f"{_GITHUB_API}/repos/{repo}/commits/{ref}/check-runs",
            headers=_headers(credential),
            params={"per_page": 50},
        )
    resp.raise_for_status()
    data = resp.json()
    checks = data.get("check_runs", [])
    return {
        "checks": [
            {
                "id":          ch["id"],
                "name":        ch["name"],
                "status":      ch["status"],
                "conclusion":  ch.get("conclusion"),
                "started_at":  ch.get("started_at"),
                "completed_at": ch.get("completed_at"),
                "url":         ch.get("html_url"),
            }
            for ch in checks
        ],
        "total":   data.get("total_count", len(checks)),
        "ref":     ref,
        "repo":    repo,
        "all_passed": all(
            ch.get("conclusion") == "success"
            for ch in checks
            if ch["status"] == "completed"
        ),
    }


async def github_list_workflow_runs(
    credential: IntegrationCredential, args: dict[str, Any], org_id: str
) -> dict:
    repo   = args["repo"]
    branch = args.get("branch")
    params: dict[str, Any] = {"per_page": min(int(args.get("per_page", 10)), 50)}
    if branch:
        params["branch"] = branch
    async with _client() as c:
        resp = await c.get(
            f"{_GITHUB_API}/repos/{repo}/actions/runs",
            headers=_headers(credential),
            params=params,
        )
    resp.raise_for_status()
    data = resp.json()
    runs = data.get("workflow_runs", [])
    return {
        "runs": [
            {
                "id":         run["id"],
                "name":       run["name"],
                "status":     run["status"],
                "conclusion": run.get("conclusion"),
                "head_sha":   run["head_sha"],
                "branch":     run.get("head_branch"),
                "url":        run.get("html_url"),
                "created_at": run.get("created_at"),
            }
            for run in runs
        ],
        "total": data.get("total_count", 0),
    }


async def github_create_issue(
    credential: IntegrationCredential, args: dict[str, Any], org_id: str
) -> dict:
    repo   = args["repo"]
    title  = args["title"]
    body   = args.get("body", "")
    labels = args.get("labels", [])
    async with _client() as c:
        resp = await c.post(
            f"{_GITHUB_API}/repos/{repo}/issues",
            headers=_headers(credential),
            json={"title": title, "body": body, "labels": labels},
        )
    resp.raise_for_status()
    issue = resp.json()
    return {
        "number": issue["number"],
        "url":    issue["html_url"],
        "title":  issue["title"],
        "state":  issue["state"],
    }


async def github_get_deployment_status(
    credential: IntegrationCredential, args: dict[str, Any], org_id: str
) -> dict:
    """Read GitHub Deployments API to get the latest deployment status for a ref."""
    repo = args["repo"]
    ref  = args.get("ref", "main")
    async with _client() as c:
        resp = await c.get(
            f"{_GITHUB_API}/repos/{repo}/deployments",
            headers=_headers(credential),
            params={"ref": ref, "per_page": 5},
        )
    resp.raise_for_status()
    deployments = resp.json()
    if not deployments:
        return {"deployments": [], "latest_sha": None}
    latest = deployments[0]
    # Get latest status for the most recent deployment
    async with _client() as c:
        sr = await c.get(
            f"{_GITHUB_API}/repos/{repo}/deployments/{latest['id']}/statuses",
            headers=_headers(credential),
            params={"per_page": 1},
        )
    sr.raise_for_status()
    statuses = sr.json()
    latest_state = statuses[0]["state"] if statuses else "unknown"
    return {
        "deployment_id": latest["id"],
        "sha":           latest["sha"],
        "environment":   latest.get("environment", "production"),
        "state":         latest_state,
        "url":           latest.get("url"),
        "created_at":    latest.get("created_at"),
    }


# ── Tool definitions + fn registry ────────────────────────────────────────────

_TOOL_FNS = {
    "github.list_repositories":      github_list_repositories,
    "github.get_commit":             github_get_commit,
    "github.list_branches":          github_list_branches,
    "github.create_branch":          github_create_branch,
    "github.list_pull_requests":     github_list_pull_requests,
    "github.create_pull_request":    github_create_pull_request,
    "github.get_pull_request":       github_get_pull_request,
    "github.merge_pull_request":     github_merge_pull_request,
    "github.list_checks":            github_list_checks,
    "github.list_workflow_runs":     github_list_workflow_runs,
    "github.create_issue":           github_create_issue,
    "github.get_deployment_status":  github_get_deployment_status,
}

GITHUB_TOOLS: dict[str, ToolDefinition] = {
    "github.list_repositories": ToolDefinition(
        name="github.list_repositories",
        provider="github",
        operation="list_repositories",
        description="List GitHub repositories the connected token can access",
        risk_level=RiskLevel.READ,
        required_args=[],
    ),
    "github.get_commit": ToolDefinition(
        name="github.get_commit",
        provider="github",
        operation="get_commit",
        description="Get metadata (SHA, message, author, date) for a commit ref",
        risk_level=RiskLevel.READ,
        required_args=["repo"],
    ),
    "github.list_branches": ToolDefinition(
        name="github.list_branches",
        provider="github",
        operation="list_branches",
        description="List branches for a repository",
        risk_level=RiskLevel.READ,
        required_args=["repo"],
    ),
    "github.create_branch": ToolDefinition(
        name="github.create_branch",
        provider="github",
        operation="create_branch",
        description="Create a new branch from a given commit SHA",
        risk_level=RiskLevel.WRITE,
        required_args=["repo", "branch", "from_sha"],
    ),
    "github.list_pull_requests": ToolDefinition(
        name="github.list_pull_requests",
        provider="github",
        operation="list_pull_requests",
        description="List pull requests for a repository",
        risk_level=RiskLevel.READ,
        required_args=["repo"],
    ),
    "github.create_pull_request": ToolDefinition(
        name="github.create_pull_request",
        provider="github",
        operation="create_pull_request",
        description="Create a pull request",
        risk_level=RiskLevel.WRITE,
        required_args=["repo", "title", "head"],
    ),
    "github.get_pull_request": ToolDefinition(
        name="github.get_pull_request",
        provider="github",
        operation="get_pull_request",
        description="Get pull request details, mergeability, and CI status",
        risk_level=RiskLevel.READ,
        required_args=["repo", "number"],
    ),
    "github.merge_pull_request": ToolDefinition(
        name="github.merge_pull_request",
        provider="github",
        operation="merge_pull_request",
        description="Merge a pull request (DESTRUCTIVE — requires approval)",
        risk_level=RiskLevel.DESTRUCTIVE,
        required_args=["repo", "number"],
    ),
    "github.list_checks": ToolDefinition(
        name="github.list_checks",
        provider="github",
        operation="list_checks",
        description="List CI check runs for a commit SHA or branch ref",
        risk_level=RiskLevel.READ,
        required_args=["repo", "ref"],
    ),
    "github.list_workflow_runs": ToolDefinition(
        name="github.list_workflow_runs",
        provider="github",
        operation="list_workflow_runs",
        description="List GitHub Actions workflow runs for a repository",
        risk_level=RiskLevel.READ,
        required_args=["repo"],
    ),
    "github.create_issue": ToolDefinition(
        name="github.create_issue",
        provider="github",
        operation="create_issue",
        description="Create a GitHub issue",
        risk_level=RiskLevel.WRITE,
        required_args=["repo", "title"],
    ),
    "github.get_deployment_status": ToolDefinition(
        name="github.get_deployment_status",
        provider="github",
        operation="get_deployment_status",
        description="Read GitHub Deployments API — latest deployment state and SHA",
        risk_level=RiskLevel.READ,
        required_args=["repo"],
    ),
}


def _register_github_tools() -> None:
    registry = get_tool_registry()
    for defn in GITHUB_TOOLS.values():
        registry.register(defn)
    # Register functions in the gateway-level ALL_TOOLS dict (no circular import)
    from app.engineering.tools.gateway import ALL_TOOLS
    for name, fn in _TOOL_FNS.items():
        ALL_TOOLS[name] = fn


_register_github_tools()
