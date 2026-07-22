/**
 * ChatTab — streaming AI conversation panel.
 * Handles conversation list, message rendering, streaming, task extraction.
 * All data access goes through apiFetch; no direct provider imports.
 */
import { useState, useRef, useEffect, useMemo, memo, type CSSProperties } from "react";
import ReactMarkdown from "react-markdown";
import { useToast } from "../../../contexts/toast";
import { apiFetch, apiJSON, authH, API, APIError } from "../../../utils/api";
import { relTime } from "../../../utils/time";
import { MD_COMPONENTS } from "../../../shared/ui/md-components";
import { useAsyncData } from "../../../shared/hooks/useAsyncData";
import { LoadingSpinner } from "../../../shared/ui/LoadingSpinner";
import { ErrorState, EmptyState } from "../../../shared/ui/StateViews";
import { GoldButton } from "../../../shared/ui/gold";
import AxonLogo from "../../../AxonLogo";
import type { Message, Conv, Project, Agent, Task } from "../../../types";
import { PRIORITY_COLOR } from "../../../constants";

/** Extracts a user-readable message from any caught error, preferring APIError's diagnostics. */
function describeError(err: unknown, fallback: string): string {
  if (err instanceof APIError) return err.details.probableCause ?? err.message;
  if (err instanceof Error) return err.message || fallback;
  return fallback;
}

interface ChatTabProps {
  agents:         Agent[];
  projects:       Project[];
  initialAgentId?: string | null;
}

