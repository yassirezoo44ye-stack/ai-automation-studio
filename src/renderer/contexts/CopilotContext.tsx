/**
 * CopilotContext — persistent, page-aware AI assistant.
 *
 * Reuses the EXISTING /api/run/stream chat endpoint (app/routers/chat.py) —
 * no new AI model, no new backend endpoint. Context-awareness (current
 * page / organization) is achieved by prefixing the prompt text sent to
 * that endpoint with a short context line before streaming; the raw
 * prefix is never shown in the UI, only the user's own text is.
 *
 * Conversations are kept in the caller's own "demo" project (the same
 * default every other chat surface in this app already resolves to via
 * resolve_project_id) under a distinct title, so no schema change was
 * needed to keep this separate in spirit from regular AI Workspace chats.
 */
import { useCallback, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { useAppContext } from "./app";
import { useOrg } from "./OrgContext";
import { API, authH } from "../shared/utils/api";
import { CopilotContext, type CopilotMessage, type CopilotAction } from "./copilot";
import { matchCopilotAction } from "../shared/ui/copilot/copilotActions";
import type { Page } from "../shared/types";

const PAGE_LABELS: Record<Page, string> = {
  home: "Dashboard", ai: "AI Chat", dev: "Dev Workspace", design: "Design Studio",
  automation: "Workflows", social: "Social", settings: "Settings", agentos: "AgentOS",
  marketplace: "Marketplace", organizations: "Organizations", teams: "Teams",
  billing: "Billing", plugins: "Plugins", sandbox: "Sandbox", "ai-routing": "AI Routing",
  observability: "Observability",
};

export function CopilotProvider({ children }: { children: ReactNode }) {
  const { page } = useAppContext();
  const { currentOrg } = useOrg();

  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<CopilotMessage[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [suggestedAction, setSuggestedAction] = useState<CopilotAction | null>(null);

  const conversationIdRef = useRef<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const send = useCallback((text: string) => {
    const trimmed = text.trim();
    if (!trimmed || streaming) return;

    setSuggestedAction(matchCopilotAction(trimmed));

    const userMsg: CopilotMessage = { id: crypto.randomUUID(), role: "user", content: trimmed };
    const assistantId = crypto.randomUUID();
    setMessages(prev => [...prev, userMsg, { id: assistantId, role: "assistant", content: "" }]);
    setStreaming(true);
    setError(null);

    const pageLabel = PAGE_LABELS[page] ?? page;
    const contextLine = `[Context: the user is currently on the "${pageLabel}" page` +
      (currentOrg ? ` of the "${currentOrg.name}" organization` : "") +
      ` inside Axon AI Automation Studio. Answer helpfully and concisely; you may suggest which page to visit but cannot take actions yourself.]`;
    const promptWithContext = `${contextLine}\n\n${trimmed}`;

    const ctrl = new AbortController();
    abortRef.current?.abort();
    abortRef.current = ctrl;

    void (async () => {
      try {
        const res = await fetch(`${API}/api/run/stream`, {
          method: "POST",
          headers: authH(),
          body: JSON.stringify({
            project_id: "demo",
            prompt: promptWithContext,
            conversation_id: conversationIdRef.current,
          }),
          signal: ctrl.signal,
        });
        if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buf = "", closed = false;

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buf += decoder.decode(value, { stream: true });
          const lines = buf.split("\n");
          buf = lines.pop() ?? "";
          for (const line of lines) {
            if (!line.startsWith("data: ")) continue;
            const ev = JSON.parse(line.slice(6)) as { type: string; conv_id?: string; text?: string; message?: string };
            if (ev.type === "conv_id" && ev.conv_id) {
              conversationIdRef.current = ev.conv_id;
            } else if (ev.type === "delta" && ev.text) {
              setMessages(prev => prev.map(m => m.id === assistantId ? { ...m, content: m.content + ev.text } : m));
            } else if (ev.type === "error") {
              setError(ev.message ?? "The copilot hit an error.");
              closed = true;
              break;
            } else if (ev.type === "done") {
              closed = true;
            }
          }
          if (closed) break;
        }
      } catch (err) {
        if ((err as Error).name !== "AbortError") {
          setError((err as Error).message?.includes("fetch") ? "Backend offline." : ((err as Error).message || "Copilot is unavailable right now."));
        }
      } finally {
        setStreaming(false);
        abortRef.current = null;
      }
    })();
  }, [streaming, page, currentOrg]);

  const dismissAction = useCallback(() => setSuggestedAction(null), []);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    conversationIdRef.current = null;
    setMessages([]);
    setError(null);
    setSuggestedAction(null);
    setStreaming(false);
  }, []);

  const value = useMemo(() => ({
    open, setOpen, messages, streaming, error, suggestedAction, send, dismissAction, reset,
  }), [open, messages, streaming, error, suggestedAction, send, dismissAction, reset]);

  return (
    <CopilotContext.Provider value={value}>
      {children}
    </CopilotContext.Provider>
  );
}
