import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { useCopilot } from "../../../contexts/copilot";
import { useAppContext } from "../../../contexts/app";
import { MD_COMPONENTS } from "../md-components";
import { GoldButton } from "../gold";
import { promptCharacters, MAX_PROMPT_CHARACTERS } from "../../utils/chatReliability";
import type { Page } from "../../types";

export function CopilotPanel() {
  const {
    messages, conversations, conversationId, loadingHistory, streaming, error,
    suggestedAction, send, openConversation, dismissAction, reset, setOpen,
  } = useCopilot();
  const { setPage } = useAppContext();
  const [input, setInput] = useState("");
  const listRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    listRef.current?.scrollTo?.({ top: listRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    panelRef.current?.focus();
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [setOpen]);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!input.trim() || streaming) return;
    const submitted = input;
    const accepted = await send(submitted);
    // Do not discard text on validation errors, HTTP failures, or disconnects.
    if (accepted) setInput(current => current === submitted ? "" : current);
  }

  function goToSuggestedPage() {
    if (!suggestedAction) return;
    setPage(suggestedAction.page as Page);
    dismissAction();
    setOpen(false);
  }

  return (
    <div ref={panelRef} className="g-copilot-panel" role="dialog" aria-label="AI Copilot" aria-modal="false" tabIndex={-1}>
      <div className="g-copilot-panel__header">
        <span className="g-copilot-panel__title">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="M12 2a5 5 0 0 1 5 5v2a5 5 0 0 1-10 0V7a5 5 0 0 1 5-5z"/><path d="M2 20c0-3 3.5-5 10-5s10 2 10 5"/></svg>
          AI Copilot
        </span>
        <div style={{ display: "flex", gap: 4 }}>
          {messages.length > 0 && <button type="button" className="g-notif-item__op" onClick={reset} title="New conversation" aria-label="Start a new conversation">↺</button>}
          <button type="button" className="g-notif-item__op" onClick={() => setOpen(false)} title="Close" aria-label="Close copilot">×</button>
        </div>
      </div>

      <details className="g-copilot-history">
        <summary>Conversation history{conversationId ? " · Active" : ""}</summary>
        {loadingHistory && <div role="status">Loading history…</div>}
        {!loadingHistory && conversations.length === 0 && <div>No saved conversations yet.</div>}
        {conversations.map(c => (
          <button key={c.id} type="button" onClick={() => void openConversation(c.id)} disabled={streaming || c.id === conversationId}>
            {c.title || "Untitled conversation"}
          </button>
        ))}
      </details>

      <div ref={listRef} className="g-copilot-panel__list" role="log" aria-live="polite" aria-label="Conversation">
        {messages.length === 0 && !loadingHistory && (
          <div className="g-copilot-empty">
            <p>Ask me anything about this page, or try:</p>
            <ul><li>"Explain this page"</li><li>"Open billing"</li><li>"Show failed workflows"</li></ul>
          </div>
        )}
        {messages.map(m => (
          <div key={m.id} className={`g-copilot-msg g-copilot-msg--${m.role}`}>
            {m.role === "assistant" && m.content === "" && streaming
              ? <span className="g-copilot-typing" aria-label="Copilot is typing"><span /><span /><span /></span>
              : <ReactMarkdown components={MD_COMPONENTS}>{m.content}</ReactMarkdown>}
            {m.role === "assistant" && m.status && m.status !== "complete" && m.status !== "streaming" && (
              <small role="status">{m.status === "stopped" ? "Reply stopped" : "Reply failed; your prompt is still available to retry"}</small>
            )}
          </div>
        ))}
        {error && <div className="g-error-banner" role="alert">{error}</div>}
      </div>

      {suggestedAction && (
        <div className="g-copilot-suggestion">
          <span>Looks like you want to navigate.</span>
          <GoldButton variant="ghost" onClick={goToSuggestedPage}>{suggestedAction.label} →</GoldButton>
          <button type="button" className="g-notif-item__op" onClick={dismissAction} aria-label="Dismiss suggestion">×</button>
        </div>
      )}

      <div role="status" style={{ fontSize: 12 }}>{promptCharacters(input)} / {MAX_PROMPT_CHARACTERS} · يشمل حد الطلب سياق الصفحة / Request limit includes page context</div>
      <form onSubmit={onSubmit} className="g-copilot-panel__input-row">
        <textarea rows={3} value={input} onChange={e => setInput(e.target.value)} placeholder="Ask the copilot…" aria-label="Ask the copilot" disabled={streaming} className="g-input" />
        <GoldButton type="submit" disabled={streaming || !input.trim()}>{streaming ? "…" : "Send"}</GoldButton>
      </form>
    </div>
  );
}
