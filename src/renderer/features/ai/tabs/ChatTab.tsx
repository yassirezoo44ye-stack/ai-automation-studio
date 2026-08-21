/**
 * ChatTab — 3-column AI command center.
 *
 * Columns:
 *   1. Conversation Rail (260px, collapsible on mobile)
 *   2. Main Chat (flex: 1) — toolbar, messages, composer
 *   3. Context Panel (280px, collapsible)
 *
 * All streaming, conversation management, and task logic is unchanged
 * from the original implementation. RTL is handled via CSS logical
 * properties in chat.css and `marginInlineStart` etc. in inline styles.
 */
import { useState, useRef, useEffect, useMemo, memo, type CSSProperties } from "react";
import ReactMarkdown from "react-markdown";
import { useTranslation } from "react-i18next";
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
import "../chat.css";

/** Extracts a user-readable message from any caught error, preferring APIError's diagnostics. */
function describeError(err: unknown, fallback: string): string {
  if (err instanceof APIError) return err.details.probableCause ?? err.message;
  if (err instanceof Error) return err.message || fallback;
  return fallback;
}

/** Group conversations into Today / This Week / Older buckets. */
function groupConvsByDate(convs: Conv[]): { label: "today" | "thisWeek" | "older"; items: Conv[] }[] {
  const now = Date.now();
  const day = 86_400_000;
  const groups: { label: "today" | "thisWeek" | "older"; items: Conv[] }[] = [
    { label: "today",    items: [] },
    { label: "thisWeek", items: [] },
    { label: "older",    items: [] },
  ];
  for (const c of convs) {
    const age = now - new Date(c.updated_at).getTime();
    if (age < day)         groups[0].items.push(c);
    else if (age < 7*day)  groups[1].items.push(c);
    else                   groups[2].items.push(c);
  }
  return groups.filter(g => g.items.length > 0);
}

interface ChatTabProps {
  agents:          Agent[];
  projects:        Project[];
  initialAgentId?: string | null;
}

