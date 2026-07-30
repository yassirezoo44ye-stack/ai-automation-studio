"""
BrowserAgent tests (app/agents/builtin/browser_agent.py) — Manus M5:
browser automation AI tool. playwright.async_api.async_playwright is
mocked throughout — no real browser is launched, no real network calls.

The Python `playwright` package is installed in this environment (it's a
lightweight ~38MB wheel, unlike the Chromium binary `playwright install`
downloads separately) specifically so these tests can patch its real
import path rather than needing a fake sys.modules entry for the
happy-path tests.
"""
from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("SESSION_SECRET", "test-secret-for-unit-tests-do-not-use-in-prod")


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _ctx(args: str, *, organization_id=None):
    from app.agents.base import AgentContext
    return AgentContext(
        input=args, args=args, kernel=None, memory=None, run_id="r1",
        organization_id=organization_id,
    )


class _FakePage:
    def __init__(self, title="Example Domain", text="hello world", goto_error=None):
        self._title = title
        self._text = text
        self.goto = AsyncMock(side_effect=goto_error) if goto_error else AsyncMock()
        self.screenshot = AsyncMock()
        # execute() always registers a page.route("**/*", ...) interceptor
        # before navigating (SSRF guard on every request, not just the
        # initial URL) — capture the handler so tests can drive it directly.
        self.route = AsyncMock(side_effect=self._capture_route)
        self.route_handler = None

    async def _capture_route(self, _pattern, handler):
        self.route_handler = handler

    async def title(self):
        return self._title

    async def inner_text(self, _selector):
        return self._text


class _FakeBrowser:
    def __init__(self, page):
        self._page = page
        self.close = AsyncMock()

    async def new_page(self):
        return self._page


class _FakeChromium:
    def __init__(self, browser):
        self._browser = browser

    async def launch(self, **_kwargs):
        return self._browser


class _FakePlaywright:
    def __init__(self, browser):
        self.chromium = _FakeChromium(browser)


class _FakeAsyncPlaywrightCM:
    def __init__(self, pw):
        self._pw = pw

    async def __aenter__(self):
        return self._pw

    async def __aexit__(self, *_args):
        return False


def _patched_playwright(page):
    browser = _FakeBrowser(page)
    pw = _FakePlaywright(browser)
    cm = _FakeAsyncPlaywrightCM(pw)
    return patch("playwright.async_api.async_playwright", return_value=cm), browser


class TestBrowserAgentConfiguration:
    def test_no_url_fails_without_touching_playwright(self):
        from app.agents.builtin.browser_agent import BrowserAgent
        with patch("playwright.async_api.async_playwright") as fake_pw:
            result = run(BrowserAgent().execute(_ctx("")))
        assert result.success is False
        assert "URL" in result.output
        fake_pw.assert_not_called()

    def test_localhost_url_is_refused_without_touching_playwright(self):
        from app.agents.builtin.browser_agent import BrowserAgent
        with patch("playwright.async_api.async_playwright") as fake_pw:
            result = run(BrowserAgent().execute(_ctx("http://localhost:8000/admin")))
        assert result.success is False
        assert "Refused" in result.output
        fake_pw.assert_not_called()

    def test_cloud_metadata_ip_is_refused(self):
        from app.agents.builtin.browser_agent import BrowserAgent
        with patch("playwright.async_api.async_playwright") as fake_pw:
            result = run(BrowserAgent().execute(_ctx("http://169.254.169.254/latest/meta-data/")))
        assert result.success is False
        fake_pw.assert_not_called()

    def test_playwright_not_installed_fails_gracefully(self):
        from app.agents.builtin.browser_agent import BrowserAgent
        with patch.dict(sys.modules, {"playwright.async_api": None}):
            result = run(BrowserAgent().execute(_ctx("example.com")))  # must not raise
        assert result.success is False
        assert "playwright install" in result.output

    def test_permissions_declare_network_and_filesystem_write(self):
        from app.agents.builtin.browser_agent import BrowserAgent
        perms = BrowserAgent().permissions
        assert perms.can_access_network is True
        assert perms.can_write_filesystem is True

    def test_bare_hostname_gets_https_prefix(self):
        from app.agents.builtin.browser_agent import _normalize_url
        assert _normalize_url("example.com") == "https://example.com"
        assert _normalize_url("http://example.com") == "http://example.com"


