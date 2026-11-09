/**
 * ChatTab — 3-column AI command center.
 *
 * Columns:
 *   1. Conversation Rail (260px, collapsible on mobile)
 *   2. Main Chat (flex: 1) — toolbar, messages, composer
 *   3. Context Panel (280px, collapsible)
 *
 * Phase A reliability guarantees (see tests/test_chat_persistence_phase_a.py
 * and features/ai/chat/chatSession.ts):
 *   - The open project/conversation is restored after a reload (per user).
 *   - The composer draft is stored separately from messages and is cleared
 *     only after the server confirms the message was saved, so a failed send
 *     never loses text.
 *   - Every logical send carries a stable client_request_id; Retry reuses it,
 *     so the server never stores a duplicate message or re-runs a finished reply.
 *   - A stream belongs to the conversation it was started in. Switching
 *     conversations/projects detaches it (it keeps running and is saved
 *     server-side) instead of writing tokens into the newly opened chat, and
 *     a history load never overwrites a reply that is still streaming.
 *   - Prompt length uses the same limit as the server, shown before sending.
 *
 * RTL is handled via CSS logical properties in chat.css and
 * `marginInlineStart` etc. in inline styles.
 */
import { useState, useRef, useEffect, useMemo, memo, type CSSProperties } from "react";
import ReactMarkdown from "react-markdown";
import { useTranslation } from "react-i18next";
import { useToast } from "../../../contexts/toast";
import { useAuth } from "../../../contexts/AuthContext";
import { apiFetch, apiJSON, APIError } from "../../../utils/api";
import { relTime } from "../../../utils/time";
import { copyText } from "../../../shared/utils/clipboard";
import { MD_COMPONENTS } from "../../../shared/ui/md-components";
import { useAsyncData } from "../../../shared/hooks/useAsyncData";
import { clearAssistantHandoff, peekAssistantHandoff } from "../../../shared/utils/assistantHandoff";
import { LoadingSpinner } from "../../../shared/ui/LoadingSpinner";
import { ErrorState, EmptyState } from "../../../shared/ui/StateViews";
import { GoldButton } from "../../../shared/ui/gold";
import AxonLogo from "../../../AxonLogo";
import type { Message, MessageStatus, Conv, Project, Agent, Task } from "../../../types";
import { PRIORITY_COLOR } from "../../../constants";
import {
  DEFAULT_LIMITS, carryOverErrors, clearDraft, countChars, describeSendFailure, getDraft, limitState,
  loadSession, parseLimits, parseSseBuffer, saveSession, setDraft, type ChatLimits,
} from "../chat/chatSession";
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

function isNarrow(px: number): boolean {
  try { return window.matchMedia(`(max-width: ${px}px)`).matches; } catch { return false; }
}

/** Map a stored message row to the UI shape, carrying its delivery status. */
function fromServer(m: { id: string; role: string; content: string; status?: string; client_request_id?: string | null }): Message {
  const role = m.role === "assistant" ? "assistant" : "user";
  let status: MessageStatus;
  if (m.status === "partial") status = "partial";
  else if (m.status === "failed") status = "failed";
  else status = role === "user" ? "saved" : "complete";
  return { id: m.id, role, content: m.content, status, requestId: m.client_request_id ?? null };
}

/** A stream in flight. `attached` is false once the user navigated away from it. */
interface LiveStream {
  requestId: string;
  convId: string | null;
  ctrl: AbortController;
  attached: boolean;
}

interface ChatTabProps {
  agents:          Agent[];
  projects:        Project[];
  initialAgentId?: string | null;
}

