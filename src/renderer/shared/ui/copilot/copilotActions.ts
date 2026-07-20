/**
 * Deterministic, keyword-based action matching for the Copilot — deliberately
 * NOT AI-driven and deliberately limited to safe, reversible NAVIGATION only.
 *
 * Scope note: the "Guided UX" spec asked for natural-language actions like
 * "deploy my project", "rollback deployment", "backup database" — those are
 * destructive/high-consequence operations and are intentionally NOT wired
 * here. Only "take me to X" style navigation is implemented for real; the
 * rest is catalogued as a follow-up requiring explicit confirmation UX
 * (see the phase report).
 */
import type { CopilotAction } from "../../../contexts/copilot";

const NAV_KEYWORDS: { page: string; label: string; keywords: string[] }[] = [
  { page: "billing",       label: "Open Billing",       keywords: ["billing", "invoice", "invoices", "subscription", "payment"] },
  { page: "settings",      label: "Open Settings",      keywords: ["settings", "preferences", "configuration"] },
  { page: "marketplace",   label: "Open Marketplace",   keywords: ["marketplace", "plugins store", "browse plugins"] },
  { page: "teams",         label: "Open Teams",         keywords: ["team", "teams", "members", "invite"] },
  { page: "organizations", label: "Open Organizations", keywords: ["organization", "organizations", "org switch"] },
  { page: "automation",    label: "Open Workflows",     keywords: ["workflow", "workflows", "automation"] },
  { page: "agentos",       label: "Open AgentOS",       keywords: ["agent os", "agentos", "self-evolving"] },
  { page: "ai-routing",    label: "Open AI Routing",    keywords: ["ai routing", "model routing", "cost routing"] },
  { page: "observability", label: "Open Observability", keywords: ["observability", "metrics", "traces", "logs"] },
  { page: "sandbox",       label: "Open Sandbox",       keywords: ["sandbox"] },
  { page: "plugins",       label: "Open Plugins",       keywords: ["plugin", "plugins"] },
  { page: "dev",           label: "Open Dev",           keywords: ["build", "dev workspace", "run code"] },
  { page: "design",        label: "Open Design",        keywords: ["design studio", "design"] },
  { page: "ai",            label: "Open AI Chat",       keywords: ["chat", "conversation", "my agents"] },
  { page: "home",          label: "Open Dashboard",     keywords: ["dashboard", "home", "overview"] },
];

const OPEN_VERBS = /\b(open|go to|show|take me to|navigate to)\b/i;

/** Returns a single best-guess navigation suggestion, or null if nothing matches confidently. */
export function matchCopilotAction(input: string): CopilotAction | null {
  const text = input.toLowerCase().trim();
  if (!text) return null;
  const hasVerb = OPEN_VERBS.test(text);
  for (const entry of NAV_KEYWORDS) {
    if (entry.keywords.some(k => text.includes(k))) {
      // Require an explicit "open/show/go to" verb OR the message being
      // just the keyword itself — avoids false-positives on messages that
      // merely mention a page name in passing ("why is billing confusing?").
      if (hasVerb || text.split(/\s+/).length <= 3) {
        return { label: entry.label, page: entry.page };
      }
    }
  }
  return null;
}
