/**
 * Assistant actions (M4) — proposals the user confirms on a card.
 *
 * The model may propose `[[action:<name> {json}]]` (catalogue in
 * app/core/ai/navigation.py). Nothing runs from the model's text: this module
 * only parses and validates a proposal against a strict allow-list. The card
 * then calls the normal, authenticated API with the user's own session, so
 * every server-side permission, org-membership and quota check still applies.
 *
 * Deliberately absent: deleting, paying, sending messages/e-mails, settings,
 * billing and permission changes.
 */
export type AssistantAction =
  | { kind: "create_task"; title: string; priority: "low" | "medium" | "high"; due_date?: string; notes?: string }
  | { kind: "create_lead"; name: string; source?: string; email?: string; phone?: string };

export const MAX_ACTIONS = 3;
const ACTION_MARKER = /\[\[\s*action\s*:\s*([a-z_]+)\s+(\{[^\n]*?\})\s*\]\]/gi;

function str(v: unknown, max: number): string | undefined {
  if (typeof v !== "string") return undefined;
  const s = v.replace(/\s+/g, " ").trim();
  return s ? s.slice(0, max) : undefined;
}

/** Validates one proposal; returns null for anything not on the allow-list. */
export function validateAction(kind: string, raw: unknown): AssistantAction | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const o = raw as Record<string, unknown>;
  if (kind === "create_task") {
    const title = str(o.title, 300);
    if (!title) return null;
    const priority = o.priority === "low" || o.priority === "high" ? o.priority : "medium";
    const due = str(o.due_date, 10);
    const notes = str(o.notes, 2000);
    return {
      kind, title, priority,
      ...(due && /^\d{4}-\d{2}-\d{2}$/.test(due) && !Number.isNaN(Date.parse(due)) ? { due_date: due } : {}),
      ...(notes ? { notes } : {}),
    };
  }
  if (kind === "create_lead") {
    const name = str(o.name, 200);
    if (!name) return null;
    const email = str(o.email, 320);
    const phone = str(o.phone, 30);
    const source = str(o.source, 100);
    return {
      kind, name,
      ...(source ? { source } : {}),
      ...(email && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) ? { email } : {}),
      ...(phone && /^\+?[\d\s()-]{6,30}$/.test(phone) ? { phone } : {}),
    };
  }
  return null;
}

/** Removes action markers from text and returns valid proposals (max 3). */
export function extractActions(content: string): { text: string; actions: AssistantAction[] } {
  const actions: AssistantAction[] = [];
  const text = content.replace(ACTION_MARKER, (_m, kind: string, json: string) => {
    if (actions.length >= MAX_ACTIONS) return "";
    try {
      const action = validateAction(kind.toLowerCase(), JSON.parse(json));
      if (action) actions.push(action);
    } catch { /* malformed JSON: drop the marker */ }
    return "";
  });
  return { text, actions };
}

/** Stable key for "already done" bookkeeping across reloads. */
export function actionKey(messageContent: string, index: number): string {
  let h = 0;
  for (let i = 0; i < messageContent.length; i++) h = (h * 31 + messageContent.charCodeAt(i)) | 0;
  return `flow-assistant-action:${h}:${index}`;
}