class TestBrowserAgentExecution:
    def test_extracts_page_text_by_default(self):
        from app.agents.builtin.browser_agent import BrowserAgent
        page = _FakePage(title="Example Domain", text="Some visible page text")
        patcher, browser = _patched_playwright(page)

        with patcher, patch("app.agents.liveness.publish_step", AsyncMock()):
            result = run(BrowserAgent().execute(_ctx("example.com")))

        assert result.success is True
        assert result.data["title"] == "Example Domain"
        assert result.data["text"] == "Some visible page text"
        assert "deliverable_id" not in result.data
        browser.close.assert_awaited_once()

    def test_screenshot_keyword_registers_a_deliverable(self, tmp_path):
        from app.agents.builtin.browser_agent import BrowserAgent
        import app.agents.builtin.browser_agent as browser_agent_mod
        import app.agents.deliverables as deliverables

        page = _FakePage(title="Example Domain")
        # screenshot() writes nothing for real in this fake — write the
        # file ourselves so deliverables.register() finds a real path.
        async def fake_screenshot(path, **_kw):
            from pathlib import Path
            Path(path).write_bytes(b"\x89PNG\r\n\x1a\nfake")
        page.screenshot = AsyncMock(side_effect=fake_screenshot)
        patcher, browser = _patched_playwright(page)

        with patcher, \
             patch.object(browser_agent_mod, "WORKSPACES", tmp_path), \
             patch.object(deliverables, "WORKSPACES", tmp_path), \
             patch("app.agents.liveness.publish_step", AsyncMock()):
            result = run(BrowserAgent().execute(_ctx("example.com screenshot", organization_id="org-a")))

        assert result.success is True
        assert "deliverable_id" in result.data
        entry = deliverables.get(result.data["deliverable_id"])
        assert entry is not None
        assert entry["organization_id"] == "org-a"
        browser.close.assert_awaited_once()

    def test_navigation_failure_still_closes_the_browser(self):
        from app.agents.builtin.browser_agent import BrowserAgent
        page = _FakePage(goto_error=RuntimeError("net::ERR_CONNECTION_REFUSED"))
        patcher, browser = _patched_playwright(page)

        with patcher, patch("app.agents.liveness.publish_step", AsyncMock()):
            result = run(BrowserAgent().execute(_ctx("example.com")))  # must not raise

        assert result.success is False
        assert "Browser automation failed" in result.output
        browser.close.assert_awaited_once()

    def test_narrates_the_visit_live(self):
        from app.agents.builtin.browser_agent import BrowserAgent
        page = _FakePage(title="Example Domain", text="text")
        patcher, _browser = _patched_playwright(page)

        fake_publish = AsyncMock()
        with patcher, patch("app.agents.liveness.publish_step", fake_publish):
            ctx = _ctx("example.com")
            ctx._agent_name_hint = "browser"
            run(BrowserAgent().execute(ctx))

        narrated = [c.args[2] for c in fake_publish.call_args_list]
        assert any("Opening" in n for n in narrated)
        assert any("Loaded" in n for n in narrated)


class _FakeRoute:
    def __init__(self):
        self.abort = AsyncMock()
        self.continue_ = AsyncMock()


class _FakeRequest:
    def __init__(self, url: str):
        self.url = url


class TestGuardRoute:
    """Unit tests for _guard_route — the page.route() handler that
    re-validates every request (main nav, redirects, subresources) a
    browser page issues, not just the initial URL string."""

    def test_public_url_is_allowed_through(self):
        from app.agents.builtin.browser_agent import _guard_route
        route, request, blocked = _FakeRoute(), _FakeRequest("https://example.com/style.css"), []
        run(_guard_route(route, request, blocked))
        route.continue_.assert_awaited_once()
        route.abort.assert_not_called()
        assert blocked == []

    def test_private_ip_subresource_is_aborted_and_recorded(self):
        from app.agents.builtin.browser_agent import _guard_route
        route, request, blocked = _FakeRoute(), _FakeRequest("http://169.254.169.254/latest/meta-data/"), []
        run(_guard_route(route, request, blocked))
        route.abort.assert_awaited_once()
        route.continue_.assert_not_called()
        assert blocked == ["http://169.254.169.254/latest/meta-data/"]

    def test_localhost_redirect_target_is_aborted(self):
        from app.agents.builtin.browser_agent import _guard_route
        route, request, blocked = _FakeRoute(), _FakeRequest("http://localhost:5432/internal"), []
        run(_guard_route(route, request, blocked))
        route.abort.assert_awaited_once()
        assert blocked == ["http://localhost:5432/internal"]


class TestBrowserAgentExecutionRegistersRouteGuard:
    def test_execute_registers_an_interceptor_before_navigating(self):
        from app.agents.builtin.browser_agent import BrowserAgent
        page = _FakePage(title="Example Domain", text="text")
        patcher, _browser = _patched_playwright(page)

        with patcher, patch("app.agents.liveness.publish_step", AsyncMock()):
            run(BrowserAgent().execute(_ctx("example.com")))

        page.route.assert_awaited_once()
        assert page.route.call_args.args[0] == "**/*"
        assert page.route_handler is not None

    def test_blocked_subresource_surfaces_on_a_successful_navigation(self):
        """The interceptor blocking a tracking-pixel-style subresource
        (e.g. one pointed at cloud metadata) must not fail an otherwise
        successful page load — it's reported informationally instead."""
        from app.agents.builtin.browser_agent import BrowserAgent

        page = _FakePage(title="Example Domain", text="text")
        # Simulate the browser issuing a blocked subresource request as
        # part of navigating — drive it through the *real* handler execute()
        # registered via page.route(), so it shares execute()'s own
        # `blocked` list rather than a separate one.
        async def fake_goto(*_a, **_kw):
            await page.route_handler(_FakeRoute(), _FakeRequest("http://169.254.169.254/"))
        page.goto = AsyncMock(side_effect=fake_goto)
        patcher, _browser = _patched_playwright(page)

        with patcher, patch("app.agents.liveness.publish_step", AsyncMock()):
            result = run(BrowserAgent().execute(_ctx("example.com")))

        assert result.success is True
        assert result.data["blocked_non_public_requests"] == ["http://169.254.169.254/"]


class TestBrowserIntentRouting:
    def test_browser_alias_resolves_with_args(self):
        from app.agents.intent import IntentParser
        ir = IntentParser().parse("browser example.com")
        assert ir.intent == "browser"
        assert ir.args == "example.com"

    def test_visit_alias_resolves_to_browser(self):
        from app.agents.intent import IntentParser
        ir = IntentParser().parse("visit example.com")
        assert ir.intent == "browser"


class TestBrowserAgentLoaderRegistration:
    def test_module_exposes_a_module_level_agent_instance(self):
        import app.agents.builtin.browser_agent as mod
        from app.agents.base import EvolvableAgent
        assert isinstance(mod.agent, EvolvableAgent)
        assert mod.agent.name == "browser"
