import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { useCopilot } from "../../../contexts/copilot";
import { useAppContext } from "../../../contexts/app";
import { MD_COMPONENTS } from "../md-components";
import { GoldButton } from "../gold";
import type { Page } from "../../types";

export function CopilotPanel() {
  const { messages, streaming, error, suggestedAction, send, dismissAction, reset, setOpen } = useCopilot();
  const { setPage } = useAppContext();
  const [input, setInput] = useState("");
  const listRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // Not implemented in jsdom (test environment) — real browsers all support it.
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

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!input.trim() || streaming) return;
    send(input);
    setInput("");
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
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 2a5 5 0 0 1 5 5v2a5 5 0 0 1-10 0V7a5 5 0 0 1 5-5z"/><path d="M2 20c0-3 3.5-5 10-5s10 2 10 5"/></svg>
          AI Copilot
        </span>
        <div style={{ display: "flex", gap: 4 }}>
          {messages.length > 0 && (
            <button type="button" className="g-notif-item__op" onClick={reset} title="New conversation" aria-label="Start a new conversation">↺</button>
          )}
          <button type="button" className="g-notif-item__op" onClick={() => setOpen(false)} title="Close" aria-label="Close copilot">×</button>
        </div>
      </div>

      <div ref={listRef} className="g-copilot-panel__list" role="log" aria-live="polite" aria-label="Conversation">
        {messages.length === 0 && (
          <div className="g-copilot-empty">
            <p>Ask me anything about this page, or try:</p>
            <ul>
              <li>"Explain this page"</li>
              <li>"Open billing"</li>
              <li>"Show failed workflows"</li>
            </ul>
          </div>
        )}
        {messages.map(m => (
          <div key={m.id} className={`g-copilot-msg g-copilot-msg--${m.role}`}>
            {m.role === "assistant" && m.content === "" && streaming ? (
              <span className="g-copilot-typing" aria-label="Copilot is typing"><span /><span /><span /></span>
            ) : (
              <ReactMarkdown components={MD_COMPONENTS}>{m.content}</ReactMarkdown>
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

      <form onSubmit={onSubmit} className="g-copilot-panel__input-row">
        <input
          value={input}
          onChange={e => setInput(e.target.value)}
          placeholder="Ask the copilot…"
          aria-label="Ask the copilot"
          disabled={streaming}
          className="g-input"
        />
        <GoldButton type="submit" disabled={streaming || !input.trim()}>{streaming ? "…" : "Send"}</GoldButton>
      </form>
    </div>
  );
}