export function ChatTab({ agents, projects, initialAgentId }: ChatTabProps) {
  const toast = useToast();
  const [projectId, setProjectId] = useState("demo");
  const [agentId, setAgentId]     = useState<string>(initialAgentId ?? "default");
  const {
    data: convs = [], status: convsStatus, error: convsError, suggestedFix: convsFix, refetch: loadConvs,
  } = useAsyncData(() => apiJSON<Conv[]>(`/api/conversations?project_id=${projectId}`), [projectId]);
  const [activeConv, setActiveConv] = useState<string | null>(null);
  // Local, mutable copy of the active conversation's messages. Backed by
  // useAsyncData below for the *load* — but sendMessage() must keep
  // appending/streaming tokens into this directly, which a hook whose only
  // externally-owned value is `data` can't support, so loaded history is
  // synced in via effect rather than read straight from the hook.
  const [messages, setMessages]   = useState<Message[]>([]);
  // Which conversation `messages` actually holds content for. Lets the UI
  // tell "switching to a different, not-yet-loaded past conversation"
  // (messagesConvId out of sync with activeConv -> show a spinner, don't
  // flash the old conversation's messages) apart from "sendMessage() just
  // created a brand-new conversation mid-stream" (messagesConvId is set to
  // the new id immediately, in the same handler that flips activeConv, so
  // the in-progress streamed reply is never hidden behind a loading state).
  const [messagesConvId, setMessagesConvId] = useState<string | null>(null);
  const [prompt, setPrompt]       = useState("");
  const [streaming, setStreaming] = useState(false);
  const [searchQ, setSearchQ]     = useState("");
  // Same local-copy-synced-from-hook pattern as messages: setTaskStatus
  // optimistically mutates this list, which a hook-owned `data` can't allow.
  const [inlineTasks, setInlineTasks] = useState<Task[]>([]);
  const [extracting, setExtracting]   = useState(false);
  const [showTasks, setShowTasks]     = useState(false);
  const [exporting, setExporting]     = useState(false);
  // Track *which* conversation/task is in flight so only that row's control
  // disables — an unrelated conversation's delete button, or a different
  // task's checkbox, must stay clickable while another one is in flight.
  const [deletingIds, setDeletingIds] = useState<Set<string>>(new Set());
  const [pendingTaskIds, setPendingTaskIds] = useState<Set<string>>(new Set());
  const bottomRef = useRef<HTMLDivElement>(null);
  const abortRef  = useRef<AbortController | null>(null);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages]);

  // Reset conversation state when the project changes — during render,
  // per React's "adjusting state when a prop changes" pattern.
  const [prevProjectId, setPrevProjectId] = useState(projectId);
  if (prevProjectId !== projectId) {
    setPrevProjectId(projectId); setActiveConv(null); setMessages([]); setMessagesConvId(null);
  }

  const {
    data: loadedTasks, status: inlineTasksStatus, error: inlineTasksError,
    suggestedFix: inlineTasksFix, refetch: loadInlineTasks,
  } = useAsyncData(
    () => apiJSON<{ tasks?: Task[] }>("/api/tasks?sort=created_at").then(d => (d.tasks ?? []).slice(0, 6)),
    [activeConv, showTasks],
    { enabled: !!activeConv && showTasks },
  );
  useEffect(() => {
    // Deferred so the setState runs outside the effect's own commit.
    if (loadedTasks) void Promise.resolve().then(() => setInlineTasks(loadedTasks));
  }, [loadedTasks]);

  const {
    data: loadedMessages, status: messagesStatus, error: messagesError,
    suggestedFix: messagesFix, refetch: reloadMessages,
  } = useAsyncData<Message[]>(
    async () => {
      const path = `/api/conversations/${activeConv}/messages`;
      const msgs = await apiJSON<{ id: string; role: string; content: string }[]>(path);
      return msgs.map(m => ({ id: m.id, role: m.role as "user" | "assistant", content: m.content }));
    },
    [activeConv],
    { enabled: !!activeConv, isEmpty: () => false }, // an empty conversation is not an error state worth flagging
  );
  // Sync loaded history into the local, streaming-mutable copy. This effect
  // only ever fires on an actual conversation switch or an explicit manual
  // retry — sendMessage() never changes activeConv or calls reloadMessages,
  // so it can't be clobbered by a fetch racing an in-progress stream.
  useEffect(() => {
    if (!loadedMessages) return;
    // Deferred so the setState runs outside the effect's own commit.
    void Promise.resolve().then(() => {
      setMessages(loadedMessages);
      setMessagesConvId(activeConv);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadedMessages]);

  async function extractTasks() {
    if (!activeConv || extracting) return; // prevent duplicate submissions
    setExtracting(true);
    try {
      const path = `/api/tasks/from-conversation/${activeConv}`;
      const d = await apiJSON<{ created?: unknown[] }>(path, { method: "POST" });
      const n = d.created?.length ?? 0;
      toast(n > 0 ? `Extracted ${n} task${n !== 1 ? "s" : ""}` : "No clear tasks found", n > 0 ? "ok" : "info");
      if (n > 0) { setShowTasks(true); loadInlineTasks(); }
    } catch (err) {
      toast(describeError(err, "Failed to extract tasks"), "err");
    } finally {
      setExtracting(false);
    }
  }

  async function setTaskStatus(t: Task, status: string) {
    if (pendingTaskIds.has(t.id)) return; // prevent duplicate submissions for this task
    setPendingTaskIds(prev => new Set(prev).add(t.id));
    setInlineTasks(prev => prev.map(x => x.id === t.id ? { ...x, status: status as Task["status"] } : x));
    try {
      await apiFetch(`/api/tasks/${t.id}`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status }),
      });
    } catch (err) {
      toast(describeError(err, "Failed to update task — reverting"), "err");
      loadInlineTasks(); // resync with server truth after the optimistic update failed
    } finally {
      setPendingTaskIds(prev => { const next = new Set(prev); next.delete(t.id); return next; });
    }
  }

  async function deleteConv(e: React.SyntheticEvent, cid: string) {
    e.stopPropagation();
    if (deletingIds.has(cid)) return; // prevent duplicate submissions for this conversation
    setDeletingIds(prev => new Set(prev).add(cid));
    try {
      const r = await apiFetch(`/api/conversations/${cid}`, { method: "DELETE" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      if (activeConv === cid) { setActiveConv(null); setMessages([]); }
      loadConvs();
    } catch (err) {
      toast(describeError(err, "Failed to delete conversation"), "err");
    } finally {
      setDeletingIds(prev => { const next = new Set(prev); next.delete(cid); return next; });
    }
  }

  async function exportConv() {
    if (!activeConv || exporting) return; // prevent duplicate submissions
    setExporting(true);
    try {
      const r = await apiFetch(`/api/export/conversations/${activeConv}`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const blob = await r.blob();
      const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "conversation.md"; a.click();
      URL.revokeObjectURL(a.href);
      toast("Exported as Markdown");
    } catch (err) {
      toast(describeError(err, "Export failed"), "err");
    } finally {
      setExporting(false);
    }
  }

  async function sendMessage() {
    const text = prompt.trim();
    if (!text || streaming) return;
    setPrompt("");
    const userMsg: Message = { id: crypto.randomUUID(), role: "user", content: text };
    setMessages(prev => [...prev, userMsg]);
    setStreaming(true);
    const assistantId = crypto.randomUUID();
    setMessages(prev => [...prev, { id: assistantId, role: "assistant", content: "" }]);

    const ctrl = new AbortController();
    abortRef.current = ctrl;
    const useAgent = agentId !== "default";
    const url = useAgent ? `${API}/api/agents/${agentId}/chat/stream` : `${API}/run/stream`;

    try {
      const res = await fetch(url, {
        method: "POST", headers: authH(),
        body: JSON.stringify({ project_id: projectId, prompt: text, conversation_id: activeConv, agent_id: agentId }),
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
        const lines = buf.split("\n"); buf = lines.pop() ?? "";
        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const ev = JSON.parse(line.slice(6));
          if (ev.type === "conv_id" && !activeConv) {
            // Claim this id for the messages already in local state *before*
            // flipping activeConv, so the messages-loading effect (keyed on
            // activeConv) sees them as already in sync and never shows a
            // loading state over the reply that's actively streaming in.
            setMessagesConvId(ev.conv_id);
            setActiveConv(ev.conv_id);
            loadConvs();
          }
          else if (ev.type === "delta")  { setMessages(p => p.map(m => m.id === assistantId ? { ...m, content: m.content + ev.text } : m)); }
          else if (ev.type === "error")  { setMessages(p => p.map(m => m.id === assistantId ? { ...m, content: `⚠️ ${ev.message}` } : m)); closed = true; break; }
          else if (ev.type === "done")   { loadConvs(); closed = true; }
        }
        if (closed) break;
      }
    } catch (err: unknown) {
      if ((err as Error).name !== "AbortError") {
        const msg = (err as Error).message ?? "";
        setMessages(p => p.map(m => m.id === assistantId ? { ...m, content: msg.includes("fetch") ? "⚠️ Backend offline" : `⚠️ ${msg}` } : m));
      }
    } finally { setStreaming(false); abortRef.current = null; }
  }

  const filteredConvs = useMemo(
    () => searchQ ? convs.filter(c => c.title.toLowerCase().includes(searchQ.toLowerCase())) : convs,
    [convs, searchQ],
  );
  const activeAgent = useMemo(() => agents.find(a => a.id === agentId), [agents, agentId]);

  // True only while `messages` genuinely doesn't reflect activeConv yet —
  // i.e. the user switched to a different, not-yet-loaded past conversation.
  // False for a brand-new conversation created mid-stream, since sendMessage
  // claims messagesConvId for it before flipping activeConv (see above) —
  // the in-progress streamed reply must never be hidden behind a spinner.
  const messagesOutOfSync = !!activeConv && messagesConvId !== activeConv;
  const showMessagesLoading = messagesOutOfSync && messagesStatus === "loading";
  const showMessagesError   = messagesOutOfSync && messagesStatus === "error";

  return (
    <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>
      {/* ── Conversation sidebar ──────────────────────────────────────────────── */}
      <div style={{ width: 230, flexShrink: 0, display: "flex", flexDirection: "column", background: "var(--bg-panel)", backdropFilter: "blur(16px)", borderRight: "1px solid var(--border)" }}>
        <div style={{ padding: "10px 10px 6px", display: "flex", gap: 6 }}>
          <select value={projectId} onChange={e => setProjectId(e.target.value)} className="g-input" style={{ flex: 1, fontSize: 12, padding: "8px 12px" }}>
            <option value="demo">Demo Project</option>
            {projects.filter(p => p.id !== "00000000-0000-0000-0000-000000000001").map(p => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
        </div>
        <div style={{ padding: "0 10px 6px" }}>
          <select value={agentId} onChange={e => setAgentId(e.target.value)} className="g-input" style={{ width: "100%", fontSize: 12, padding: "8px 12px" }}>
            <option value="default">🤖 Claude (default)</option>
            {agents.map(a => <option key={a.id} value={a.id}>{a.avatar} {a.name}</option>)}
          </select>
        </div>
        <div style={{ padding: "0 8px 6px", display: "flex", gap: 6 }}>
          <GoldButton
            onClick={() => { setActiveConv(null); setMessages([]); setMessagesConvId(null); setShowTasks(false); }}
            style={{ flex: 1, fontSize: 12 }}
          >
            + New Chat
          </GoldButton>
          {activeConv && (
            <button onClick={exportConv} disabled={exporting} title="Export as Markdown" className="btn-icon" style={{ width: 36 }}>
              {exporting ? "…" : "↓"}
            </button>
          )}
          {activeConv && (
            <button onClick={extractTasks} disabled={extracting} title="Extract tasks" className="btn-icon" style={{ width: 36 }}>
              {extracting ? "…" : "✅"}
            </button>
          )}
        </div>
        <div style={{ padding: "0 8px 6px" }}>
          <input value={searchQ} onChange={e => setSearchQ(e.target.value)} placeholder="Search…" className="g-input" style={{ fontSize: 12, padding: "6px 10px" }} />
        </div>
        <div style={{ flex: 1, overflowY: "auto", position: "relative" }}>
          {convsStatus === "refreshing" && (
            <div style={{ position: "absolute", top: 6, right: 8, opacity: 0.6, zIndex: 1 }}>
              <LoadingSpinner size={14} label="" />
            </div>
          )}
          {convsStatus === "loading" && <LoadingSpinner label="Loading conversations…" />}
          {convsStatus === "error" && (
            <ErrorState compact message={convsError ?? "Failed to load conversations."} suggestedFix={convsFix} onRetry={loadConvs} />
          )}
          {convsStatus === "empty" && (
            <EmptyState compact title="No conversations yet" description="Start a new chat to see it here." />
          )}
          {(convsStatus === "success" || convsStatus === "refreshing") && filteredConvs.length === 0 && (
            <EmptyState compact title="No matches" description={`Nothing found for "${searchQ}".`} />
          )}
          {filteredConvs.map(c => {
            const isDeleting = deletingIds.has(c.id);
            return (
              <div
                key={c.id}
                role="button" tabIndex={0}
                onClick={() => setActiveConv(c.id)}
                onKeyDown={e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setActiveConv(c.id); } }}
                style={{
                  padding: "10px 14px", cursor: "pointer", transition: "background .15s",
                  background: c.id === activeConv ? "var(--accent-dim)" : "transparent",
                  borderRight: c.id === activeConv ? "2px solid var(--accent)" : "2px solid transparent",
                  ...(isDeleting ? { opacity: 0.5, pointerEvents: "none" } : {}),
                }}
              >
                <div style={{ fontSize: 12, fontWeight: 500, color: "var(--t1)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{c.title}</div>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 2 }}>
                  <span style={{ fontSize: 10, color: "var(--t5)" }}>{relTime(c.updated_at)}</span>
                  <span
                    role="button" tabIndex={0}
                    onClick={e => { if (!isDeleting) deleteConv(e, c.id); }}
                    onKeyDown={e => { if (!isDeleting && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); void deleteConv(e, c.id); } }}
                    title={isDeleting ? "Deleting…" : "Delete conversation"}
                    aria-label={isDeleting ? "Deleting…" : "Delete conversation"}
                    style={{ color: "var(--t5)", fontSize: 11, cursor: isDeleting ? "default" : "pointer" }}
                  >
                    {isDeleting ? "…" : "✕"}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* ── Chat area ─────────────────────────────────────────────────────────── */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        {/* Inline tasks strip — shown while loading/erroring too now, not just once tasks exist,
            so "Extract tasks" always gives visible feedback instead of silently doing nothing. */}
        {showTasks && (inlineTasksStatus === "loading" || inlineTasksStatus === "error" || inlineTasks.length > 0) && (
          <div style={{ padding: "10px 16px", borderBottom: "1px solid var(--border)", background: "var(--accent-dim)", display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
            <span style={{ fontSize: 11, fontWeight: 600, color: "var(--ta)", flexShrink: 0 }}>TASKS</span>
            {inlineTasksStatus === "loading" && <LoadingSpinner size={14} label="" />}
            {inlineTasksStatus === "error" && (
              <ErrorState compact message={inlineTasksError ?? "Failed to load tasks."} suggestedFix={inlineTasksFix} onRetry={loadInlineTasks} />
            )}
            {inlineTasksStatus !== "loading" && inlineTasksStatus !== "error" && inlineTasks.map(t => {
              const isPending = pendingTaskIds.has(t.id);
              return (
                <div key={t.id} style={{ display: "flex", alignItems: "center", gap: 6, padding: "4px 10px", borderRadius: 20, background: "var(--bg-hover)", border: "1px solid var(--border)", fontSize: 12, opacity: isPending ? 0.6 : 1 }}>
                  <button
                    onClick={() => setTaskStatus(t, t.status === "done" ? "pending" : "done")}
                    disabled={isPending}
                    style={{ background: "none", border: "none", cursor: isPending ? "default" : "pointer", padding: 0, color: t.status === "done" ? "var(--green)" : "var(--t5)", display: "flex" }}
                  >
                    {t.status === "done"
                      ? <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="20 6 9 17 4 12"/></svg>
                      : <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="9"/></svg>}
                  </button>
                  <span style={{ color: t.status === "done" ? "var(--t5)" : "var(--t2)", textDecoration: t.status === "done" ? "line-through" : "none" }}>{t.title}</span>
                  <span style={{ width: 6, height: 6, borderRadius: "50%", background: PRIORITY_COLOR[t.priority], flexShrink: 0 }} title={t.priority} />
                </div>
              );
            })}
            <button onClick={() => setShowTasks(false)} style={{ background: "none", border: "none", color: "var(--t5)", cursor: "pointer", marginLeft: "auto", fontSize: 16 }}>×</button>
          </div>
        )}

        {/* Messages */}
        <div style={{ flex: 1, overflowY: "auto", padding: "32px 0", display: "flex", flexDirection: "column", gap: 0, position: "relative" }}>
          {showMessagesLoading && <LoadingSpinner fullPage label="Loading conversation…" />}
          {showMessagesError && (
            <ErrorState message={messagesError ?? "Failed to load this conversation."} suggestedFix={messagesFix} onRetry={reloadMessages} />
          )}
          {!showMessagesLoading && !showMessagesError && messages.length === 0 && (
            <div style={{ margin: "auto", textAlign: "center", color: "var(--t5)", paddingBottom: 80, animation: "fadeIn .4s ease" }}>
              <div style={{ width: 72, height: 72, borderRadius: 20, margin: "0 auto 16px", background: "var(--accent-dim)", border: "1px solid var(--accent-border)", display: "flex", alignItems: "center", justifyContent: "center" }}>
                {activeAgent ? <span style={{ fontSize: 32 }}>{activeAgent.avatar}</span> : <AxonLogo size={40} />}
              </div>
              <div style={{ fontSize: 20, fontWeight: 700, color: "var(--t1)", letterSpacing: "-.4px" }}>{activeAgent ? activeAgent.name : "Axon AI"}</div>
              <div style={{ fontSize: 14, color: "var(--t4)", maxWidth: 320, lineHeight: 1.65, marginTop: 6 }}>
                {activeAgent?.description ?? "Start a conversation or pick one from the sidebar."}
              </div>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", justifyContent: "center", marginTop: 16 }}>
                {["Write Python code", "Explain a concept", "Debug my script", "Build a web app"].map(s => (
                  <GoldButton key={s} variant="ghost" onClick={() => setPrompt(s)} style={{ fontSize: 12, padding: "6px 14px" }}>{s}</GoldButton>
                ))}
              </div>
            </div>
          )}
          {/* Suppressed while a *different* conversation's history is loading/erroring, so the
              previous conversation's messages never flash underneath the loading/error state. */}
          {!showMessagesLoading && !showMessagesError && messages.map((m, idx) => (
            <MessageRow key={m.id} msg={m} isLast={idx === messages.length - 1}
                        agentName={activeAgent?.name ?? null} agentAvatar={activeAgent?.avatar ?? null} />
          ))}
          <div ref={bottomRef} />
        </div>

        {/* Input */}
        <div style={{ padding: "14px 22px", gap: 10, borderTop: "1px solid var(--border)", display: "flex", alignItems: "flex-end", background: "var(--bg-panel)", backdropFilter: "blur(16px)" }}>
          <textarea
            value={prompt}
            onChange={e => setPrompt(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void sendMessage(); } }}
            placeholder="Message… (Enter to send, Shift+Enter for new line)"
            className="g-input" style={{ flex: 1, maxHeight: 160, resize: "none" }} rows={1}
          />
          {streaming
            ? <GoldButton variant="danger" onClick={() => abortRef.current?.abort()} style={{ width: 42, height: 42, padding: 0, flexShrink: 0 }}>■</GoldButton>
            : <GoldButton onClick={() => void sendMessage()} disabled={!prompt.trim()} style={{ width: 42, height: 42, padding: 0, flexShrink: 0 }}>↑</GoldButton>}
        </div>
      </div>
    </div>
  );
}

// Memoized row: during streaming, only the last message's content changes —
// memo stops React re-rendering (and re-parsing markdown for) every earlier
// message on each streamed token.
const MessageRow = memo(function MessageRow({ msg, isLast, agentName, agentAvatar }: {
  msg: Message; isLast: boolean; agentName: string | null; agentAvatar: string | null;
}) {
  const rowStyle: CSSProperties = msg.role === "user"
    ? { display: "flex", gap: 14, alignItems: "flex-start", padding: "16px 32px", maxWidth: 900, width: "100%", alignSelf: "flex-end", flexDirection: "row-reverse", animation: "slideIn .22s ease" }
    : { display: "flex", gap: 14, alignItems: "flex-start", padding: "16px 32px", maxWidth: 900, width: "100%", animation: "slideIn .22s ease" };
  return (
    <div style={rowStyle} className="msg-row">
      {msg.role === "assistant" && (
        <div style={{ width: 34, height: 34, borderRadius: 9, flexShrink: 0, background: "var(--accent-dim)", border: "1px solid var(--accent-border)", display: "flex", alignItems: "center", justifyContent: "center", marginTop: 2 }}>
          <span style={{ fontSize: 18 }}>{agentAvatar ?? "◈"}</span>
        </div>
      )}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{
          fontSize: 11, fontWeight: 600, marginBottom: 7, display: "flex", alignItems: "center", gap: 8,
          letterSpacing: "0.04em", textTransform: "uppercase",
          color: msg.role === "user" ? "var(--t5)" : "var(--ta)",
          justifyContent: msg.role === "user" ? "flex-end" : "flex-start",
        }}>
          {msg.role === "user" ? "You" : (agentName ?? "Claude")}
          <span style={{ fontSize: 10, color: "var(--t5)", fontWeight: 400 }}>{isLast ? "now" : ""}</span>
        </div>
        {msg.role === "user" ? (
          <div style={{
            fontSize: 15, lineHeight: 1.75, color: "var(--t1)",
            background: "linear-gradient(135deg, var(--accent-dim), var(--accent-glow))",
            border: "1px solid var(--accent-border)",
            borderRadius: 16, borderTopRightRadius: 4, padding: "12px 18px",
            boxShadow: "0 2px 16px var(--accent-dim)", display: "inline-block",
          }}>{msg.content}</div>
        ) : msg.content === "" ? (
          <div style={{ padding: "8px 0" }} className="typing"><span /><span /><span /></div>
        ) : (
          <div style={{ fontSize: 15, color: "var(--t2)", lineHeight: 1.8 }} className="md-body">
            <ReactMarkdown components={MD_COMPONENTS}>{msg.content}</ReactMarkdown>
          </div>
        )}
      </div>
      {msg.role === "user" && (
        <div style={{
          width: 34, height: 34, borderRadius: 9, flexShrink: 0,
          background: "linear-gradient(135deg, var(--accent), var(--accent-2))",
          display: "flex", alignItems: "center", justifyContent: "center",
          fontSize: 13, fontWeight: 700, color: "#121008", marginTop: 2,
        }}>Y</div>
      )}
    </div>
  );
});

