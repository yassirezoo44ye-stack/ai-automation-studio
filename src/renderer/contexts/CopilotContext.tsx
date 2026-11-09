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
import { API, authH } from "../shared/utils/api";
import { CopilotContext, type CopilotConversation, type CopilotMessage, type CopilotAction } from "./copilot";
import { matchCopilotAction } from "../shared/ui/copilot/copilotActions";
import type { Page } from "../shared/types";

const MAX_REQUEST_CHARACTERS = 4000;
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

export function CopilotProvider({ children }: { children: ReactNode }) {
  const { page } = useAppContext();
  const { currentOrg } = useOrg();
  const [open, setOpen] = useState(false);
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

  const refreshConversations = useCallback(async () => {
    const response = await fetch(`${API}/api/conversations?project_id=${encodeURIComponent(COPILOT_PROJECT)}`, {
      headers: authH(),
    });
    const items = await jsonOrThrow<CopilotConversation[]>(response);
    setConversations(items);
    return items;
  }, []);

  // The endpoint scopes the list through the authenticated user's project.
  // The message endpoint independently verifies ownership before returning rows.
  useEffect(() => {
    let mounted = true;
    const requestId = ++historyRequestRef.current;
    setLoadingHistory(true);
    void refreshConversations().then(async items => {
      if (!mounted || requestId !== historyRequestRef.current || !items.length) return;
      const first = items[0];
      const response = await fetch(`${API}/api/conversations/${encodeURIComponent(first.id)}/messages`, {
        headers: authH(),
      });
      const rows = await jsonOrThrow<{ id: string; role: string; content: string }[]>(response);
      if (!mounted || requestId !== historyRequestRef.current || conversationIdRef.current) return;
      conversationIdRef.current = first.id;
      setMessages(rows.filter(m => m.role === "user" || m.role === "assistant")
        .map(m => ({ id: m.id, role: m.role as CopilotMessage["role"], content: m.content, status: "complete" })));
    }).catch(() => {
      // A failed history request must not block starting a fresh conversation.
    }).finally(() => {
      if (mounted && requestId === historyRequestRef.current) setLoadingHistory(false);
    });
    return () => { mounted = false; };
  }, [refreshConversations]);

  const openConversation = useCallback(async (id: string) => {
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
    setMessages([]);
    try {
      const response = await fetch(`${API}/api/conversations/${encodeURIComponent(id)}/messages`, {
        headers: authH(),
      });
      const rows = await jsonOrThrow<{ id: string; role: string; content: string }[]>(response);
      if (requestId !== historyRequestRef.current) return;
      conversationIdRef.current = id;
      setMessages(rows.filter(m => m.role === "user" || m.role === "assistant")
        .map(m => ({ id: m.id, role: m.role as CopilotMessage["role"], content: m.content, status: "complete" })));
    } catch (err) {
      if (requestId === historyRequestRef.current) setError(err instanceof Error ? err.message : "Could not load this conversation.");
    } finally {
      if (requestId === historyRequestRef.current) setLoadingHistory(false);
    }
  }, []);

  const send = useCallback(async (text: string): Promise<boolean> => {
    const trimmed = text.trim();
    if (!trimmed || requestInFlightRef.current) return false;

    const pageLabel = PAGE_LABELS[page] ?? page;
    const contextLine = `[Context: the user is currently on the "${pageLabel}" page` +
      (currentOrg ? ` of the "${currentOrg.name}" organization` : "") +
      ` inside Axon AI Automation Studio. Answer helpfully and concisely; you may suggest which page to visit but cannot take actions yourself.]`;
    const promptWithContext = `${contextLine}\n\n${trimmed}`;
    // Match RunRequest's 4,000-character limit before changing the conversation
    // or letting the composer clear its draft.
    if (promptWithContext.length > MAX_REQUEST_CHARACTERS) {
      setError(`This message is too long (${promptWithContext.length} characters; limit ${MAX_REQUEST_CHARACTERS}). Shorten it and try again.`);
      return false;
    }

    requestInFlightRef.current = true;
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
      const res = await fetch(`${API}/api/run/stream`, {
        method: "POST",
        headers: authH(),
        body: JSON.stringify({
          project_id: COPILOT_PROJECT,
          prompt: promptWithContext,
          display_text: trimmed,
          conversation_id: conversationIdRef.current,
        }),
        signal: ctrl.signal,
      });
      if (!res.ok || !res.body) throw new Error(`Request failed (${res.status})`);
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

  // Keep the flag synchronized with the synchronous ref guard; this prevents
  // rapid clicks from starting parallel fetches before React re-renders.
  useEffect(() => {
    if (requestInFlightRef.current) setStreaming(true);
  }, [messages]);

  const dismissAction = useCallback(() => setSuggestedAction(null), []);
  const reset = useCallback(() => {
    historyRequestRef.current += 1;
    generationRef.current += 1;
    abortRef.current?.abort();
    abortRef.current = null;
    requestInFlightRef.current = false;
    conversationIdRef.current = null;
    setMessages([]);
    setError(null);
    setSuggestedAction(null);
    setStreaming(false);
  }, []);

  const value = useMemo(() => ({
    open, setOpen, messages, conversations, conversationId: conversationIdRef.current,
    loadingHistory, streaming, error, suggestedAction, send, openConversation,
    dismissAction, reset,
  }), [open, messages, conversations, loadingHistory, streaming, error, suggestedAction, send, openConversation, dismissAction, reset]);

  return <CopilotContext.Provider value={value}>{children}</CopilotContext.Provider>;
}
