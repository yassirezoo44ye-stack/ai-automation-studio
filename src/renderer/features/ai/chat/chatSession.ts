/**
 * Chat session helpers — pure, framework-free, unit-tested.
 *
 * - Session restore: which project/conversation was open, per user, so a
 *   reload reopens it (the server re-checks ownership; a stale or foreign id
 *   just 404s and is cleared).
 * - Drafts: unsent composer text, per user + project + conversation, kept
 *   apart from saved messages. A draft is cleared only once the server
 *   confirms the message was stored, so a failed send never loses it.
 * - Limits: one counting rule shared with the server (code points).
 * - SSE parsing and error description for the stream endpoint.
 *
 * Everything touching localStorage is wrapped: storage can be unavailable
 * (private mode, blocked site data) and the chat must still work without it.
 */

export const STORAGE_PREFIX = "flow.chat.";
const SESSION_KEY = (userId: string) => `${STORAGE_PREFIX}session.v1:${userId}`;
const DRAFT_KEY = (userId: string, projectId: string, convId: string | null) =>
  `${STORAGE_PREFIX}draft.v1:${userId}:${projectId}:${convId ?? "new"}`;

/** Fallback used only until GET /api/chat/limits answers. Must match the server default. */
export const DEFAULT_MAX_PROMPT_CHARS = 32_000;

export interface ChatLimits {
  maxPromptChars: number;
  warnAtChars: number;
}

export const DEFAULT_LIMITS: ChatLimits = {
  maxPromptChars: DEFAULT_MAX_PROMPT_CHARS,
  warnAtChars: Math.floor(DEFAULT_MAX_PROMPT_CHARS * 0.85),
};

export interface ChatSessionState {
  projectId: string;
  convId: string | null;
}

function safeGet(key: string): string | null {
  try { return localStorage.getItem(key); } catch { return null; }
}
function safeSet(key: string, value: string): void {
  try { localStorage.setItem(key, value); } catch { /* storage unavailable — non-fatal */ }
}
function safeRemove(key: string): void {
  try { localStorage.removeItem(key); } catch { /* non-fatal */ }
}

export function loadSession(userId: string | null | undefined): ChatSessionState {
  const fallback: ChatSessionState = { projectId: "demo", convId: null };
  if (!userId) return fallback;
  const raw = safeGet(SESSION_KEY(userId));
  if (!raw) return fallback;
  try {
    const v = JSON.parse(raw) as Partial<ChatSessionState>;
    return {
      projectId: typeof v.projectId === "string" && v.projectId ? v.projectId : "demo",
      convId: typeof v.convId === "string" && v.convId ? v.convId : null,
    };
  } catch {
    return fallback;
  }
}

export function saveSession(userId: string | null | undefined, s: ChatSessionState): void {
  if (!userId) return;
  safeSet(SESSION_KEY(userId), JSON.stringify(s));
}

export function getDraft(userId: string | null | undefined, projectId: string, convId: string | null): string {
  if (!userId) return "";
  return safeGet(DRAFT_KEY(userId, projectId, convId)) ?? "";
}

export function setDraft(userId: string | null | undefined, projectId: string, convId: string | null, text: string): void {
  if (!userId) return;
  if (text) safeSet(DRAFT_KEY(userId, projectId, convId), text);
  else safeRemove(DRAFT_KEY(userId, projectId, convId));
}

export function clearDraft(userId: string | null | undefined, projectId: string, convId: string | null): void {
  setDraft(userId, projectId, convId, "");
}

/** Remove every chat session/draft key — called on logout so a shared browser keeps nothing. */
export function clearAllChatStorage(): void {
  try {
    const doomed: string[] = [];
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k && k.startsWith(STORAGE_PREFIX)) doomed.push(k);
    }
    doomed.forEach(k => localStorage.removeItem(k));
  } catch { /* non-fatal */ }
}

/** Same counting rule as the server (Unicode code points, not UTF-16 units). */
export function countChars(text: string): number {
  let n = 0;
  for (const _ of text) n++;
  return n;
}

