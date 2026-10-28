/**
 * One-time hand-off of a question from another page (e.g. Home's "Ask Flow")
 * to My AI Assistant's chat input. Session-scoped; never throws when storage
 * is unavailable.
 */
const KEY = "flow_assistant_prompt";

export function handOffToAssistant(text: string): void {
  const q = text.trim();
  if (!q) return;
  try { sessionStorage.setItem(KEY, q); } catch { /* storage unavailable */ }
}

export function peekAssistantHandoff(): string {
  try { return sessionStorage.getItem(KEY) ?? ""; } catch { return ""; }
}

export function clearAssistantHandoff(): void {
  try { sessionStorage.removeItem(KEY); } catch { /* storage unavailable */ }
}
