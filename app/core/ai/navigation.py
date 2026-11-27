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
        "action yourself. You may only PROPOSE the actions listed below; the user "
        "confirms each one on a card before anything happens.\n"
        "When the user asks to go to, open or find a page, or when a page would clearly "
        "help with their request, end your reply with one marker per page on its own "
        f"line, at most {MAX_SUGGESTIONS}, exactly like: [[open:settings]]\n"
        "The user sees each marker as a button and decides whether to click it. Never "
        "say you opened a page. Only use page ids from this list:\n"
        f"{catalog}\n"
        f"{actions_prompt()}\n"
        "Reply in the user's language."
    )


ACTIONS: dict[str, str] = {
    "create_task": '{"title": str (required), "priority": "low"|"medium"|"high", '
                   '"due_date": "YYYY-MM-DD" (optional), "notes": str (optional)}',
    "create_lead": '{"name": str (required), "source": str (optional), '
                   '"email": str (optional), "phone": str (optional)}',
    "update_task_status": '{"id": task id from <workspace-data> (required), '
                          '"status": "pending"|"in_progress"|"done"}',
    "update_lead_status": '{"id": lead id from <workspace-data> (required), '
                          '"status": "new"|"qualified"|"contacted"|"won"|"lost"}',
}


def actions_prompt() -> str:
    lines = "\n".join(f"- {name}: {schema}" for name, schema in ACTIONS.items())
    return (
        "Proposable actions (only when the user clearly asks to create, add, or change "
        "the status of something; at most 3 per reply; never invent e-mails or phone "
        "numbers the user did not give; for a status change copy the id exactly from "
        "<workspace-data> and never guess one; if the item is not listed there, say so "
        "and point to its page instead):\n"
        f"{lines}\n"
        'Propose one on its own line exactly like: [[action:create_task {"title": "Call the supplier", "priority": "high"}]]\n'
        "The JSON must be valid and on one line. Never say an action is done: say "
        "the user can confirm it on the card. Deleting, paying, sending messages or "
        "e-mails, changing settings, billing or permissions are NOT possible; explain "
        "where the user can do them instead."
    )


def with_navigation(system: str | None) -> str:
    nav = navigation_system_prompt()
    return f"{system}\n\n{nav}" if system else nav