/**
 * Merge freshly loaded history over the local copy without losing what only
 * the client knows: the failure reason of a reply that just failed (the
 * server stores the status, not the provider's message). Matching is by
 * request id + role; everything else comes from the server.
 */
export function carryOverErrors<
  M extends { role: string; requestId?: string | null; status?: string; error?: string | null },
>(loaded: M[], local: M[]): M[] {
  const reasons = new Map<string, string>();
  for (const m of local) {
    if (m.requestId && m.error) reasons.set(`${m.requestId}:${m.role}`, m.error);
  }
  if (reasons.size === 0) return loaded;
  return loaded.map(m => {
    if (!m.requestId || m.error) return m;
    if (m.status !== "failed" && m.status !== "partial") return m;
    const reason = reasons.get(`${m.requestId}:${m.role}`);
    return reason ? { ...m, error: reason } : m;
  });
}

export type LimitState = "ok" | "warn" | "over";

export function limitState(count: number, limits: ChatLimits): LimitState {
  if (count > limits.maxPromptChars) return "over";
  if (count >= limits.warnAtChars) return "warn";
  return "ok";
}

export function parseLimits(raw: unknown): ChatLimits {
  const r = (raw ?? {}) as { max_prompt_chars?: unknown; warn_at_chars?: unknown };
  const max = typeof r.max_prompt_chars === "number" && r.max_prompt_chars > 0 ? r.max_prompt_chars : DEFAULT_MAX_PROMPT_CHARS;
  const warn = typeof r.warn_at_chars === "number" && r.warn_at_chars > 0 && r.warn_at_chars <= max
    ? r.warn_at_chars : Math.floor(max * 0.85);
  return { maxPromptChars: max, warnAtChars: warn };
}

// ── SSE ──────────────────────────────────────────────────────────────────────

export interface StreamEvent {
  type: string;
  [k: string]: unknown;
}

/**
 * Split a growing SSE buffer into complete `data:` events plus the unfinished
 * remainder. Malformed lines are skipped rather than aborting the stream —
 * one bad frame must not discard a reply that is otherwise arriving fine.
 */
export function parseSseBuffer(buffer: string): { events: StreamEvent[]; rest: string } {
  const lines = buffer.split("\n");
  const rest = lines.pop() ?? "";
  const events: StreamEvent[] = [];
  for (const line of lines) {
    if (!line.startsWith("data: ")) continue;
    try {
      const ev = JSON.parse(line.slice(6));
      if (ev && typeof ev.type === "string") events.push(ev as StreamEvent);
    } catch { /* skip malformed frame */ }
  }
  return { events, rest };
}

// ── Errors ───────────────────────────────────────────────────────────────────

export interface SendErrorInfo {
  /** The request was rejected before anything was stored — put the text back in the composer. */
  rejectedBeforeSave: boolean;
  /** Retrying the same request can help (network, 5xx, capacity). */
  retryable: boolean;
  message: string;
}

interface StructuredDetail { code?: string; message?: string; message_ar?: string; limit?: number; length?: number }

/**
 * Turn a non-OK response from /api/run/stream into something the UI can act
 * on. 413/422 are validation rejections (nothing stored, not retryable as-is);
 * 409 means another attempt of the same request is in flight; others retry.
 */
export function describeSendFailure(status: number, body: unknown, lang: string, fallback: string): SendErrorInfo {
  const detail = (body as { detail?: unknown } | null)?.detail;
  let message = fallback;
  if (detail && typeof detail === "object") {
    const d = detail as StructuredDetail;
    message = (lang.startsWith("ar") ? d.message_ar : d.message) ?? d.message ?? fallback;
  } else if (typeof detail === "string" && detail) {
    message = detail;
  }
  if (status === 413 || status === 422 || status === 400) {
    return { rejectedBeforeSave: true, retryable: false, message };
  }
  if (status === 401 || status === 403 || status === 404) {
    return { rejectedBeforeSave: true, retryable: false, message };
  }
  return { rejectedBeforeSave: false, retryable: true, message };
}
