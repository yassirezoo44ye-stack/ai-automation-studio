/**
 * ChatTab — streaming AI conversation panel.
 * Handles conversation list, message rendering, streaming, task extraction.
 * All data access goes through apiFetch; no direct provider imports.
 */
import { useState, useRef, useEffect, useCallback, memo } from "react";
import ReactMarkdown from "react-markdown";
import { useToast } from "../../../contexts/toast";
import { apiFetch, apiJSON, parseJSON, authH, API } from "../../../utils/api";
import { relTime } from "../../../utils/time";
import { MD_COMPONENTS } from "../../../shared/ui/md-components";
import { useAsyncData } from "../../../shared/hooks/useAsyncData";
import { LoadingSpinner } from "../../../shared/ui/LoadingSpinner";
import { ErrorState, EmptyState } from "../../../shared/ui/StateViews";
import { S, C } from "../../../styles/theme";
import AxonLogo from "../../../AxonLogo";
import type { Message, Conv, Project, Agent, Task } from "../../../types";
import { PRIORITY_COLOR } from "../../../constants";

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
  const [messages, setMessages]   = useState<Message[]>([]);
  const [prompt, setPrompt]       = useState("");
  const [streaming, setStreaming] = useState(false);
  const [searchQ, setSearchQ]     = useState("");
  const [inlineTasks, setInlineTasks] = useState<Task[]>([]);
  const [extracting, setExtracting]   = useState(false);
  const [showTasks, setShowTasks]     = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const abortRef  = useRef<AbortController | null>(null);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages]);

  // Reset conversation state when the project changes — during render,
  // per React's "adjusting state when a prop changes" pattern.
  const [prevProjectId, setPrevProjectId] = useState(projectId);
  if (prevProjectId !== projectId) { setPrevProjectId(projectId); setActiveConv(null); setMessages([]); }

  const loadInlineTasks = useCallback(async () => {
    if (!activeConv) return;
    try {
      const r = await apiFetch("/api/tasks?sort=created_at");
      const d = await parseJSON<{ tasks?: Task[] }>(r, "/api/tasks");
      setInlineTasks((d.tasks ?? []).slice(0, 6));
    } catch {}
  }, [activeConv]);

  useEffect(() => { if (showTasks) void Promise.resolve().then(loadInlineTasks); }, [showTasks, loadInlineTasks]);

  async function loadMessages(cid: string) {
    const path = `/api/conversations/${cid}/messages`;
    try {
      const r = await apiFetch(path);
      const msgs = await parseJSON<{ id: string; role: string; content: string }[]>(r, path);
      setMessages(msgs.map(m => ({ id: m.id, role: m.role as "user" | "assistant", content: m.content })));
    } catch {}
  }

  async function extractTasks() {
    if (!activeConv || extracting) return;
    setExtracting(true);
    try {
      const path = `/api/tasks/from-conversation/${activeConv}`;
      const r = await apiFetch(path, { method: "POST" });
      const d = await parseJSON<{ created?: unknown[] }>(r, path);
      const n = d.created?.length ?? 0;
      toast(n > 0 ? `Extracted ${n} task${n !== 1 ? "s" : ""}` : "No clear tasks found", n > 0 ? "ok" : "info");
      if (n > 0) { setShowTasks(true); loadInlineTasks(); }
    } catch { toast("Failed to extract tasks", "err"); }
    finally { setExtracting(false); }
  }

  async function setTaskStatus(t: Task, status: string) {
    setInlineTasks(prev => prev.map(x => x.id === t.id ? { ...x, status: status as Task["status"] } : x));
    try {
      await apiFetch(`/api/tasks/${t.id}`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status }),
      });
    } catch { loadInlineTasks(); }
  }

  async function deleteConv(e: React.MouseEvent, cid: string) {
    e.stopPropagation();
    try {
      const r = await apiFetch(`/api/conversations/${cid}`, { method: "DELETE" });
      if (!r.ok) throw new Error();
      if (activeConv === cid) { setActiveConv(null); setMessages([]); }
      loadConvs();
    } catch { toast("Failed to delete conversation", "err"); }
  }

  async function exportConv() {
    if (!activeConv) return;
    try {
      const r = await apiFetch(`/api/export/conversations/${activeConv}`);
      if (!r.ok) { toast("Export failed", "err"); return; }
      const blob = await r.blob();
      const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "conversation.md"; a.click();
      URL.revokeObjectURL(a.href);
      toast("Exported as Markdown");
    } catch { toast("Export failed", "err"); }
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
          if (ev.type === "conv_id" && !activeConv) { setActiveConv(ev.conv_id); loadConvs(); }
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

  const filteredConvs = searchQ
    ? convs.filter(c => c.title.toLowerCase().includes(searchQ.toLowerCase()))
    : convs;
  const activeAgent = agents.find(a => a.id === agentId);

  return (
    <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>
      {/* ── Conversation sidebar ──────────────────────────────────────────────── */}
      <div style={S.chatSidebar}>
        <div style={{ padding: "10px 10px 6px", display: "flex", gap: 6 }}>
          <select value={projectId} onChange={e => setProjectId(e.target.value)} style={{ ...S.projectSelect, flex: 1 }}>
            <option value="demo">Demo Project</option>
            {projects.filter(p => p.id !== "00000000-0000-0000-0000-000000000001").map(p => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
        </div>
        <div style={{ padding: "0 10px 6px" }}>
          <select value={agentId} onChange={e => setAgentId(e.target.value)} style={{ ...S.projectSelect, width: "100%" }}>
            <option value="default">🤖 Claude (default)</option>
            {agents.map(a => <option key={a.id} value={a.id}>{a.avatar} {a.name}</option>)}
          </select>
        </div>
        <div style={{ padding: "0 8px 6px", display: "flex", gap: 6 }}>
          <button onClick={() => { setActiveConv(null); setMessages([]); setShowTasks(false); }} style={{ ...S.newChatBtn, flex: 1 }}>+ New Chat</button>
          {activeConv && (
            <button onClick={exportConv} title="Export as Markdown" style={{ ...S.newChatBtn, width: 36, padding: 0, textAlign: "center" }}>↓</button>
          )}
          {activeConv && (
            <button onClick={extractTasks} disabled={extracting} title="Extract tasks" style={{ ...S.newChatBtn, width: 36, padding: 0, textAlign: "center" }}>
              {extracting ? "…" : "✅"}
            </button>
          )}
        </div>
        <div style={{ padding: "0 8px 6px" }}>
          <input value={searchQ} onChange={e => setSearchQ(e.target.value)} placeholder="Search…" style={{ ...S.textInput, fontSize: 12, padding: "6px 10px" }} />
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
          {filteredConvs.map(c => (
            <div
              key={c.id}
              onClick={() => { setActiveConv(c.id); loadMessages(c.id); }}
              style={{ ...S.convItem, ...(c.id === activeConv ? S.convItemActive : {}) }}
            >
              <div style={S.convTitle}>{c.title}</div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 2 }}>
                <span style={S.convTime}>{relTime(c.updated_at)}</span>
                <span onClick={e => deleteConv(e, c.id)} style={{ color: C.slate, fontSize: 11, cursor: "pointer" }}>✕</span>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* ── Chat area ─────────────────────────────────────────────────────────── */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        {/* Inline tasks strip */}
        {showTasks && inlineTasks.length > 0 && (
          <div style={{ padding: "10px 16px", borderBottom: "1px solid rgba(255,255,255,0.06)", background: "rgba(108,142,247,0.04)", display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
            <span style={{ fontSize: 11, fontWeight: 600, color: "var(--ta)", flexShrink: 0 }}>TASKS</span>
            {inlineTasks.map(t => (
              <div key={t.id} style={{ display: "flex", alignItems: "center", gap: 6, padding: "4px 10px", borderRadius: 20, background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)", fontSize: 12 }}>
                <button
                  onClick={() => setTaskStatus(t, t.status === "done" ? "pending" : "done")}
                  style={{ background: "none", border: "none", cursor: "pointer", padding: 0, color: t.status === "done" ? C.green : "var(--t5)", display: "flex" }}
                >
                  {t.status === "done"
                    ? <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="20 6 9 17 4 12"/></svg>
                    : <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="9"/></svg>}
                </button>
                <span style={{ color: t.status === "done" ? "var(--t5)" : "var(--t2)", textDecoration: t.status === "done" ? "line-through" : "none" }}>{t.title}</span>
                <span style={{ width: 6, height: 6, borderRadius: "50%", background: PRIORITY_COLOR[t.priority], flexShrink: 0 }} title={t.priority} />
              </div>
            ))}
            <button onClick={() => setShowTasks(false)} style={{ background: "none", border: "none", color: "var(--t5)", cursor: "pointer", marginLeft: "auto", fontSize: 16 }}>×</button>
          </div>
        )}

        {/* Messages */}
        <div style={{ ...S.messages, position: "relative" }}>
          {messages.length === 0 && (
            <div style={{ ...S.empty, animation: "fadeIn .4s ease" }}>
              <div style={{ width: 72, height: 72, borderRadius: 20, margin: "0 auto 16px", background: "linear-gradient(135deg,rgba(255,215,0,.22),rgba(99,102,241,.17))", border: "1px solid rgba(255,215,0,.22)", display: "flex", alignItems: "center", justifyContent: "center" }}>
                {activeAgent ? <span style={{ fontSize: 32 }}>{activeAgent.avatar}</span> : <AxonLogo size={40} />}
              </div>
              <div style={{ fontSize: 20, fontWeight: 700, color: "var(--t1)", letterSpacing: "-.4px" }}>{activeAgent ? activeAgent.name : "Axon AI"}</div>
              <div style={{ fontSize: 14, color: "var(--t4)", maxWidth: 320, lineHeight: 1.65, marginTop: 6 }}>
                {activeAgent?.description ?? "Start a conversation or pick one from the sidebar."}
              </div>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", justifyContent: "center", marginTop: 16 }}>
                {["Write Python code", "Explain a concept", "Debug my script", "Build a web app"].map(s => (
                  <button key={s} onClick={() => setPrompt(s)} style={{ ...S.btnSecondary, fontSize: 12, padding: "6px 14px" }}>{s}</button>
                ))}
              </div>
            </div>
          )}
          {messages.map((m, idx) => (
            <MessageRow key={m.id} msg={m} isLast={idx === messages.length - 1}
                        agentName={activeAgent?.name ?? null} agentAvatar={activeAgent?.avatar ?? null} />
          ))}
          <div ref={bottomRef} />
        </div>

        {/* Input */}
        <div style={S.inputRow}>
          <textarea
            value={prompt}
            onChange={e => setPrompt(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void sendMessage(); } }}
            placeholder="Message… (Enter to send, Shift+Enter for new line)"
            style={S.input} rows={1}
          />
          {streaming
            ? <button onClick={() => abortRef.current?.abort()} style={{ ...S.sendBtn, background: C.redSoft }}>■</button>
            : <button onClick={() => void sendMessage()} disabled={!prompt.trim()} style={S.sendBtn}>↑</button>}
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
  return (
    <div style={msg.role === "user" ? S.msgRowUser : S.msgRowAssist} className="msg-row">
      {msg.role === "assistant" && (
        <div style={S.avatar}><span style={{ fontSize: 18 }}>{agentAvatar ?? "◈"}</span></div>
      )}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={msg.role === "user" ? S.msgLabelUser : S.msgLabelAssist}>
          {msg.role === "user" ? "You" : (agentName ?? "Claude")}
          <span style={S.msgTime}>{isLast ? "now" : ""}</span>
        </div>
        {msg.role === "user" ? (
          <div style={S.msgBubbleUser}>{msg.content}</div>
        ) : msg.content === "" ? (
          <div style={{ padding: "8px 0" }} className="typing"><span /><span /><span /></div>
        ) : (
          <div style={S.msgBubbleAssist} className="md-body">
            <ReactMarkdown components={MD_COMPONENTS}>{msg.content}</ReactMarkdown>
          </div>
        )}
      </div>
      {msg.role === "user" && <div style={S.avatarUser}>Y</div>}
    </div>
  );
});

