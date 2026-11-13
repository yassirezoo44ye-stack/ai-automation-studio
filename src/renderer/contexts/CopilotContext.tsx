/**
 * CopilotContext — persistent, page-aware AI assistant.
 *
 * The floating copilot deliberately reuses the legacy /api/run/stream endpoint
 * and its conversations/messages tables, just like ChatTab. It does not read
 * or write ai_conversations/ai_messages.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { useAppContext } from "./app";
import { useOrg } from "./OrgContext";
import { apiFetch } from "../shared/utils/api";
import { CopilotContext, type CopilotConversation, type CopilotMessage, type CopilotAction } from "./copilot";
import { matchCopilotAction } from "../shared/ui/copilot/copilotActions";
import type { Page } from "../shared/types";

import { validatePrompt, chatHttpFailure } from "../shared/utils/chatReliability";
const COPILOT_PROJECT = "copilot";

const PAGE_LABELS: Record<Page, string> = {
  home: "Dashboard", ai: "AI Chat", dev: "Dev Workspace", design: "Design Studio",
  automation: "Workflows", social: "Social", settings: "Settings", agentos: "AgentOS",
  marketplace: "Marketplace", organizations: "Organizations", teams: "Teams",
  billing: "Billing", plugins: "Plugins", sandbox: "Sandbox", "ai-routing": "AI Routing",
  observability: "Observability", "app-builder": "App Builder", runs: "Runs",
  integrations: "Integrations", training: "Training Studio", "business-lab": "Business Lab",
  devices: "Devices", discover: "Discover", feed: "Flow Feed", careers: "Career Assistant",
  "study-library": "Visual Study Library", leads: "Leads", "saas-factory": "SaaS Factory",
  "new-project": "New Project",
};

async function jsonOrThrow<T>(response: Response): Promise<T> {
  if (!response.ok) throw new Error(`Request failed (${response.status})`);
  return response.json() as Promise<T>;
}

async function loadCopilotConversations(): Promise<CopilotConversation[]> {
  const response = await apiFetch(`/api/conversations?project_id=${encodeURIComponent(COPILOT_PROJECT)}`);
  return jsonOrThrow<CopilotConversation[]>(response);
}

export function CopilotProvider({ children }: { children: ReactNode }) {
  const { page } = useAppContext();
  const { currentOrg } = useOrg();
  const [open, setOpen] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<CopilotMessage[]>([]);
  const [conversations, setConversations] = useState<CopilotConversation[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [suggestedAction, setSuggestedAction] = useState<CopilotAction | null>(null);

  const conversationIdRef = useRef<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const requestInFlightRef = useRef(false);
  const generationRef = useRef(0);
  const historyRequestRef = useRef(0);
  // Prevent a delayed initial history request from claiming the UI after the
  // user has already started a fresh turn (before the server emits conv_id).
  const interactionRef = useRef(0);

  const refreshConversations = useCallback(async () => {
    const items = await loadCopilotConversations();
    setConversations(items);
    return items;
  }, []);

  // Load both the server-backed history rail and latest active conversation.
  // The endpoint scopes the list through the authenticated user's project;
  // message retrieval independently enforces conversation ownership.
  useEffect(() => {
    let mounted = true;
    const requestId = ++historyRequestRef.current;
    const interactionAtStart = interactionRef.current;
    void Promise.resolve().then(() => { if (mounted) setLoadingHistory(true); });
    void loadCopilotConversations().then(async items => {
      if (!mounted) return;
      setConversations(items);
      if (!mounted || requestId !== historyRequestRef.current || interactionRef.current !== interactionAtStart || !items.length) return;
      const first = items[0];
      const response = await apiFetch(`/api/conversations/${encodeURIComponent(first.id)}/messages`);
      const rows = await jsonOrThrow<{ id: string; role: string; content: string }[]>(response);
      if (!mounted || requestId !== historyRequestRef.current || interactionRef.current !== interactionAtStart || conversationIdRef.current) return;
      conversationIdRef.current = first.id;
      setConversationId(first.id);
      setMessages(rows.filter(m => m.role === "user" || m.role === "assistant")
        .map(m => ({ id: m.id, role: m.role as CopilotMessage["role"], content: m.content, status: "complete" })));
    }).catch(() => {
      // A failed history request must not block starting a fresh conversation.
    }).finally(() => {
      if (mounted && requestId === historyRequestRef.current) setLoadingHistory(false);
    });
    return () => { mounted = false; };
  }, []);

  const openConversation = useCallback(async (id: string) => {
    interactionRef.current += 1;
    if (requestInFlightRef.current) {
      generationRef.current += 1;
      abortRef.current?.abort();
      abortRef.current = null;
      requestInFlightRef.current = false;
      setStreaming(false);
    }
    const requestId = ++historyRequestRef.current;
    setLoadingHistory(true);
    setError(null);
    conversationIdRef.current = null;
    setConversationId(null);
    setMessages([]);
    try {
      const response = await apiFetch(`/api/conversations/${encodeURIComponent(id)}/messages`);
      const rows = await jsonOrThrow<{ id: string; role: string; content: string }[]>(response);
      if (requestId !== historyRequestRef.current) return;
      conversationIdRef.current = id;
      setConversationId(id);
      setMessages(rows.filter(m => m.role === "user" || m.role === "assistant")
        .map(m => ({ id: m.id, role: m.role as CopilotMessage["role"], content: m.content, status: "complete" })));
    } catch (err) {
      if (requestId === historyRequestRef.current) setError(err instanceof Error ? err.message : "Could not load this conversation.");
    } finally {
      if (requestId === historyRequestRef.current) setLoadingHistory(false);
    }
  }, []);

  const send = useCallback(async (text: string): Promise<boolean> => {
    const trimmed = text; // Preserve whitespace, code indentation and original line endings.
    if (!text.trim() || requestInFlightRef.current) return false;

    const pageLabel = PAGE_LABELS[page] ?? page;
    const contextLine = `[Context: the user is currently on the "${pageLabel}" page` +
      (currentOrg ? ` of the "${currentOrg.name}" organization` : "") +
      ` inside Flow. Answer helpfully and concisely; you may suggest which page to visit but cannot take actions yourself.]`;
    const promptWithContext = `${contextLine}\n\n${trimmed}`;
    const validation = validatePrompt(promptWithContext);
    if (validation) {
      setError(validation);
      return false;
    }

    interactionRef.current += 1;
    historyRequestRef.current += 1;
    setLoadingHistory(false);
    requestInFlightRef.current = true;
    setStreaming(true);
    const generation = ++generationRef.current;
    const userMsg: CopilotMessage = { id: crypto.randomUUID(), role: "user", content: trimmed, status: "complete" };
    const assistantId = crypto.randomUUID();
    setMessages(prev => [...prev, userMsg, { id: assistantId, role: "assistant", content: "", status: "streaming" }]);
    setSuggestedAction(matchCopilotAction(trimmed));
    setError(null);

    const ctrl = new AbortController();
    abortRef.current = ctrl;
    let completed = false;
    try {
      const res = await apiFetch(`/api/run/stream`, {
        method: "POST",
        body: JSON.stringify({
          project_id: COPILOT_PROJECT,
          prompt: promptWithContext,
          display_text: trimmed,
          conversation_id: conversationIdRef.current,
        }),
        signal: ctrl.signal,
      });
      if (!res.ok) throw new Error(await chatHttpFailure(res));
      if (!res.body) throw new Error("No response stream was received. Your draft is unchanged.");
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split("\n");
        buf = lines.pop() ?? "";
        for (const line of lines) {
          if (generation !== generationRef.current || !line.startsWith("data: ")) continue;
          const ev = JSON.parse(line.slice(6)) as { type: string; conv_id?: string; text?: string; message?: string };
          if (ev.type === "conv_id" && ev.conv_id) {
            conversationIdRef.current = ev.conv_id;
            setConversationId(ev.conv_id);
          } else if (ev.type === "delta" && ev.text) {
            setMessages(prev => prev.map(m => m.id === assistantId ? { ...m, content: m.content + ev.text } : m));
          } else if (ev.type === "error") {
            throw new Error(ev.message ?? "The copilot could not complete this reply.");
          } else if (ev.type === "done") {
            completed = true;
          }
        }
        if (completed) break;
      }
      if (!completed) throw new Error("The connection ended before the reply was saved. Your draft is still available; please retry.");
      if (generation === generationRef.current) {
        setMessages(prev => prev.map(m => m.id === assistantId ? { ...m, status: "complete" } : m));
        void refreshConversations().catch(() => {});
      }
      return true;
    } catch (err) {
      if (generation === generationRef.current) {
        const stopped = err instanceof Error && err.name === "AbortError";
        const message = stopped ? "Reply stopped." : err instanceof Error ? err.message : "Copilot is unavailable right now.";
        setError(message);
        setMessages(prev => prev.map(m => m.id === assistantId
          ? { ...m, content: m.content || message, status: stopped ? "stopped" : "failed" }
          : m));
      }
      return false;
    } finally {
      if (generation === generationRef.current) {
        requestInFlightRef.current = false;
        abortRef.current = null;
        setStreaming(false);
      }
    }
  }, [page, currentOrg, refreshConversations]);

  const dismissAction = useCallback(() => setSuggestedAction(null), []);
  const reset = useCallback(() => {
    interactionRef.current += 1;
    historyRequestRef.current += 1;
    generationRef.current += 1;
    abortRef.current?.abort();
    abortRef.current = null;
    requestInFlightRef.current = false;
    conversationIdRef.current = null;
    setConversationId(null);
    setMessages([]);
    setLoadingHistory(false);
    setError(null);
    setSuggestedAction(null);
    setStreaming(false);
  }, []);

  const value = useMemo(() => ({
    open, setOpen, messages, conversations, conversationId,
    loadingHistory, streaming, error, suggestedAction, send, openConversation,
    dismissAction, reset,
  }), [open, messages, conversations, conversationId, loadingHistory, streaming, error, suggestedAction, send, openConversation, dismissAction, reset]);

  return <CopilotContext.Provider value={value}>{children}</CopilotContext.Provider>;
}
