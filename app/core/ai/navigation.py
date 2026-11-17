"""Page catalog the Flow assistant may point users to (M2: navigation only).

The assistant cannot act on the platform. It may *suggest* opening a page by
ending its reply with ``[[open:<page-id>]]`` markers; the web client turns
each known id into a button the user clicks. Unknown ids are ignored by the
client, so this list only has to stay a subset of the client's routes
(``src/renderer/shared/utils/assistantNav.ts``).
"""
from __future__ import annotations

PAGES: dict[str, str] = {
    "home": "Dashboard: overview, today's tasks and quick actions",
    "ai": "My AI Assistant: chat, agents, projects and plans",
    "new-project": "Start a new project",
    "leads": "Leads: capture, review and follow up with potential customers",
    "automation": "Automations and workflows",
    "social": "Marketing and social media posts",
    "app-builder": "Build an app with AI",
    "design": "Design Studio: logos, images and visual designs",
    "dev": "Developer workspace: write and run code",
    "agentos": "Agents: create and manage AI agents",
    "marketplace": "Templates marketplace",
    "plugins": "Plugins and add-on packages",
    "integrations": "Integrations with external services",
    "runs": "Run history of automations and agents",
    "training": "Training Studio: courses and lessons",
    "study-library": "Visual study library (lessons explained visually)",
    "careers": "Careers assistant: CVs and job search",
    "business-lab": "Business lab: business ideas and plans",
    "saas-factory": "SaaS factory: generate SaaS products",
    "discover": "Discover: explore content and creators",
    "feed": "Flow feed",
    "devices": "Devices: connected devices and device advisor",
    "teams": "Teams and members",
    "organizations": "Organizations",
    "billing": "Billing, plan and invoices",
    "settings": "Settings: account, language, API keys, security",
    "ai-routing": "AI gateway and model routing",
    "observability": "Observability: metrics, traces and logs",
    "sandbox": "Logs sandbox",
}

MAX_SUGGESTIONS = 2


def navigation_system_prompt() -> str:
    catalog = "\n".join(f"- {pid}: {desc}" for pid, desc in PAGES.items())
    return (
        "You are the Flow platform assistant. You can point the user to any page of "
        "the platform, but you cannot open pages, click, change settings or take any "
        "action yourself.\n"
        "When the user asks to go to, open or find a page, or when a page would clearly "
        "help with their request, end your reply with one marker per page on its own "
        f"line, at most {MAX_SUGGESTIONS}, exactly like: [[open:settings]]\n"
        "The user sees each marker as a button and decides whether to click it. Never "
        "say you opened a page. Only use page ids from this list:\n"
        f"{catalog}\n"
        "Reply in the user's language."
    )


def with_navigation(system: str | None) -> str:
    nav = navigation_system_prompt()
    return f"{system}\n\n{nav}" if system else nav
