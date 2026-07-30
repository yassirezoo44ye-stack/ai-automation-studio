"""Browser agent — page navigation + content/screenshot extraction via
Playwright.

Requires the `playwright` package AND a downloaded Chromium binary
(`pip install playwright && playwright install chromium` — see
requirements.txt for the package; the browser binary is a separate,
~300MB download that must be run once per deployment target). Neither is
imported at module load time, so this module always imports cleanly even
when Playwright isn't installed — execute() reports a clear, actionable
failure instead of crashing, matching every other optional-dependency
agent in this file (search_agent.py's BRAVE_SEARCH_API_KEY,
image_agent.py's OPENAI_API_KEY).

Every request the page issues — not just the initial URL — is validated
by app.core.ssrf_guard.assert_public_url() before it's allowed through, via
a Playwright page.route() interceptor. A single upfront check on the
navigation string isn't enough: Playwright is a full browser, so it
follows HTTP redirects and executes the page's JavaScript, which can
issue its own fetch()/XHR calls, load <iframe>/<img> subresources, or
navigate again — any of which can point at an internal host with no
redirect needed on the attacker's part. The interceptor re-validates
every one of those, at the moment they're actually requested (which also
re-resolves DNS each time, closing most of the TOCTOU window a one-shot
check before launching the browser would leave open).
"""
from __future__ import annotations

import asyncio
import logging
import uuid

from app.agents import deliverables
from app.agents.base import AgentContext, AgentPermissions, AgentResult, EvolvableAgent
from app.core.config import WORKSPACES
from app.core.ssrf_guard import UnsafeUrlError, assert_public_url

log = logging.getLogger(__name__)

_MAX_TEXT_CHARS = 4000
_NAV_TIMEOUT_MS = 20_000
_SCREENSHOT_KEYWORDS = {"screenshot", "shot", "image", "picture"}


async def _guard_route(route, request, blocked: list[str]) -> None:
    """page.route() handler — runs for the main navigation, every
    redirect, and every subresource request this page issues. Aborts
    anything that fails the same public-reachability check the initial
    URL was validated against. assert_public_url() does blocking DNS
    resolution (socket.getaddrinfo) — offloaded to a thread so it doesn't
    stall the event loop across a page with many subresources."""
    try:
        await asyncio.to_thread(assert_public_url, request.url)
    except UnsafeUrlError:
        blocked.append(request.url)
        log.warning("browser agent blocked a request to a non-public URL: %s", request.url)
        await route.abort()
        return
    await route.continue_()


def _normalize_url(raw: str) -> str:
    if not raw.startswith(("http://", "https://")):
        return "https://" + raw
    return raw


class BrowserAgent(EvolvableAgent):
    name        = "browser"
    description = "Visit a URL and extract page content or a screenshot (Playwright)"
    group       = "research"

    @property
    def permissions(self) -> AgentPermissions:
        return AgentPermissions(
            can_access_network=True, can_write_filesystem=True,
            max_execution_seconds=45.0,
        )

    async def execute(self, ctx: AgentContext) -> AgentResult:
        raw = ctx.args.strip() or ctx.input.strip()
        if not raw:
            return AgentResult.fail(self.name, "No URL. Usage: browser <url> [screenshot]")

        parts = raw.split()
        url = _normalize_url(parts[0])
        want_screenshot = len(parts) > 1 and parts[1].lower() in _SCREENSHOT_KEYWORDS

        try:
            assert_public_url(url)
        except UnsafeUrlError as exc:
            return AgentResult.fail(self.name, f"Refused to visit URL: {exc}", data={"url": url})

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return AgentResult.fail(
                self.name,
                "Browser automation isn't installed — run "
                "`pip install playwright && playwright install chromium` to enable it.",
                data={"url": url},
            )

        await ctx.step(f"Opening {url}", "terminal")

        blocked: list[str] = []
        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch()
                try:
                    page = await browser.new_page()
                    await page.route("**/*", lambda route, request: _guard_route(route, request, blocked))
                    await page.goto(url, timeout=_NAV_TIMEOUT_MS, wait_until="domcontentloaded")
                    title = await page.title()

                    result_data: dict = {"url": url, "title": title}
                    output = f"{title or url}\n"

                    if want_screenshot:
                        await ctx.step("Capturing screenshot", "file")
                        out_dir = WORKSPACES / "screenshots"
                        out_dir.mkdir(parents=True, exist_ok=True)
                        shot_path = out_dir / f"screenshot_{uuid.uuid4().hex[:8]}.png"
                        await page.screenshot(path=str(shot_path))

                        deliverable_id = deliverables.register(
                            shot_path, run_id=ctx.run_id, agent=self.name,
                            label=shot_path.name, organization_id=ctx.organization_id,
                            user_id=ctx.user_id,
                        )
                        if deliverable_id:
                            result_data["deliverable_id"]    = deliverable_id
                            result_data["deliverable_label"] = shot_path.name
                            output += f"Screenshot: {shot_path.name}\n"
                    else:
                        text = (await page.inner_text("body")).strip()[:_MAX_TEXT_CHARS]
                        result_data["text"] = text
                        output += text

                    if blocked:
                        # Navigation itself succeeded — only subresources
                        # (e.g. a tracking pixel pointing at an internal
                        # host) were blocked. That's the guard working
                        # correctly, not a failure; just surface it.
                        result_data["blocked_non_public_requests"] = blocked

                    await ctx.step(f"Loaded {title or url}", "success")
                    return AgentResult.ok(self.name, output.strip(), data=result_data)
                finally:
                    await browser.close()
        except Exception as exc:
            if blocked:
                return AgentResult.fail(
                    self.name,
                    f"Refused to load a non-public URL reached via redirect/subresource: {blocked[0]}",
                    data={"url": url, "blocked": blocked},
                )
            return AgentResult.fail(self.name, f"Browser automation failed: {exc}", data={"url": url})

    def performance_hint(self) -> dict:
        return {"complexity": "high", "io_bound": True, "timeout_s": 45}


agent = BrowserAgent()
