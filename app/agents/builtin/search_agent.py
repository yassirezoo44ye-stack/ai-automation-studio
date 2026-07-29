"""Search agent — web search via the Brave Search API.

Set BRAVE_SEARCH_API_KEY to enable (https://brave.com/search/api/). Absent
key never crashes the agent — it returns a clear, actionable failure
result instead, matching the rest of this codebase's "graceful when a key
is missing" convention (see app/core/ai/registry/registry.py's get()).
"""
from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from app.agents.base import AgentContext, AgentPermissions, AgentResult, EvolvableAgent

log = logging.getLogger(__name__)

_SEARCH_URL   = "https://api.search.brave.com/res/v1/web/search"
_ENV_KEY      = "BRAVE_SEARCH_API_KEY"
_MAX_RESULTS  = 5


def _extract_results(data: dict[str, Any]) -> list[dict[str, str]]:
    web   = data.get("web", {}) if isinstance(data, dict) else {}
    items = web.get("results", []) if isinstance(web, dict) else []
    return [
        {
            "title":       item.get("title", ""),
            "url":         item.get("url", ""),
            "description": item.get("description", ""),
        }
        for item in items[:_MAX_RESULTS]
    ]


class SearchAgent(EvolvableAgent):
    name        = "search"
    description = "Web search via the Brave Search API"
    group       = "research"

    @property
    def permissions(self) -> AgentPermissions:
        return AgentPermissions(can_access_network=True)

    async def execute(self, ctx: AgentContext) -> AgentResult:
        query = ctx.args.strip() or ctx.input.strip()
        if not query:
            return AgentResult.fail(self.name, "No search query. Usage: search <query>")

        api_key = os.getenv(_ENV_KEY, "")
        if not api_key:
            return AgentResult.fail(
                self.name,
                f"Web search isn't configured — set {_ENV_KEY} to enable it "
                "(https://brave.com/search/api/).",
                data={"query": query},
            )

        await ctx.step(f"Searching the web: {query!r}", "info")

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    _SEARCH_URL,
                    params={"q": query, "count": _MAX_RESULTS},
                    headers={"X-Subscription-Token": api_key, "Accept": "application/json"},
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as exc:
            return AgentResult.fail(
                self.name, f"Search request failed: HTTP {exc.response.status_code}",
                data={"query": query},
            )
        except httpx.HTTPError as exc:
            return AgentResult.fail(self.name, f"Search request failed: {exc}", data={"query": query})

        results = _extract_results(data)
        if not results:
            await ctx.step("No results found", "info")
            return AgentResult.ok(
                self.name, f"No results for {query!r}",
                data={"query": query, "results": []},
            )

        await ctx.step(f"Found {len(results)} result(s)", "success")
        summary = "\n".join(f"- {r['title']}: {r['url']}" for r in results)
        return AgentResult.ok(
            self.name,
            f"{len(results)} result(s) for {query!r}:\n{summary}",
            data={"query": query, "results": results},
        )

    def performance_hint(self) -> dict:
        return {"complexity": "low", "io_bound": True, "timeout_s": 20}


agent = SearchAgent()
