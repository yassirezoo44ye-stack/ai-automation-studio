"""
SearchAgent tests (app/agents/builtin/search_agent.py) — Manus M5: web
search AI tool. Mirrors test_groq_provider.py's httpx-mocking convention.

No live network calls — BRAVE_SEARCH_API_KEY is never read from a real
environment here except where explicitly patched.
"""
from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("SESSION_SECRET", "test-secret-for-unit-tests-do-not-use-in-prod")


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _ctx(args: str, *, input_: str = ""):
    from app.agents.base import AgentContext
    return AgentContext(input=input_ or args, args=args, kernel=None, memory=None, run_id="r1")


class TestSearchAgentConfiguration:
    def test_no_query_fails_without_network_call(self):
        from app.agents.builtin.search_agent import SearchAgent
        with patch("httpx.AsyncClient.get") as fake_get:
            result = run(SearchAgent().execute(_ctx("")))
        assert result.success is False
        assert "query" in result.output.lower()
        fake_get.assert_not_called()

    def test_missing_api_key_fails_gracefully_without_network_call(self):
        from app.agents.builtin.search_agent import SearchAgent
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("BRAVE_SEARCH_API_KEY", None)
            with patch("httpx.AsyncClient.get") as fake_get:
                result = run(SearchAgent().execute(_ctx("python tutorials")))
        assert result.success is False
        assert "BRAVE_SEARCH_API_KEY" in result.output
        fake_get.assert_not_called()

    def test_permissions_declare_network_access(self):
        from app.agents.builtin.search_agent import SearchAgent
        assert SearchAgent().permissions.can_access_network is True


class TestSearchAgentExecution:
    def test_successful_search_parses_results(self):
        from app.agents.builtin.search_agent import SearchAgent

        fake_response = MagicMock()
        fake_response.raise_for_status = MagicMock()
        fake_response.json = MagicMock(return_value={
            "web": {"results": [
                {"title": "Result A", "url": "https://a.example", "description": "desc a"},
                {"title": "Result B", "url": "https://b.example", "description": "desc b"},
            ]},
        })

        with patch.dict(os.environ, {"BRAVE_SEARCH_API_KEY": "test-key"}), \
             patch("httpx.AsyncClient.get", new=AsyncMock(return_value=fake_response)), \
             patch("app.agents.liveness.publish_step", AsyncMock()):
            result = run(SearchAgent().execute(_ctx("python tutorials")))

        assert result.success is True
        assert result.data["query"] == "python tutorials"
        assert len(result.data["results"]) == 2
        assert result.data["results"][0]["url"] == "https://a.example"

    def test_no_results_still_succeeds(self):
        from app.agents.builtin.search_agent import SearchAgent

        fake_response = MagicMock()
        fake_response.raise_for_status = MagicMock()
        fake_response.json = MagicMock(return_value={"web": {"results": []}})

        with patch.dict(os.environ, {"BRAVE_SEARCH_API_KEY": "test-key"}), \
             patch("httpx.AsyncClient.get", new=AsyncMock(return_value=fake_response)), \
             patch("app.agents.liveness.publish_step", AsyncMock()):
            result = run(SearchAgent().execute(_ctx("a query with no results")))

        assert result.success is True
        assert result.data["results"] == []

    def test_http_error_fails_without_raising(self):
        from app.agents.builtin.search_agent import SearchAgent

        with patch.dict(os.environ, {"BRAVE_SEARCH_API_KEY": "test-key"}), \
             patch("httpx.AsyncClient.get", new=AsyncMock(side_effect=__import__("httpx").ConnectError("boom"))), \
             patch("app.agents.liveness.publish_step", AsyncMock()):
            result = run(SearchAgent().execute(_ctx("python tutorials")))  # must not raise

        assert result.success is False
        assert "Search request failed" in result.output

    def test_narrates_the_search_live(self):
        from app.agents.builtin.search_agent import SearchAgent

        fake_response = MagicMock()
        fake_response.raise_for_status = MagicMock()
        fake_response.json = MagicMock(return_value={
            "web": {"results": [{"title": "R", "url": "https://x.example", "description": ""}]},
        })

        fake_publish = AsyncMock()
        with patch.dict(os.environ, {"BRAVE_SEARCH_API_KEY": "test-key"}), \
             patch("httpx.AsyncClient.get", new=AsyncMock(return_value=fake_response)), \
             patch("app.agents.liveness.publish_step", fake_publish):
            ctx = _ctx("python tutorials")
            ctx._agent_name_hint = "search"
            run(SearchAgent().execute(ctx))

        narrated = [c.args[2] for c in fake_publish.call_args_list]
        assert any("Searching the web" in n for n in narrated)
        assert any("Found" in n for n in narrated)


class TestSearchIntentRouting:
    def test_search_alias_resolves_to_search_intent_with_args(self):
        from app.agents.intent import IntentParser
        ir = IntentParser().parse("search python tutorials")
        assert ir.intent == "search"
        assert ir.args == "python tutorials"

    def test_lookup_alias_resolves_to_search(self):
        from app.agents.intent import IntentParser
        ir = IntentParser().parse("lookup weather in Cairo")
        assert ir.intent == "search"


class TestSearchAgentLoaderRegistration:
    def test_module_exposes_a_module_level_agent_instance(self):
        """app.agents.loader.load_all()'s _load_file() strategy for
        auto-registering a builtin agent — mirrors run_agent.py's `agent =
        RunAgent()` module-level instance."""
        import app.agents.builtin.search_agent as mod
        from app.agents.base import EvolvableAgent
        assert isinstance(mod.agent, EvolvableAgent)
        assert mod.agent.name == "search"