export function ChatTab({ agents, projects, initialAgentId }: ChatTabProps) {
  const { t } = useTranslation("ai");
  const toast = useToast();

  // ── Core state (unchanged) ────────────────────────────────────────
  const [projectId, setProjectId] = useState("demo");
  const [agentId, setAgentId]     = useState<string>(initialAgentId ?? "default");

  // Layout state
  const [contextPanelOpen, setContextPanelOpen] = useState(true);

  const {
    data: convs = [], status: convsStatus, error: convsError, suggestedFix: convsFix, refetch: loadConvs,
  } = useAsyncData(() => apiJSON<Conv[]>(`/api/conversations?project_id=${projectId}`), [projectId]);

  const [activeConv, setActiveConv]         = useState<string | null>(null);
  // Local, mutable copy of the active conversation's messages. Backed by
  // useAsyncData below for the *load* — but sendMessage() must keep
  // appending/streaming tokens into this directly, which a hook whose only
  // externally-owned value is `data` can't support, so loaded history is
  // synced in via effect rather than read straight from the hook.
  const [messages, setMessages]             = useState<Message[]>([]);
  // Which conversation `messages` actually holds content for. Lets the UI
  // tell "switching to a different, not-yet-loaded past conversation"
  // (messagesConvId out of sync with activeConv -> show a spinner, don't
  // flash the old conversation's messages) apart from "sendMessage() just
  // created a brand-new conversation mid-stream" (messagesConvId is set to
  // the new id immediately, in the same handler that flips activeConv, so
  // the in-progress streamed reply is never hidden behind a loading state).
  const [messagesConvId, setMessagesConvId] = useState<string | null>(null);
  const [prompt, setPrompt]                 = useState("");
  const [streaming, setStreaming]           = useState(false);
  const [searchQ, setSearchQ]               = useState("");
  // Same local-copy-synced-from-hook pattern as messages: setTaskStatus
  // optimistically mutates this list, which a hook-owned `data` can't allow.
  const [inlineTasks, setInlineTasks]       = useState<Task[]>([]);
  const [extracting, setExtracting]         = useState(false);
  const [showTasks, setShowTasks]           = useState(false);
  const [exporting, setExporting]           = useState(false);
  // Track *which* conversation/task is in flight so only that row's control
  // disables — an unrelated conversation's delete button, or a different
  // task's checkbox, must stay clickable while another one is in flight.
  const [deletingIds, setDeletingIds]       = useState<Set<string>>(new Set());
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
    { enabled: !!activeConv, isEmpty: () => false },
  );
  // Sync loaded history into the local, streaming-mutable copy.
  useEffect(() => {
    if (!loadedMessages) return;
    void Promise.resolve().then(() => {
      setMessages(loadedMessages);
      setMessagesConvId(activeConv);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadedMessages]);

  // ── Actions (unchanged logic) ─────────────────────────────────────

  async function extractTasks() {
    if (!activeConv || extracting) return;
    setExtracting(true);
    try {
      const path = `/api/tasks/from-conversation/${activeConv}`;
      const d = await apiJSON<{ created?: unknown[] }>(path, { method: "POST" });
      const n = d.created?.length ?? 0;
      toast(n > 0 ? t("chatTab.toast.extractedTasks", { count: n }) : t("chatTab.toast.noTasksFound"), n > 0 ? "ok" : "info");
      if (n > 0) { setShowTasks(true); loadInlineTasks(); }
    } catch (err) {
      toast(describeError(err, t("chatTab.toast.extractTasksFailed")), "err");
    } finally {
      setExtracting(false);
    }
  }

  async function setTaskStatus(task: Task, status: string) {
    if (pendingTaskIds.has(task.id)) return;
    setPendingTaskIds(prev => new Set(prev).add(task.id));
    setInlineTasks(prev => prev.map(x => x.id === task.id ? { ...x, status: status as Task["status"] } : x));
    try {
      await apiFetch(`/api/tasks/${task.id}`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status }),
      });
    } catch (err) {
      toast(describeError(err, t("chatTab.toast.updateTaskFailed")), "err");
      loadInlineTasks();
    } finally {
      setPendingTaskIds(prev => { const next = new Set(prev); next.delete(task.id); return next; });
    }
  }

  async function deleteConv(e: React.SyntheticEvent, cid: string) {
    e.stopPropagation();
    if (deletingIds.has(cid)) return;
    setDeletingIds(prev => new Set(prev).add(cid));
    try {
      const r = await apiFetch(`/api/conversations/${cid}`, { method: "DELETE" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      if (activeConv === cid) { setActiveConv(null); setMessages([]); }
      loadConvs();
    } catch (err) {
      toast(describeError(err, t("chatTab.toast.deleteConversationFailed")), "err");
    } finally {
      setDeletingIds(prev => { const next = new Set(prev); next.delete(cid); return next; });
    }
  }

  async function exportConv() {
    if (!activeConv || exporting) return;
    setExporting(true);
    try {
      const r = await apiFetch(`/api/export/conversations/${activeConv}`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const blob = await r.blob();
      const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "conversation.md"; a.click();
      URL.revokeObjectURL(a.href);
      toast(t("chatTab.toast.exportedMarkdown"));
    } catch (err) {
      toast(describeError(err, t("chatTab.toast.exportFailed")), "err");
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
    const url = useAgent ? `${API}/api/agents/${agentId}/chat/stream` : `${API}/api/run/stream`;

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
          else if (ev.type === "error")  { setMessages(p => p.map(m => m.id === assistantId ? { ...m, content: t("chatTab.messages.streamErrorPrefix", { message: ev.message }) } : m)); closed = true; break; }
          else if (ev.type === "done")   { loadConvs(); closed = true; }
        }
        if (closed) break;
      }
    } catch (err: unknown) {
      if ((err as Error).name !== "AbortError") {
        const msg = (err as Error).message ?? "";
        setMessages(p => p.map(m => m.id === assistantId ? { ...m, content: msg.includes("fetch") ? t("chatTab.toast.backendOffline") : t("chatTab.messages.streamErrorPrefix", { message: msg }) } : m));
      }
    } finally { setStreaming(false); abortRef.current = null; }
  }

  // ── Derived state ─────────────────────────────────────────────────
  const filteredConvs = useMemo(
    () => searchQ ? convs.filter(c => c.title.toLowerCase().includes(searchQ.toLowerCase())) : convs,
    [convs, searchQ],
  );
  const groupedConvs = useMemo(() => groupConvsByDate(filteredConvs), [filteredConvs]);
  const activeAgent  = useMemo(() => agents.find(a => a.id === agentId), [agents, agentId]);

  // True only while `messages` genuinely doesn't reflect activeConv yet.
  const messagesOutOfSync  = !!activeConv && messagesConvId !== activeConv;
  const showMessagesLoading = messagesOutOfSync && messagesStatus === "loading";
  const showMessagesError   = messagesOutOfSync && messagesStatus === "error";

  // Active project label
  const activeProjectName = projectId === "demo"
    ? t("chatTab.sidebar.demoProject")
    : (projects.find(p => p.id === projectId)?.name ?? projectId);

  // ── Render ────────────────────────────────────────────────────────
  return (
    <div className="chat-layout">

      {/* ═══════════════════════════════════════════════════════════
          COLUMN 1 — Conversation Rail
          ════════════════════════════════════════════════════════ */}
      <aside className="chat-rail" aria-label={t("chatTab.sidebar.loading")}>

        {/* Top controls */}
        <div className="chat-rail__top">
          <GoldButton
            onClick={() => { setActiveConv(null); setMessages([]); setMessagesConvId(null); setShowTasks(false); }}
            style={{ fontSize: 12 }}
          >
            {t("chatTab.sidebar.newChat")}
          </GoldButton>

          <input
            value={searchQ}
            onChange={e => setSearchQ(e.target.value)}
            placeholder={t("chatTab.sidebar.searchPlaceholder")}
            className="g-input"
            aria-label={t("chatTab.sidebar.searchPlaceholder")}
            style={{ fontSize: 12, padding: "6px 10px" }}
          />

          <select
            value={projectId}
            onChange={e => setProjectId(e.target.value)}
            className="g-input"
            aria-label={t("chatTab.contextPanel.project")}
            style={{ fontSize: 12, padding: "6px 10px" }}
          >
            <option value="demo">{t("chatTab.sidebar.demoProject")}</option>
            {projects.filter(p => p.id !== "00000000-0000-0000-0000-000000000001").map(p => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>

          <select
            value={agentId}
            onChange={e => setAgentId(e.target.value)}
            className="g-input"
            aria-label={t("chatTab.contextPanel.activeAgent")}
            style={{ fontSize: 12, padding: "6px 10px" }}
          >
            <option value="default">{t("chatTab.sidebar.defaultAgent")}</option>
            {agents.map(a => <option key={a.id} value={a.id}>{a.avatar} {a.name}</option>)}
          </select>
        </div>

        {/* Conversation list */}
        <div className="chat-rail__scroll">
          {convsStatus === "loading" && <LoadingSpinner label={t("chatTab.sidebar.loading")} />}
          {convsStatus === "error" && (
            <ErrorState compact message={convsError ?? t("chatTab.sidebar.loadError")} suggestedFix={convsFix} onRetry={loadConvs} />
          )}
          {convsStatus === "empty" && (
            <EmptyState compact title={t("chatTab.sidebar.emptyTitle")} description={t("chatTab.sidebar.emptyDesc")} />
          )}
          {(convsStatus === "success" || convsStatus === "refreshing") && filteredConvs.length === 0 && searchQ && (
            <EmptyState compact title={t("chatTab.sidebar.noMatchesTitle")} description={t("chatTab.sidebar.noMatchesDesc", { query: searchQ })} />
          )}

          {groupedConvs.map(({ label, items }) => (
            <div key={label}>
              <div className="conv-group-label">{t(`chatTab.convGroups.${label}`)}</div>
              {items.map(c => {
                const isDeleting = deletingIds.has(c.id);
                return (
                  <div
                    key={c.id}
                    role="button"
                    className={`conv-item${c.id === activeConv ? " active" : ""}`}
                    tabIndex={0}
                    aria-label={c.title}
                    aria-current={c.id === activeConv ? "page" : undefined}
                    onClick={() => { if (!isDeleting) setActiveConv(c.id); }}
                    onKeyDown={e => {
                      if (!isDeleting && (e.key === "Enter" || e.key === " ")) {
                        e.preventDefault(); setActiveConv(c.id);
                      }
                    }}
                    style={isDeleting ? { opacity: 0.5, pointerEvents: "none" } : undefined}
                  >
                    <div className="conv-item__title">{c.title}</div>
                    <span className="conv-item__time">{relTime(c.updated_at)}</span>
                    <button
                      className="conv-item__del"
                      onClick={e => { if (!isDeleting) void deleteConv(e, c.id); }}
                      aria-label={isDeleting ? t("chatTab.sidebar.deleting") : t("chatTab.sidebar.deleteConversation")}
                      title={isDeleting ? t("chatTab.sidebar.deleting") : t("chatTab.sidebar.deleteConversation")}
                    >
                      {isDeleting ? "…" : "✕"}
                    </button>
                  </div>
                );
              })}
            </div>
          ))}

          {convsStatus === "refreshing" && (
            <div style={{ padding: "8px", textAlign: "center" }}>
              <LoadingSpinner size={14} label="" />
            </div>
          )}
        </div>
      </aside>

      {/* ═══════════════════════════════════════════════════════════
          COLUMN 2 — Main Chat
          ════════════════════════════════════════════════════════ */}
      <div className="chat-main">

        {/* Toolbar */}
        <div className="chat-toolbar" role="toolbar" aria-label="Chat controls">
          <span style={{ fontSize: 16 }}>{activeAgent?.avatar ?? "🤖"}</span>
          <span style={{ fontSize: 12, fontWeight: 500, color: "var(--t2)" }}>
            {activeAgent?.name ?? t("chatTab.contextPanel.defaultAgent")}
          </span>
          {activeConv && (
            <span style={{
              fontSize: 10, fontWeight: 600, color: "var(--ta)",
              background: "var(--accent-dim)", border: "1px solid var(--accent-border)",
              borderRadius: "var(--r-full)", padding: "2px 8px", letterSpacing: "0.04em",
            }}>
              {activeProjectName}
            </span>
          )}
          <div className="chat-toolbar__spacer" />

          {/* Context panel toggle */}
          <button
            className={`chat-icon-btn${contextPanelOpen ? " active" : ""}`}
            onClick={() => setContextPanelOpen(p => !p)}
            aria-label={contextPanelOpen ? t("chatTab.contextPanel.hidePanel") : t("chatTab.contextPanel.showPanel")}
            title={contextPanelOpen ? t("chatTab.contextPanel.hidePanel") : t("chatTab.contextPanel.showPanel")}
            aria-pressed={contextPanelOpen}
          >
            {/* Side-panel icon */}
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <rect x="3" y="3" width="18" height="18" rx="2"/>
              <line x1="15" y1="3" x2="15" y2="21"/>
            </svg>
          </button>
        </div>

        {/* Inline tasks strip */}
        {showTasks && (inlineTasksStatus === "loading" || inlineTasksStatus === "error" || inlineTasks.length > 0) && (
          <div style={{ padding: "10px 16px", borderBottom: "1px solid var(--border)", background: "var(--accent-dim)", display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
            <span style={{ fontSize: 11, fontWeight: 600, color: "var(--ta)", flexShrink: 0 }}>{t("chatTab.tasksBar.label")}</span>
            {inlineTasksStatus === "loading" && <LoadingSpinner size={14} label="" />}
            {inlineTasksStatus === "error" && (
              <ErrorState compact message={inlineTasksError ?? t("chatTab.tasksBar.loadError")} suggestedFix={inlineTasksFix} onRetry={loadInlineTasks} />
            )}
            {inlineTasksStatus !== "loading" && inlineTasksStatus !== "error" && inlineTasks.map(task => {
              const isPending = pendingTaskIds.has(task.id);
              return (
                <div key={task.id} style={{ display: "flex", alignItems: "center", gap: 6, padding: "4px 10px", borderRadius: 20, background: "var(--bg-hover)", border: "1px solid var(--border)", fontSize: 12, opacity: isPending ? 0.6 : 1 }}>
                  <button
                    onClick={() => void setTaskStatus(task, task.status === "done" ? "pending" : "done")}
                    disabled={isPending}
                    aria-label={task.status === "done" ? "Mark pending" : "Mark done"}
                    style={{ background: "none", border: "none", cursor: isPending ? "default" : "pointer", padding: 0, color: task.status === "done" ? "var(--green)" : "var(--t5)", display: "flex" }}
                  >
                    {task.status === "done"
                      ? <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" aria-hidden="true"><polyline points="20 6 9 17 4 12"/></svg>
                      : <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><circle cx="12" cy="12" r="9"/></svg>}
                  </button>
                  <span style={{ color: task.status === "done" ? "var(--t5)" : "var(--t2)", textDecoration: task.status === "done" ? "line-through" : "none" }}>{task.title}</span>
                  <span style={{ width: 6, height: 6, borderRadius: "50%", background: PRIORITY_COLOR[task.priority], flexShrink: 0 }} title={task.priority} />
                </div>
              );
            })}
            <button
              onClick={() => setShowTasks(false)}
              aria-label="Close tasks"
              style={{ background: "none", border: "none", color: "var(--t5)", cursor: "pointer", marginInlineStart: "auto", fontSize: 16 }}
            >×</button>
          </div>
        )}

        {/* Messages area */}
        <div style={{ flex: 1, overflowY: "auto", padding: "32px 0", display: "flex", flexDirection: "column", gap: 0, position: "relative" }}>
          {showMessagesLoading && <LoadingSpinner fullPage label={t("chatTab.messages.loading")} />}
          {showMessagesError && (
            <ErrorState message={messagesError ?? t("chatTab.messages.loadError")} suggestedFix={messagesFix} onRetry={reloadMessages} />
          )}

          {/* Empty state */}
          {!showMessagesLoading && !showMessagesError && messages.length === 0 && (
            <div style={{ margin: "auto", textAlign: "center", color: "var(--t5)", paddingBottom: 80, animation: "fadeIn .4s ease" }}>
              <div style={{ width: 72, height: 72, borderRadius: 20, margin: "0 auto 16px", background: "var(--accent-dim)", border: "1px solid var(--accent-border)", display: "flex", alignItems: "center", justifyContent: "center" }}>
                {activeAgent ? <span style={{ fontSize: 32 }}>{activeAgent.avatar}</span> : <AxonLogo size={40} />}
              </div>
              <div style={{ fontSize: 20, fontWeight: 700, color: "var(--t1)", letterSpacing: "-.4px" }}>
                {activeAgent ? activeAgent.name : t("chatTab.messages.emptyAgentName")}
              </div>
              <div style={{ fontSize: 14, color: "var(--t4)", maxWidth: 320, lineHeight: 1.65, marginTop: 6 }}>
                {activeAgent?.description ?? t("chatTab.messages.emptyDescription")}
              </div>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", justifyContent: "center", marginTop: 16 }}>
                {[
                  t("chatTab.messages.suggestion1"),
                  t("chatTab.messages.suggestion2"),
                  t("chatTab.messages.suggestion3"),
                  t("chatTab.messages.suggestion4"),
                ].map(s => (
                  <GoldButton key={s} variant="ghost" onClick={() => setPrompt(s)} style={{ fontSize: 12, padding: "6px 14px" }}>{s}</GoldButton>
                ))}
              </div>
            </div>
          )}

          {/* Message rows — suppressed while a *different* conversation's history
              is loading/erroring to avoid flashing old content beneath the state. */}
          {!showMessagesLoading && !showMessagesError && messages.map((m, idx) => (
            <MessageRow
              key={m.id}
              msg={m}
              isLast={idx === messages.length - 1}
              agentName={activeAgent?.name ?? null}
              agentAvatar={activeAgent?.avatar ?? null}
            />
          ))}
          <div ref={bottomRef} />
        </div>

        {/* Composer */}
        <div style={{ padding: "10px 16px 14px", borderTop: "1px solid var(--border)", background: "var(--bg-surface)", flexShrink: 0 }}>
          <textarea
            value={prompt}
            onChange={e => setPrompt(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void sendMessage(); } }}
            placeholder={t("chatTab.input.placeholder")}
            className="g-input"
            rows={2}
            aria-label={t("chatTab.input.placeholder")}
            style={{ width: "100%", maxHeight: 160, resize: "none", marginBottom: 8 }}
          />
          <div style={{ display: "flex", justifyContent: "flex-end", gap: 6 }}>
            {streaming ? (
              <GoldButton
                variant="danger"
                onClick={() => abortRef.current?.abort()}
                aria-label={t("chatTab.input.stop")}
                style={{ height: 36, paddingInline: 16, fontSize: 13 }}
              >
                ■ {t("chatTab.input.stop")}
              </GoldButton>
            ) : (
              <GoldButton
                onClick={() => void sendMessage()}
                disabled={!prompt.trim()}
                aria-label={t("chatTab.input.send")}
                style={{ height: 36, paddingInline: 16, fontSize: 13 }}
              >
                {t("chatTab.input.send")} ↑
              </GoldButton>
            )}
          </div>
        </div>
      </div>

      {/* ═══════════════════════════════════════════════════════════
          COLUMN 3 — Context Panel (collapsible)
          ════════════════════════════════════════════════════════ */}
      {contextPanelOpen && (
        <aside className="chat-context" aria-label={t("chatTab.contextPanel.title")}>
          <div className="chat-context__header">
            <span className="chat-context__title">{t("chatTab.contextPanel.title")}</span>
            <button
              className="chat-icon-btn"
              onClick={() => setContextPanelOpen(false)}
              aria-label={t("chatTab.contextPanel.hidePanel")}
              title={t("chatTab.contextPanel.hidePanel")}
              style={{ width: 24, height: 24, fontSize: 14, border: "none" }}
            >×</button>
          </div>

          <div className="chat-context__body">
            {/* Active agent */}
            <div>
              <div className="chat-context__section-label">{t("chatTab.contextPanel.activeAgent")}</div>
              <div className="chat-context__agent-card">
                <div className="chat-context__agent-avatar">
                  {activeAgent?.avatar ?? "🤖"}
                </div>
                <div style={{ minWidth: 0 }}>
                  <div className="chat-context__agent-name">
                    {activeAgent?.name ?? t("chatTab.contextPanel.defaultAgent")}
                  </div>
                  {activeAgent?.description && (
                    <div className="chat-context__agent-desc">{activeAgent.description}</div>
                  )}
                </div>
              </div>
            </div>

            {/* Current project */}
            <div>
              <div className="chat-context__section-label">{t("chatTab.contextPanel.project")}</div>
              <span style={{
                fontSize: 12, color: "var(--t1)",
                padding: "4px 10px", borderRadius: "var(--r-full)",
                background: "var(--accent-dim)", border: "1px solid var(--accent-border)",
                display: "inline-block",
              }}>
                {activeProjectName}
              </span>
            </div>

            {/* Actions — only shown when a conversation is active */}
            {activeConv && (
              <div>
                <div className="chat-context__section-label">{t("chatTab.contextPanel.actions")}</div>
                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  <button
                    className="chat-context__action-btn"
                    onClick={() => void exportConv()}
                    disabled={exporting}
                    title={t("chatTab.sidebar.exportTitle")}
                  >
                    {/* Download icon */}
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                      <polyline points="7 10 12 15 17 10"/>
                      <line x1="12" y1="15" x2="12" y2="3"/>
                    </svg>
                    {exporting ? "…" : t("chatTab.contextPanel.export")}
                  </button>
                  <button
                    className="chat-context__action-btn"
                    onClick={() => void extractTasks()}
                    disabled={extracting}
                    title={t("chatTab.sidebar.extractTasksTitle")}
                  >
                    {/* Check icon */}
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                      <polyline points="20 6 9 17 4 12"/>
                    </svg>
                    {extracting ? "…" : t("chatTab.contextPanel.extractTasks")}
                  </button>
                </div>
              </div>
            )}
          </div>
        </aside>
      )}
    </div>
  );
}

// ── MessageRow ────────────────────────────────────────────────────────────────
// Memoized: during streaming only the last message's content changes —
// memo stops React re-rendering (and re-parsing markdown for) every earlier
// message on each streamed token.
const MessageRow = memo(function MessageRow({
  msg, isLast, agentName, agentAvatar,
}: {
  msg: Message; isLast: boolean; agentName: string | null; agentAvatar: string | null;
}) {
  const { t } = useTranslation("ai");
  const [copied, setCopied] = useState(false);

  function handleCopy() {
    void navigator.clipboard.writeText(msg.content).then(() => {
      setCopied(true);
      // Reset the "Copied!" indicator after 2 s so it's ready for re-use.
      const id = setTimeout(() => setCopied(false), 2000);
      return () => clearTimeout(id);
    });
  }

  const isUser = msg.role === "user";
  const rowStyle: CSSProperties = {
    display: "flex",
    gap: 14,
    alignItems: "flex-start",
    padding: "14px 24px",
    maxWidth: 900,
    width: "100%",
    animation: "slideIn .22s ease",
    ...(isUser ? { flexDirection: "row-reverse", alignSelf: "flex-end" } : {}),
  };

  return (
    <div style={rowStyle} className="msg-row">
      {/* Assistant avatar */}
      {!isUser && (
        <div style={{ width: 34, height: 34, borderRadius: 9, flexShrink: 0, background: "var(--accent-dim)", border: "1px solid var(--accent-border)", display: "flex", alignItems: "center", justifyContent: "center", marginTop: 2 }}>
          <span style={{ fontSize: 18 }}>{agentAvatar ?? "◈"}</span>
        </div>
      )}

      <div style={{ flex: 1, minWidth: 0 }}>
        {/* Label + copy button */}
        <div style={{
          fontSize: 11, fontWeight: 600, marginBottom: 7,
          display: "flex", alignItems: "center", gap: 8,
          letterSpacing: "0.04em", textTransform: "uppercase",
          color: isUser ? "var(--t5)" : "var(--ta)",
          justifyContent: isUser ? "flex-end" : "flex-start",
        }}>
          {isUser ? t("chatTab.messages.you") : (agentName ?? t("chatTab.messages.assistantFallback"))}
          <span style={{ fontSize: 10, color: "var(--t5)", fontWeight: 400 }}>
            {isLast ? t("chatTab.messages.now") : ""}
          </span>
          {/* Copy button — shown on .msg-row hover via chat.css */}
          {msg.content && (
            <button
              className={`msg-copy-btn${copied ? " copied" : ""}`}
              onClick={handleCopy}
              aria-label={copied ? t("chatTab.messages.copied") : t("chatTab.messages.copyCode")}
            >
              {copied ? t("chatTab.messages.copied") : t("chatTab.messages.copyCode")}
            </button>
          )}
        </div>

        {/* Content */}
        {isUser ? (
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

      {/* User avatar */}
      {isUser && (
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
