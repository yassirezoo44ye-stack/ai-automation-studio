/**
 * Generic AI client — all calls go through /api/ai/*.
 * Zero provider imports. Zero hardcoded model strings.
 */
import { apiFetch, apiJSON, getToken, API } from "../../shared/utils/api";

import type {
  CompletionResponse,
  Conversation,
  ConversationMessage,
  InferenceRequest,
  PromptVersion,
  ProviderID,
  ProviderUsage,
  ToolSchema,
  UsageTotals,
} from "./types";

// ── Completion ────────────────────────────────────────────────────────────────

export async function complete(req: InferenceRequest): Promise<CompletionResponse> {
  return apiJSON<CompletionResponse>("/api/ai/complete", {
    method: "POST",
    body:   JSON.stringify(req),
  });
}

/** Returns the raw Response so the caller can consume SSE. */
export async function streamRaw(req: InferenceRequest): Promise<Response> {
  const res = await fetch(`${API}/api/ai/stream`, {
    method:  "POST",
    headers: { "Content-Type": "application/json", "X-Sub-Token": getToken() },
    body:    JSON.stringify(req),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`AI stream error ${res.status}: ${text}`);
  }
  return res;
}

// ── Conversations ─────────────────────────────────────────────────────────────

export async function createConversation(params: {
  title?:      string;
  project_id?: string;
  agent_id?:   string;
}): Promise<{ id: string; title: string }> {
  return apiJSON("/api/ai/conversations", {
    method: "POST",
    body:   JSON.stringify(params),
  });
}

export async function listConversations(limit = 50): Promise<Conversation[]> {
  return apiJSON<Conversation[]>(`/api/ai/conversations?limit=${limit}`);
}

export async function getMessages(conversationId: string): Promise<ConversationMessage[]> {
  return apiJSON<ConversationMessage[]>(`/api/ai/conversations/${conversationId}/messages`);
}

export async function deleteConversation(conversationId: string): Promise<void> {
  // 204 No Content — apiJSON/parseJSON would throw trying to JSON.parse an
  // empty body, so this hits apiFetch directly and only checks .ok.
  const res = await apiFetch(`/api/ai/conversations/${conversationId}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`Failed to delete conversation: HTTP ${res.status}`);
}

// ── Providers ─────────────────────────────────────────────────────────────────

export async function listProviders(): Promise<{
  available: ProviderID[];
  default:   ProviderID | null;
  all:       ProviderID[];
}> {
  return apiJSON("/api/ai/providers");
}

// ── Usage / cost tracking ─────────────────────────────────────────────────────

export async function getUsageTotals(since?: string): Promise<UsageTotals> {
  const qs = since ? `?since=${encodeURIComponent(since)}` : "";
  return apiJSON<UsageTotals>(`/api/ai/usage${qs}`);
}

export async function getUsageByProvider(since?: string): Promise<ProviderUsage[]> {
  const qs = since ? `?since=${encodeURIComponent(since)}` : "";
  return apiJSON<ProviderUsage[]>(`/api/ai/usage/providers${qs}`);
}

// ── Memory ────────────────────────────────────────────────────────────────────

export async function storeMemory(params: {
  content:          string;
  importance?:      number;
  conversation_id?: string;
}): Promise<{ id: string }> {
  return apiJSON("/api/ai/memory", { method: "POST", body: JSON.stringify(params) });
}

export async function recallMemory(limit = 10): Promise<{ items: string[] }> {
  return apiJSON(`/api/ai/memory?limit=${limit}`);
}

export async function deleteMemoryItem(id: string): Promise<void> {
  // 204 No Content — see deleteConversation's comment above.
  const res = await apiFetch(`/api/ai/memory/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`Failed to delete memory item: HTTP ${res.status}`);
}

// ── Prompts ───────────────────────────────────────────────────────────────────

export async function createPrompt(params: {
  name:           string;
  slug:           string;
  description?:   string;
  system?:        string;
  user_template?: string;
  variables?:     string[];
}): Promise<{ id: string; slug: string }> {
  return apiJSON("/api/ai/prompts", { method: "POST", body: JSON.stringify(params) });
}

export async function publishPromptVersion(
  promptId: string,
  params: {
    system?:        string;
    user_template?: string;
    variables?:     string[];
  },
): Promise<{ prompt_id: string; version: number }> {
  return apiJSON(`/api/ai/prompts/${promptId}/versions`, {
    method: "POST",
    body:   JSON.stringify(params),
  });
}

export async function listPromptVersions(promptId: string): Promise<PromptVersion[]> {
  return apiJSON<PromptVersion[]>(`/api/ai/prompts/${promptId}/versions`);
}

export async function getActivePromptVersion(promptId: string): Promise<PromptVersion> {
  return apiJSON<PromptVersion>(`/api/ai/prompts/${promptId}/active`);
}

// ── Tools ─────────────────────────────────────────────────────────────────────

export async function listTools(): Promise<ToolSchema[]> {
  return apiJSON<ToolSchema[]>("/api/ai/tools");
}