export function ChatTab({ agents, projects, initialAgentId }: ChatTabProps) {
  const { t, i18n } = useTranslation("ai");
  const toast = useToast();
  const { user } = useAuth();
  const userId = user?.id ?? null;

  // ── Core state ────────────────────────────────────────────────────
  // Restored from the last session for this user; the server re-validates.
  const [projectId, setProjectId] = useState(() => loadSession(userId).projectId);
  const [agentId, setAgentId]     = useState<string>(initialAgentId ?? "default");

  // Layout state. On narrow screens the context panel is an overlay, so it
  // starts closed there; the conversation rail is a drawer on phones.
  const [contextPanelOpen, setContextPanelOpen] = useState(() => !isNarrow(1100));
  const [railOpen, setRailOpen]                 = useState(false);
  const railToggleRef = useRef<HTMLButtonElement>(null);
  const railRef       = useRef<HTMLElement>(null);

  // Rail: server-side search (title + message content) and archive view.
  const [searchQ, setSearchQ]           = useState("");
  const [debouncedQ, setDebouncedQ]     = useState("");
  const [showArchived, setShowArchived] = useState(false);
  useEffect(() => {
    const id = setTimeout(() => setDebouncedQ(searchQ.trim()), 250);
    return () => clearTimeout(id);
  }, [searchQ]);

  const {
    data: convs = [], status: convsStatus, error: convsError, suggestedFix: convsFix, refetch: loadConvs,
  } = useAsyncData(
    () => {
      const qs = new URLSearchParams({ project_id: projectId });
      if (debouncedQ) qs.set("q", debouncedQ);
      if (showArchived) qs.set("archived", "true");
      return apiJSON<Conv[]>(`/api/conversations?${qs.toString()}`);
    },
    [projectId, debouncedQ, showArchived],
  );

  const [activeConv, setActiveConv]         = useState<string | null>(() => loadSession(userId).convId);
  // Local, mutable copy of the active conversation's messages (streaming
  // tokens are appended here); loaded history is synced in via effect.
  const [messages, setMessages]             = useState<Message[]>([]);
  // Which conversation `messages` actually holds content for — lets the UI
  // show a spinner while a different conversation loads, but never over a
  // reply that is streaming into a just-created conversation.
  const [messagesConvId, setMessagesConvId] = useState<string | null>(null);

  // Draft: a question handed over from another page (Home's "Ask Flow")
  // wins once; otherwise the saved draft for this conversation.
  const [prompt, setPromptState] = useState(() => peekAssistantHandoff() || getDraft(userId, loadSession(userId).projectId, loadSession(userId).convId));
  useEffect(() => { clearAssistantHandoff(); }, []);
  /** User typing — updates the composer and the stored draft. */
  function editPrompt(v: string) {
    setPromptState(v);
    setDraft(userId, projectId, activeConv, v);
    if (sendError) setSendError(null);
  }

  const [streaming, setStreaming]           = useState(false);
  const [sendError, setSendError]           = useState<string | null>(null);
  // Polite screen-reader announcements for state changes (never per token).
  const [announcement, setAnnouncement]     = useState("");
  const [limits, setLimits]                 = useState<ChatLimits>(DEFAULT_LIMITS);
  // Same local-copy-synced-from-hook pattern as messages: setTaskStatus
  // optimistically mutates this list, which a hook-owned `data` can't allow.
  const [inlineTasks, setInlineTasks]       = useState<Task[]>([]);
  const [extracting, setExtracting]         = useState(false);
  const [showTasks, setShowTasks]           = useState(false);
  const [exporting, setExporting]           = useState(false);
  // Per-row in-flight tracking so only that row's control disables.
  const [deletingIds, setDeletingIds]       = useState<Set<string>>(new Set());
  const [pendingTaskIds, setPendingTaskIds] = useState<Set<string>>(new Set());
  const [busyConvIds, setBusyConvIds]       = useState<Set<string>>(new Set());
  const [renamingId, setRenamingId]         = useState<string | null>(null);
  const [renameValue, setRenameValue]       = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);
  const liveRef   = useRef<LiveStream | null>(null);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages]);

  // Lets global CSS keep the floating copilot button off the Send button.
  useEffect(() => {
    document.body.classList.add("flow-chat-open");
    return () => document.body.classList.remove("flow-chat-open");
  }, []);

  // Escape closes whichever overlay is open (drawer first).
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key !== "Escape") return;
      if (railOpen) { setRailOpen(false); railToggleRef.current?.focus(); }
      else if (contextPanelOpen && isNarrow(1100)) setContextPanelOpen(false);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [railOpen, contextPanelOpen]);

  // Move focus into the drawer when it opens on a phone.
  useEffect(() => {
    if (railOpen) railRef.current?.querySelector<HTMLElement>("button, input, select")?.focus();
  }, [railOpen]);

  // Shared limit with the server — fetched once; defaults until it answers.
  useEffect(() => {
    let cancelled = false;
    apiJSON<unknown>("/api/chat/limits")
      .then(raw => { if (!cancelled) setLimits(parseLimits(raw)); })
      .catch(() => { /* keep defaults — the server still enforces its own limit */ });
    return () => { cancelled = true; };
  }, []);

  // Remember the open project/conversation for the next visit.
  useEffect(() => {
    saveSession(userId, { projectId, convId: activeConv });
  }, [userId, projectId, activeConv]);

  // A restored conversation that no longer exists (deleted, or belongs to a
  // different account on this browser) is dropped instead of showing an error.
  const [restoredConvId] = useState(activeConv);
  useEffect(() => {
    if (!restoredConvId) return;
    apiJSON<Conv>(`/api/conversations/${restoredConvId}`).catch(err => {
      if (err instanceof APIError && err.details.status === 404) {
        setActiveConv(cur => (cur === restoredConvId ? null : cur));
      }
    });
  }, [restoredConvId]);

  const {
    data: loadedTasks, status: inlineTasksStatus, error: inlineTasksError,
    suggestedFix: inlineTasksFix, refetch: loadInlineTasks,
  } = useAsyncData(
    () => apiJSON<{ tasks?: Task[] }>(`/api/tasks?conversation_id=${activeConv}&sort=created_at`).then(d => (d.tasks ?? []).slice(0, 6)),
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
      const msgs = await apiJSON<{ id: string; role: string; content: string; status?: string; client_request_id?: string | null }[]>(path);
      return msgs.map(fromServer);
    },
    [activeConv],
    { enabled: !!activeConv, isEmpty: () => false },
  );
  // Sync loaded history into the local copy — except while a reply is
  // streaming into this same conversation: the DB doesn't have the reply
  // yet, and replacing local state would erase the bubble mid-stream.
  useEffect(() => {
    if (!loadedMessages) return;
    const conv = activeConv;
    void Promise.resolve().then(() => {
      const live = liveRef.current;
      if (live && live.attached && live.convId === conv) return;
      // Keep failure reasons the client already showed for these messages.
      setMessages(prev => carryOverErrors(loadedMessages, prev));
      setMessagesConvId(conv);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadedMessages]);

  // ── Navigation (always detaches a running stream first) ───────────

  function detachStream() {
    const live = liveRef.current;
    if (live) { live.attached = false; liveRef.current = null; }
    setStreaming(false);
  }

  function openConversation(convId: string | null) {
    setRailOpen(false);
    if (convId === activeConv && convId !== null) return;
    detachStream();
    setActiveConv(convId);
    setMessages([]);
    setMessagesConvId(null);
    setShowTasks(false);
    setSendError(null);
    setPromptState(getDraft(userId, projectId, convId));
  }

  function openProject(pid: string) {
    if (pid === projectId) return;
    detachStream();
    setProjectId(pid);
    setActiveConv(null);
    setMessages([]);
    setMessagesConvId(null);
    setShowTasks(false);
    setSendError(null);
    setPromptState(getDraft(userId, pid, null));
  }

  // ── Actions ───────────────────────────────────────────────────────

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
      const response = await apiFetch(`/api/tasks/${task.id}`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status }),
      });
      if (!response.ok) throw new Error(t("chatTab.toast.updateTaskFailed"));
    } catch (err) {
      toast(describeError(err, t("chatTab.toast.updateTaskFailed")), "err");
      loadInlineTasks();
    } finally {
      setPendingTaskIds(prev => { const next = new Set(prev); next.delete(task.id); return next; });
    }
  }

  async function deleteConv(cid: string, title: string) {
    if (deletingIds.has(cid)) return;
    if (!window.confirm(t("chatTab.sidebar.confirmDelete", { title }))) return;
    setDeletingIds(prev => new Set(prev).add(cid));
    try {
      const r = await apiFetch(`/api/conversations/${cid}`, { method: "DELETE" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      clearDraft(userId, projectId, cid);
      if (activeConv === cid) openConversation(null);
      loadConvs();
    } catch (err) {
      toast(describeError(err, t("chatTab.toast.deleteConversationFailed")), "err");
    } finally {
      setDeletingIds(prev => { const next = new Set(prev); next.delete(cid); return next; });
    }
  }

  async function patchConv(cid: string, body: { title?: string; archived?: boolean }, failKey: string): Promise<boolean> {
    if (busyConvIds.has(cid)) return false;
    setBusyConvIds(prev => new Set(prev).add(cid));
    try {
      await apiJSON<Conv>(`/api/conversations/${cid}`, { method: "PATCH", body: JSON.stringify(body) });
      loadConvs();
      return true;
    } catch (err) {
      toast(describeError(err, t(failKey)), "err");
      return false;
    } finally {
      setBusyConvIds(prev => { const next = new Set(prev); next.delete(cid); return next; });
    }
  }

  function startRename(c: Conv) {
    setRenamingId(c.id);
    setRenameValue(c.title);
  }

  async function commitRename() {
    const cid = renamingId;
    if (!cid) return;
    const title = renameValue.trim();
    const original = convs.find(c => c.id === cid)?.title;
    setRenamingId(null);
    if (!title || title === original) return;
    await patchConv(cid, { title }, "chatTab.toast.renameFailed");
  }

  async function toggleArchive(c: Conv) {
    const archive = !c.archived;
    const ok = await patchConv(c.id, { archived: archive }, "chatTab.toast.archiveFailed");
    if (!ok) return;
    toast(t(archive ? "chatTab.toast.archived" : "chatTab.toast.unarchived"), "ok");
    if (archive && activeConv === c.id) openConversation(null);
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

  /**
   * Send the composer text, or retry an earlier send with the SAME request id.
   * The server dedupes on that id, so retrying is always safe.
   */
  async function sendMessage(retryOf?: { requestId: string; text: string }) {
    if (streaming) return;
    const text = retryOf ? retryOf.text : prompt;
    if (!text.trim()) return;
    const length = countChars(text);
    if (length > limits.maxPromptChars) {
      setSendError(t("chatTab.input.overLimit", { count: length.toLocaleString(i18n.language), limit: limits.maxPromptChars.toLocaleString(i18n.language) }));
      return;
    }
    setSendError(null);

    const requestId     = retryOf?.requestId ?? crypto.randomUUID();
    const convAtSend    = activeConv;
    const projectAtSend = projectId;
    const ctrl          = new AbortController();
    const live: LiveStream = { requestId, convId: convAtSend, ctrl, attached: true };
    liveRef.current = live;
    setStreaming(true);

    const update = (role: Message["role"], fn: (m: Message) => Message) => {
      if (!live.attached) return;
      setMessages(prev => prev.map(m => (m.requestId === requestId && m.role === role ? fn(m) : m)));
    };
    const removeReply = () => {
      if (!live.attached) return;
      setMessages(prev => prev.filter(m => !(m.requestId === requestId && m.role === "assistant")));
    };

    setMessages(prev => {
      const base = retryOf
        ? prev
            .filter(m => !(m.requestId === requestId && m.role === "assistant"))
            .map(m => (m.requestId === requestId && m.role === "user" ? { ...m, status: "sending" as const, error: null } : m))
        : [...prev, { id: `${requestId}:user`, role: "user" as const, content: text, status: "sending" as const, requestId }];
      return [...base, { id: `${requestId}:reply`, role: "assistant" as const, content: "", status: "streaming" as const, requestId }];
    });
    // The composer empties now, but the stored draft stays until the server
    // confirms the message was saved (the `conv_id` ack below).
    if (!retryOf) setPromptState("");
    setAnnouncement(t("chatTab.status.sending"));

    const useAgent = agentId !== "default";
    const path = useAgent ? `/api/agents/${agentId}/chat/stream` : "/api/run/stream";
    let acked = false;
    let replyText = "";

    try {
      const res = await apiFetch(path, {
        method: "POST",
        body: JSON.stringify({
          project_id: projectAtSend, prompt: text, conversation_id: convAtSend,
          agent_id: agentId, client_request_id: requestId,
        }),
        signal: ctrl.signal,
      });

      if (!res.ok || !res.body) {
        const body = await res.json().catch(() => null);
        const info = describeSendFailure(res.status, body, i18n.language, t("chatTab.status.sendFailed"));
        if (live.attached) {
          removeReply();
          if (info.rejectedBeforeSave && !retryOf) {
            // Nothing was stored: take the bubble back and return the full
            // text to the composer with the reason.
            setMessages(prev => prev.filter(m => !(m.requestId === requestId && m.role === "user")));
            setPromptState(cur => (cur.trim() ? cur : text));
            setSendError(info.message);
          } else {
            update("user", m => ({ ...m, status: "failed", error: info.message }));
          }
          setAnnouncement(info.message);
        }
        return;
      }

      const reader  = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      let terminal = false;

      read: while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const { events, rest } = parseSseBuffer(buf);
        buf = rest;
        for (const ev of events) {
          if (ev.type === "conv_id") {
            acked = true;
            const cid = String(ev.conv_id);
            live.convId = cid;
            clearDraft(userId, projectAtSend, convAtSend);
            if (live.attached) {
              update("user", m => ({ ...m, status: "saved", error: null }));
              if (!convAtSend) {
                // Claim the id for the local messages before flipping
                // activeConv so the history load doesn't replace them.
                setMessagesConvId(cid);
                setActiveConv(cid);
              }
              setAnnouncement(t("chatTab.status.saved"));
            }
            loadConvs();
          } else if (ev.type === "delta") {
            replyText += String(ev.text ?? "");
            const snapshot = replyText;
            update("assistant", m => ({ ...m, content: snapshot }));
          } else if (ev.type === "error") {
            terminal = true;
            const msg = String(ev.message ?? t("chatTab.status.replyFailed"));
            update("assistant", m => ({ ...m, status: replyText ? "partial" : "failed", error: msg }));
            if (live.attached) setAnnouncement(t("chatTab.status.replyFailed"));
            break read;
          } else if (ev.type === "done") {
            terminal = true;
            update("assistant", m => ({ ...m, status: "complete", error: null }));
            if (live.attached) setAnnouncement(t("chatTab.status.replyDone"));
            loadConvs();
            break read;
          }
        }
      }
      if (!terminal) {
        // The connection closed without `done`/`error`: say so plainly.
        update("assistant", m => ({ ...m, status: replyText ? "partial" : "failed", error: t("chatTab.status.connectionLost") }));
        if (live.attached) setAnnouncement(t("chatTab.status.connectionLost"));
      }
    } catch (err: unknown) {
      const aborted = (err as Error)?.name === "AbortError";
      const reason = aborted ? t("chatTab.status.stopped") : t("chatTab.status.connectionLost");
      if (!acked && !aborted) {
        // Never reached the server (or no ack): the draft is still stored;
        // offer Retry (same request id — safe even if it did arrive).
        removeReply();
        update("user", m => ({ ...m, status: "failed", error: reason }));
      } else {
        update("assistant", m => ({ ...m, status: replyText ? "partial" : "failed", error: reason }));
        if (!acked) update("user", m => ({ ...m, status: "failed", error: reason }));
      }
      if (live.attached) setAnnouncement(reason);
    } finally {
      if (liveRef.current === live) { liveRef.current = null; setStreaming(false); }
      if (!live.attached) loadConvs();
    }
  }

  function retryMessage(m: Message) {
    if (streaming || !m.requestId) return;
    const userMsg = m.role === "user" ? m : messages.find(x => x.role === "user" && x.requestId === m.requestId);
    if (!userMsg) return;
    void sendMessage({ requestId: m.requestId, text: userMsg.content });
  }

  /** Move a failed, unconfirmed message back into the composer for editing. */
  function editFailed(m: Message) {
    setMessages(prev => prev.filter(x => x.requestId !== m.requestId));
    setPromptState(m.content);
    setDraft(userId, projectId, activeConv, m.content);
  }

  // ── Derived state ─────────────────────────────────────────────────
  const groupedConvs = useMemo(() => groupConvsByDate(convs), [convs]);
  const activeAgent  = useMemo(() => agents.find(a => a.id === agentId), [agents, agentId]);
  const userInitial  = (user?.name || user?.email || "?").trim().charAt(0).toUpperCase() || "?";

  // True only while `messages` genuinely doesn't reflect activeConv yet.
  const messagesOutOfSync  = !!activeConv && messagesConvId !== activeConv;
  const showMessagesLoading = messagesOutOfSync && messagesStatus === "loading";
  const showMessagesError   = messagesOutOfSync && messagesStatus === "error";

  const charCount = countChars(prompt);
  const limit     = limitState(charCount, limits);

  // Active project label
  const activeProjectName = projectId === "demo"
    ? t("chatTab.sidebar.demoProject")
    : (projects.find(p => p.id === projectId)?.name ?? projectId);

  // ── Render ────────────────────────────────────────────────────────
  return (
    <div className={`chat-layout${railOpen ? " chat-layout--rail-open" : ""}`}>
      {/* Polite status announcements — state changes only, never tokens. */}
      <div className="sr-only" role="status" aria-live="polite">{announcement}</div>

      {/* Tap-outside to close an overlay (drawer or narrow-screen context panel). */}
      <button
        type="button"
        tabIndex={-1}
        aria-hidden="true"
        className={`chat-overlay-backdrop${railOpen || contextPanelOpen ? " is-open" : ""}`}
        onClick={() => { setRailOpen(false); if (isNarrow(1100)) setContextPanelOpen(false); }}
      />

      {/* ═══════════════════════════════════════════════════════════
          COLUMN 1 — Conversation Rail
          ════════════════════════════════════════════════════════ */}
      <aside className="chat-rail" id="chat-rail" ref={railRef} aria-label={t("chatTab.sidebar.railLabel")}>

        {/* Top controls */}
        <div className="chat-rail__top">
          <GoldButton onClick={() => openConversation(null)} style={{ fontSize: 12 }}>
            {t("chatTab.sidebar.newChat")}
          </GoldButton>

          <input
            type="search"
            value={searchQ}
            onChange={e => setSearchQ(e.target.value)}
            placeholder={t("chatTab.sidebar.searchPlaceholder")}
            className="g-input"
            aria-label={t("chatTab.sidebar.searchLabel")}
            style={{ fontSize: 12, padding: "6px 10px" }}
          />

          <select
            value={projectId}
            onChange={e => openProject(e.target.value)}
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

          <button
            type="button"
            className="chat-rail__toggle"
            aria-pressed={showArchived}
            onClick={() => setShowArchived(v => !v)}
          >
            {showArchived ? t("chatTab.sidebar.showActive") : t("chatTab.sidebar.showArchived")}
          </button>
        </div>

        {/* Conversation list */}
        <div className="chat-rail__scroll">
          {convsStatus === "loading" && <LoadingSpinner label={t("chatTab.sidebar.loading")} />}
          {convsStatus === "error" && (
            <ErrorState compact message={convsError ?? t("chatTab.sidebar.loadError")} suggestedFix={convsFix} onRetry={loadConvs} />
          )}
          {convsStatus === "empty" && !debouncedQ && (
            showArchived
              ? <EmptyState compact title={t("chatTab.sidebar.archivedEmptyTitle")} description={t("chatTab.sidebar.archivedEmptyDesc")} />
              : <EmptyState compact title={t("chatTab.sidebar.emptyTitle")} description={t("chatTab.sidebar.emptyDesc")} />
          )}
          {convsStatus === "empty" && debouncedQ && (
            <EmptyState compact title={t("chatTab.sidebar.noMatchesTitle")} description={t("chatTab.sidebar.noMatchesDesc", { query: debouncedQ })} />
          )}

          {groupedConvs.map(({ label, items }) => (
            <div key={label} role="group" aria-label={t(`chatTab.convGroups.${label}`)}>
              <div className="conv-group-label" aria-hidden="true">{t(`chatTab.convGroups.${label}`)}</div>
              {items.map(c => {
                const isDeleting = deletingIds.has(c.id);
                const isBusy     = busyConvIds.has(c.id) || isDeleting;
                const isActive   = c.id === activeConv;
                if (renamingId === c.id) {
                  return (
                    <div key={c.id} className={`conv-item${isActive ? " active" : ""}`}>
                      <input
                        className="g-input"
                        value={renameValue}
                        maxLength={200}
                        aria-label={t("chatTab.sidebar.renameLabel")}
                        autoFocus
                        onChange={e => setRenameValue(e.target.value)}
                        onBlur={() => void commitRename()}
                        onKeyDown={e => {
                          if (e.key === "Enter") { e.preventDefault(); void commitRename(); }
                          if (e.key === "Escape") { e.preventDefault(); setRenamingId(null); }
                        }}
                        style={{ fontSize: 12, padding: "4px 8px", width: "100%" }}
                      />
                    </div>
                  );
                }
                return (
                  <div
                    key={c.id}
                    className={`conv-item${isActive ? " active" : ""}`}
                    style={isBusy ? { opacity: 0.5 } : undefined}
                  >
                    <button
                      type="button"
                      className="conv-item__main"
                      aria-current={isActive ? "page" : undefined}
                      disabled={isBusy}
                      onClick={() => openConversation(c.id)}
                    >
                      <span className="conv-item__title">{c.title}</span>
                      <span className="conv-item__time">{relTime(c.updated_at)}</span>
                    </button>
                    <div className="conv-item__actions">
                      <button
                        type="button"
                        className="conv-item__action"
                        disabled={isBusy}
                        onClick={() => startRename(c)}
                        aria-label={t("chatTab.sidebar.renameNamed", { title: c.title })}
                        title={t("chatTab.sidebar.rename")}
                      >✎</button>
                      <button
                        type="button"
                        className="conv-item__action"
                        disabled={isBusy}
                        onClick={() => void toggleArchive(c)}
                        aria-label={t(c.archived ? "chatTab.sidebar.unarchiveNamed" : "chatTab.sidebar.archiveNamed", { title: c.title })}
                        title={t(c.archived ? "chatTab.sidebar.unarchive" : "chatTab.sidebar.archive")}
                      >{c.archived ? "↺" : "⤓"}</button>
                      <button
                        type="button"
                        className="conv-item__action conv-item__action--danger"
                        disabled={isBusy}
                        onClick={() => void deleteConv(c.id, c.title)}
                        aria-label={isDeleting ? t("chatTab.sidebar.deleting") : t("chatTab.sidebar.deleteNamed", { title: c.title })}
                        title={isDeleting ? t("chatTab.sidebar.deleting") : t("chatTab.sidebar.deleteConversation")}
                      >{isDeleting ? "…" : "✕"}</button>
                    </div>
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
        <div className="chat-toolbar" role="toolbar" aria-label={t("chatTab.toolbarLabel")}>
          <button
            type="button"
            ref={railToggleRef}
            className="chat-icon-btn chat-rail-toggle"
            aria-expanded={railOpen}
            aria-controls="chat-rail"
            onClick={() => setRailOpen(v => !v)}
            aria-label={railOpen ? t("chatTab.sidebar.closeRail") : t("chatTab.sidebar.openRail")}
            title={railOpen ? t("chatTab.sidebar.closeRail") : t("chatTab.sidebar.openRail")}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
              <line x1="4" y1="6" x2="20" y2="6"/><line x1="4" y1="12" x2="20" y2="12"/><line x1="4" y1="18" x2="20" y2="18"/>
            </svg>
          </button>
          <span style={{ fontSize: 16 }} aria-hidden="true">{activeAgent?.avatar ?? "◈"}</span>
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
            type="button"
            className={`chat-icon-btn${contextPanelOpen ? " active" : ""}`}
            onClick={() => setContextPanelOpen(p => !p)}
            aria-label={contextPanelOpen ? t("chatTab.contextPanel.hidePanel") : t("chatTab.contextPanel.showPanel")}
            title={contextPanelOpen ? t("chatTab.contextPanel.hidePanel") : t("chatTab.contextPanel.showPanel")}
            aria-pressed={contextPanelOpen}
          >
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
                    type="button"
                    onClick={() => void setTaskStatus(task, task.status === "done" ? "pending" : "done")}
                    disabled={isPending}
                    aria-label={task.status === "done" ? t("chatTab.tasksBar.markPending", { title: task.title }) : t("chatTab.tasksBar.markDone", { title: task.title })}
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
              type="button"
              onClick={() => setShowTasks(false)}
              aria-label={t("chatTab.tasksBar.close")}
              style={{ background: "none", border: "none", color: "var(--t5)", cursor: "pointer", marginInlineStart: "auto", fontSize: 16 }}
            >×</button>
          </div>
        )}

        {/* Messages area */}
        <div
          style={{ flex: 1, overflowY: "auto", padding: "32px 0", display: "flex", flexDirection: "column", gap: 0, position: "relative" }}
          aria-busy={streaming}
        >
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
                  <GoldButton key={s} variant="ghost" onClick={() => editPrompt(s)} style={{ fontSize: 12, padding: "6px 14px" }}>{s}</GoldButton>
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
              awaitingReply={!streaming && m.role === "user" && idx === messages.length - 1 && m.status === "saved"}
              canRetry={!streaming && !!m.requestId}
              agentName={activeAgent?.name ?? null}
              agentAvatar={activeAgent?.avatar ?? null}
              userInitial={userInitial}
              onRetry={retryMessage}
              onEdit={editFailed}
            />
          ))}
          <div ref={bottomRef} />
        </div>

        {/* Composer */}
        <div style={{ padding: "10px 16px 14px", borderTop: "1px solid var(--border)", background: "var(--bg-surface)", flexShrink: 0 }}>
          <textarea
            value={prompt}
            onChange={e => editPrompt(e.target.value)}
            onKeyDown={e => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); void sendMessage(); }
            }}
            placeholder={t("chatTab.input.placeholder")}
            className="g-input"
            rows={2}
            dir="auto"
            aria-label={t("chatTab.input.label")}
            aria-describedby="chat-composer-meta"
            aria-invalid={limit === "over" || !!sendError}
            style={{ width: "100%", maxHeight: 160, resize: "none", marginBottom: 8, unicodeBidi: "plaintext" }}
          />
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <div id="chat-composer-meta" style={{ flex: 1, minWidth: 0, fontSize: 12, lineHeight: 1.5 }}>
              {sendError ? (
                <span role="alert" style={{ color: "var(--red)" }}>{sendError}</span>
              ) : limit === "over" ? (
                <span style={{ color: "var(--red)" }}>
                  {t("chatTab.input.overLimit", { count: charCount.toLocaleString(i18n.language), limit: limits.maxPromptChars.toLocaleString(i18n.language) })}
                </span>
              ) : limit === "warn" ? (
                <span style={{ color: "var(--amber, var(--ta))" }}>
                  {t("chatTab.input.nearLimit", { remaining: (limits.maxPromptChars - charCount).toLocaleString(i18n.language) })}
                </span>
              ) : null}
            </div>
            <span
              style={{ fontSize: 11, fontVariantNumeric: "tabular-nums", color: limit === "over" ? "var(--red)" : "var(--t5)" }}
              aria-label={t("chatTab.input.counterLabel", { count: charCount, limit: limits.maxPromptChars })}
            >
              {t("chatTab.input.counter", { count: charCount.toLocaleString(i18n.language), limit: limits.maxPromptChars.toLocaleString(i18n.language) })}
            </span>
            {streaming ? (
              <GoldButton
                variant="danger"
                onClick={() => liveRef.current?.ctrl.abort()}
                style={{ height: 36, paddingInline: 16, fontSize: 13 }}
              >
                <span aria-hidden="true">■ </span>{t("chatTab.input.stop")}
              </GoldButton>
            ) : (
              <GoldButton
                onClick={() => void sendMessage()}
                disabled={!prompt.trim() || limit === "over"}
                style={{ height: 36, paddingInline: 16, fontSize: 13 }}
              >
                {t("chatTab.input.send")} <span aria-hidden="true">↑</span>
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
              type="button"
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
                <div className="chat-context__agent-avatar" aria-hidden="true">
                  {activeAgent?.avatar ?? "◈"}
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
                    type="button"
                    className="chat-context__action-btn"
                    onClick={() => void exportConv()}
                    disabled={exporting}
                    title={t("chatTab.sidebar.exportTitle")}
                  >
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                      <polyline points="7 10 12 15 17 10"/>
                      <line x1="12" y1="15" x2="12" y2="3"/>
                    </svg>
                    {exporting ? "…" : t("chatTab.contextPanel.export")}
                  </button>
                  <button
                    type="button"
                    className="chat-context__action-btn"
                    onClick={() => void extractTasks()}
                    disabled={extracting}
                    title={t("chatTab.sidebar.extractTasksTitle")}
                  >
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
  msg, isLast, awaitingReply, canRetry, agentName, agentAvatar, userInitial, onRetry, onEdit,
}: {
  msg: Message; isLast: boolean; awaitingReply: boolean; canRetry: boolean;
  agentName: string | null; agentAvatar: string | null; userInitial: string;
  onRetry: (m: Message) => void; onEdit: (m: Message) => void;
}) {
  const { t } = useTranslation("ai");
  const toast = useToast();
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) return;
    const id = setTimeout(() => setCopied(false), 2000);
    return () => clearTimeout(id);
  }, [copied]);

  function handleCopy() {
    void copyText(msg.content)
      .then(() => setCopied(true))
      .catch(() => toast(t("common:actions.copyFailed"), "err"));
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

  // Status line under the message — text plus color, never color alone.
  // The reason (often an English provider message) sits in its own element
  // with its own direction so it doesn't scramble an Arabic label.
  let statusText: string | null = null;
  let statusReason: string | null = null;
  let statusTone: "muted" | "warn" | "error" = "muted";
  let showRetry = false;
  let showEdit = false;
  if (isUser) {
    if (msg.status === "sending") statusText = t("chatTab.status.sending");
    else if (msg.status === "failed") {
      statusText = t("chatTab.status.sendFailed"); statusReason = msg.error ?? null;
      statusTone = "error"; showRetry = canRetry; showEdit = true;
    } else if (awaitingReply) {
      statusText = t("chatTab.status.noReply"); statusTone = "warn"; showRetry = canRetry;
    } else if (msg.status === "saved" && isLast) statusText = t("chatTab.status.saved");
  } else if (msg.status === "partial") {
    statusText = t("chatTab.status.replyPartial"); statusReason = msg.error ?? null;
    statusTone = "warn"; showRetry = canRetry;
  } else if (msg.status === "failed") {
    statusText = t("chatTab.status.replyFailed"); statusReason = msg.error ?? null;
    statusTone = "error"; showRetry = canRetry;
  }
  const toneColor = statusTone === "error" ? "var(--red)" : statusTone === "warn" ? "var(--amber, var(--ta))" : "var(--t5)";

  return (
    <div style={rowStyle} className="msg-row">
      {/* Assistant avatar */}
      {!isUser && (
        <div aria-hidden="true" style={{ width: 34, height: 34, borderRadius: 9, flexShrink: 0, background: "var(--accent-dim)", border: "1px solid var(--accent-border)", display: "flex", alignItems: "center", justifyContent: "center", marginTop: 2 }}>
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
          {msg.content && (
            <button
              type="button"
              className={`msg-copy-btn${copied ? " copied" : ""}`}
              onClick={handleCopy}
              aria-label={copied ? t("chatTab.messages.copied") : t("chatTab.messages.copyMessage")}
            >
              {copied ? t("chatTab.messages.copied") : t("chatTab.messages.copyShort")}
            </button>
          )}
        </div>

        {/* Content */}
        {isUser ? (
          <div dir="auto" style={{
            fontSize: 15, lineHeight: 1.75, color: "var(--t1)",
            background: "linear-gradient(135deg, var(--accent-dim), var(--accent-glow))",
            border: "1px solid var(--accent-border)",
            borderRadius: 16, borderStartEndRadius: 4, padding: "12px 18px",
            boxShadow: "0 2px 16px var(--accent-dim)", display: "inline-block",
            // Keep the user's text exactly as typed: newlines, indentation, code.
            // `plaintext` gives each line its own direction, so Arabic lines
            // read RTL and code lines read LTR instead of being bidi-flipped.
            whiteSpace: "pre-wrap", overflowWrap: "anywhere", maxWidth: "100%",
            unicodeBidi: "plaintext", textAlign: "start",
          }}>{msg.content}</div>
        ) : msg.content === "" && msg.status === "streaming" ? (
          <div style={{ padding: "8px 0" }} className="typing" role="img" aria-label={t("chatTab.status.thinking")}><span /><span /><span /></div>
        ) : msg.content === "" ? null : (
          <div dir="auto" style={{ fontSize: 15, color: "var(--t2)", lineHeight: 1.8 }} className="md-body">
            <ReactMarkdown components={MD_COMPONENTS}>{msg.content}</ReactMarkdown>
          </div>
        )}

        {statusText && (
          <div style={{
            display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginTop: 6,
            fontSize: 12, color: toneColor, justifyContent: isUser ? "flex-end" : "flex-start",
          }}>
            <span>{statusText}</span>
            {statusReason && <span dir="auto" style={{ flexBasis: "100%", color: "var(--t4)" }}>{statusReason}</span>}
            {showRetry && (
              <button type="button" className="msg-status-btn" onClick={() => onRetry(msg)}>
                {t("chatTab.status.retry")}
              </button>
            )}
            {showEdit && (
              <button type="button" className="msg-status-btn" onClick={() => onEdit(msg)}>
                {t("chatTab.status.edit")}
              </button>
            )}
          </div>
        )}
      </div>

      {/* User avatar */}
      {isUser && (
        <div aria-hidden="true" style={{
          width: 34, height: 34, borderRadius: 9, flexShrink: 0,
          background: "linear-gradient(135deg, var(--accent), var(--accent-2))",
          display: "flex", alignItems: "center", justifyContent: "center",
          fontSize: 13, fontWeight: 700, color: "#121008", marginTop: 2,
        }}>{userInitial}</div>
      )}
    </div>
  );
});
