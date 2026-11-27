/**
 * What the chat keeps across a page refresh (FE-02).
 *
 * - The open project + conversation, per tab (sessionStorage): a refresh
 *   reopens the same conversation, a new tab starts fresh.
 * - Unsent drafts, per project + conversation (localStorage): text typed but
 *   not sent survives a refresh, a crash or a closed tab.
 *
 * Storage can be unavailable (private modes, quota); every access is
 * guarded and the chat simply works without persistence then.
 */
const SESSION_KEY = "flow.chat.session.v1";
const DRAFT_PREFIX = "flow.chat.draft.v1:";
const MAX_DRAFT_CHARS = 20_000;

export type ChatSession = { projectId: string; activeConv: string | null };

export function draftScope(projectId: string, conv: string | null): string {
  return `${projectId}:${conv ?? "new"}`;
}

export function readSession(): ChatSession | null {
  try {
    const v: unknown = JSON.parse(sessionStorage.getItem(SESSION_KEY) ?? "null");
    if (v && typeof v === "object" && typeof (v as ChatSession).projectId === "string") {
      const conv = (v as ChatSession).activeConv;
      return { projectId: (v as ChatSession).projectId, activeConv: typeof conv === "string" ? conv : null };
    }
  } catch { /* unavailable or corrupt: start fresh */ }
  return null;
}

export function writeSession(s: ChatSession): void {
  try { sessionStorage.setItem(SESSION_KEY, JSON.stringify(s)); } catch { /* unavailable */ }
}

export function readDraft(scope: string): string {
  try { return localStorage.getItem(DRAFT_PREFIX + scope) ?? ""; } catch { return ""; }
}

export function writeDraft(scope: string, text: string): void {
  try {
    if (text.trim()) localStorage.setItem(DRAFT_PREFIX + scope, text.slice(0, MAX_DRAFT_CHARS));
    else localStorage.removeItem(DRAFT_PREFIX + scope);
  } catch { /* unavailable or full: keep the draft in memory only */ }
}
