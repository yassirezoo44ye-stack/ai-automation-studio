import { useState, useRef, useEffect, useCallback, createContext, useContext } from "react";
import ReactMarkdown from "react-markdown";

type Page    = "dashboard" | "chat" | "agents" | "build" | "social" | "projects" | "settings";
type Message = { id: string; role: "user" | "assistant"; content: string };
type Conv    = { id: string; title: string; updated_at: string };
type Project = { id: string; name: string; description: string; status: string; created_at: string };
type Agent   = { id: string; name: string; avatar: string; description: string; system_prompt: string; model: string; temperature: number; message_count: number; created_at: string };

const API = "http://127.0.0.1:8000";

// ── Toast ─────────────────────────────────────────────────────────────────────
type Toast = { id: string; msg: string; kind: "ok" | "err" | "info" };
const ToastCtx = createContext<(msg: string, kind?: Toast["kind"]) => void>(() => {});
function useToast() { return useContext(ToastCtx); }

function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const add = useCallback((msg: string, kind: Toast["kind"] = "ok") => {
    const id = crypto.randomUUID();
    setToasts(p => [...p, { id, msg, kind }]);
    setTimeout(() => setToasts(p => p.filter(t => t.id !== id)), 3500);
  }, []);
  return (
    <ToastCtx.Provider value={add}>
      {children}
      <div style={{ position: "fixed", bottom: 24, right: 24, display: "flex", flexDirection: "column", gap: 8, zIndex: 9999, pointerEvents: "none" }}>
        {toasts.map(t => (
          <div key={t.id} style={{ background: t.kind === "err" ? "#3b1a1a" : t.kind === "info" ? "#1a2040" : "#1a3b2a", border: `1px solid ${t.kind === "err" ? "#f87171" : t.kind === "info" ? "#6c8ef7" : "#34d399"}`, color: t.kind === "err" ? "#f87171" : t.kind === "info" ? "#93b4ff" : "#34d399", padding: "10px 16px", borderRadius: 10, fontSize: 13, maxWidth: 320, boxShadow: "0 4px 20px #0009", animation: "slideIn .2s ease" }}>
            {t.msg}
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

// ── Dashboard ─────────────────────────────────────────────────────────────────
function DashboardPage() {
  const [stats, setStats]     = useState<Record<string, number> | null>(null);
  const [series, setSeries]   = useState<{ labels: string[]; messages: number[]; builds: number[] } | null>(null);
  const [activity, setActivity] = useState<{ action: string; details: Record<string, string>; time: string }[]>([]);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    fetch(`${API}/api/stats`).then(r => r.json()).then(d => { setStats(d); setActivity(d.recent_activity ?? []); }).catch(() => {});
    fetch(`${API}/api/stats/timeseries?days=14`).then(r => r.json()).then(setSeries).catch(() => {});
  }, []);

  useEffect(() => {
    if (!series || !canvasRef.current) return;
    const canvas = canvasRef.current;
    const ctx = canvas.getContext("2d")!;
    const W = canvas.width, H = canvas.height;
    const pad = { top: 20, right: 20, bottom: 36, left: 40 };
    const gW = W - pad.left - pad.right;
    const gH = H - pad.top - pad.bottom;
    ctx.clearRect(0, 0, W, H);

    const allVals = [...series.messages, ...series.builds];
    const maxVal  = Math.max(...allVals, 1);
    const n = series.labels.length;

    const x = (i: number) => pad.left + (i / (n - 1)) * gW;
    const y = (v: number) => pad.top + gH - (v / maxVal) * gH;

    // Grid lines
    ctx.strokeStyle = "#1e2438"; ctx.lineWidth = 1;
    for (let i = 0; i <= 4; i++) {
      const yy = pad.top + (i / 4) * gH;
      ctx.beginPath(); ctx.moveTo(pad.left, yy); ctx.lineTo(pad.left + gW, yy); ctx.stroke();
      ctx.fillStyle = "#4b5980"; ctx.font = "11px Segoe UI";
      ctx.fillText(String(Math.round(maxVal * (1 - i / 4))), 4, yy + 4);
    }

    // Area — messages
    const grad1 = ctx.createLinearGradient(0, pad.top, 0, pad.top + gH);
    grad1.addColorStop(0, "#6c8ef740"); grad1.addColorStop(1, "#6c8ef700");
    ctx.beginPath();
    ctx.moveTo(x(0), y(series.messages[0]));
    series.messages.forEach((v, i) => ctx.lineTo(x(i), y(v)));
    ctx.lineTo(x(n - 1), pad.top + gH); ctx.lineTo(x(0), pad.top + gH);
    ctx.closePath(); ctx.fillStyle = grad1; ctx.fill();

    // Line — messages
    ctx.beginPath(); ctx.strokeStyle = "#6c8ef7"; ctx.lineWidth = 2.5;
    series.messages.forEach((v, i) => i === 0 ? ctx.moveTo(x(i), y(v)) : ctx.lineTo(x(i), y(v)));
    ctx.stroke();

    // Area — builds
    const grad2 = ctx.createLinearGradient(0, pad.top, 0, pad.top + gH);
    grad2.addColorStop(0, "#34d39930"); grad2.addColorStop(1, "#34d39900");
    ctx.beginPath();
    ctx.moveTo(x(0), y(series.builds[0]));
    series.builds.forEach((v, i) => ctx.lineTo(x(i), y(v)));
    ctx.lineTo(x(n - 1), pad.top + gH); ctx.lineTo(x(0), pad.top + gH);
    ctx.closePath(); ctx.fillStyle = grad2; ctx.fill();

    // Line — builds
    ctx.beginPath(); ctx.strokeStyle = "#34d399"; ctx.lineWidth = 2;
    series.builds.forEach((v, i) => i === 0 ? ctx.moveTo(x(i), y(v)) : ctx.lineTo(x(i), y(v)));
    ctx.stroke();

    // Labels
    ctx.fillStyle = "#4b5980"; ctx.font = "11px Segoe UI"; ctx.textAlign = "center";
    series.labels.forEach((l, i) => { if (i % 2 === 0) ctx.fillText(l, x(i), H - 8); });
    ctx.textAlign = "start";
  }, [series]);

  const statCards = [
    { label: "Conversations", value: stats?.conversations ?? "—", icon: "💬", color: "#6c8ef7" },
    { label: "Messages",      value: stats?.messages      ?? "—", icon: "✉️",  color: "#a78bfa" },
    { label: "Builds",        value: stats?.agent_runs    ?? "—", icon: "🔨", color: "#34d399" },
    { label: "Projects",      value: stats?.projects      ?? "—", icon: "📁", color: "#f59e0b" },
    { label: "Success Rate",  value: stats ? `${stats.success_rate}%` : "—", icon: "✅", color: "#10b981" },
    { label: "Agent Runs",    value: stats?.agent_runs    ?? "—", icon: "⚡", color: "#f87171" },
  ];

  const actionLabel: Record<string, string> = { agent_run: "Chat run", build: "Build", project_created: "New project" };

  return (
    <>
      <header style={S.header}><span style={S.headerTitle}>Dashboard</span><span style={S.headerSub}>Live metrics</span></header>
      <div style={{ flex: 1, overflowY: "auto", padding: 24, display: "flex", flexDirection: "column", gap: 20 }}>
        {/* Stat cards */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 12 }}>
          {statCards.map(c => (
            <div key={c.label} style={{ ...S.card, display: "flex", alignItems: "center", gap: 14 }}>
              <div style={{ width: 44, height: 44, borderRadius: 12, background: c.color + "22", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 22, flexShrink: 0 }}>{c.icon}</div>
              <div>
                <div style={{ fontSize: 22, fontWeight: 700, color: c.color, lineHeight: 1 }}>{String(c.value)}</div>
                <div style={{ fontSize: 12, color: "#6b7a99", marginTop: 3 }}>{c.label}</div>
              </div>
            </div>
          ))}
        </div>

        {/* Chart */}
        <div style={S.card}>
          <div style={{ ...S.cardTitle, marginBottom: 12 }}>Activity (last 14 days)</div>
          <div style={{ display: "flex", gap: 16, marginBottom: 8, fontSize: 12 }}>
            <span style={{ color: "#6c8ef7" }}>⬤ Messages</span>
            <span style={{ color: "#34d399" }}>⬤ Builds</span>
          </div>
          {series ? (
            <canvas ref={canvasRef} width={800} height={200} style={{ width: "100%", height: 200 }} />
          ) : (
            <div style={{ height: 200, display: "flex", alignItems: "center", justifyContent: "center", color: "#4b5980" }}>Loading…</div>
          )}
        </div>

        {/* Recent activity */}
        <div style={S.card}>
          <div style={{ ...S.cardTitle, marginBottom: 12 }}>Recent Activity</div>
          {activity.length === 0 && <div style={S.muted}>No activity yet.</div>}
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {activity.slice(0, 8).map((a, i) => (
              <div key={i} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "8px 0", borderBottom: "1px solid #1e2438" }}>
                <div>
                  <span style={{ fontSize: 13, color: "#c8d3f0" }}>{actionLabel[a.action] ?? a.action}</span>
                  {a.details.prompt_preview && <span style={{ fontSize: 12, color: "#6b7a99", marginLeft: 8 }}>"{a.details.prompt_preview}"</span>}
                  {a.details.files && <span style={{ fontSize: 12, color: "#34d399", marginLeft: 8 }}>{JSON.stringify(a.details.files).length > 2 ? `${a.details.files} files` : ""}</span>}
                </div>
                <span style={{ fontSize: 11, color: "#4b5980" }}>{relTime(a.time)}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </>
  );
}

// ── Chat Page ─────────────────────────────────────────────────────────────────
function ChatPage() {
  const toast                         = useToast();
  const [projects, setProjects]       = useState<Project[]>([]);
  const [agents, setAgents]           = useState<Agent[]>([]);
  const [projectId, setProjectId]     = useState("demo");
  const [agentId, setAgentId]         = useState<string>("default");
  const [convs, setConvs]             = useState<Conv[]>([]);
  const [activeConv, setActiveConv]   = useState<string | null>(null);
  const [messages, setMessages]       = useState<Message[]>([]);
  const [prompt, setPrompt]           = useState("");
  const [streaming, setStreaming]     = useState(false);
  const [searchQ, setSearchQ]         = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);
  const abortRef  = useRef<AbortController | null>(null);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages]);

  const loadProjects = useCallback(async () => {
    try { const r = await fetch(`${API}/api/projects`); setProjects(await r.json()); } catch {}
  }, []);
  const loadAgents = useCallback(async () => {
    try { const r = await fetch(`${API}/api/agents`); setAgents(await r.json()); } catch {}
  }, []);
  const loadConvs = useCallback(async () => {
    try {
      const r = await fetch(`${API}/api/conversations?project_id=${projectId}`);
      setConvs(await r.json());
    } catch {}
  }, [projectId]);

  useEffect(() => { loadProjects(); loadAgents(); }, []);
  useEffect(() => { loadConvs(); setActiveConv(null); setMessages([]); }, [loadConvs]);

  async function loadMessages(cid: string) {
    try {
      const r = await fetch(`${API}/api/conversations/${cid}/messages`);
      const msgs: { id: string; role: string; content: string }[] = await r.json();
      setMessages(msgs.map(m => ({ id: m.id, role: m.role as "user" | "assistant", content: m.content })));
    } catch {}
  }

  async function deleteConv(e: React.MouseEvent, cid: string) {
    e.stopPropagation();
    await fetch(`${API}/api/conversations/${cid}`, { method: "DELETE" });
    if (activeConv === cid) { setActiveConv(null); setMessages([]); }
    loadConvs();
  }

  async function exportConv() {
    if (!activeConv) return;
    const r = await fetch(`${API}/api/export/conversations/${activeConv}`);
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a"); a.href = url; a.download = "conversation.md"; a.click();
    URL.revokeObjectURL(url);
    toast("Exported as Markdown");
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

    const controller = new AbortController();
    abortRef.current = controller;

    const useAgent = agentId !== "default";
    const url = useAgent ? `${API}/api/agents/${agentId}/chat/stream` : `${API}/run/stream`;

    try {
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project_id: projectId, prompt: text, conversation_id: activeConv, agent_id: agentId }),
        signal: controller.signal,
      });
      if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      let closed = false;

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split("\n");
        buf = lines.pop() ?? "";
        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const ev = JSON.parse(line.slice(6));
          if (ev.type === "conv_id" && !activeConv) { setActiveConv(ev.conv_id); loadConvs(); }
          else if (ev.type === "delta") { setMessages(prev => prev.map(m => m.id === assistantId ? { ...m, content: m.content + ev.text } : m)); }
          else if (ev.type === "error") { setMessages(prev => prev.map(m => m.id === assistantId ? { ...m, content: `⚠️ ${ev.message}` } : m)); closed = true; break; }
          else if (ev.type === "done") { loadConvs(); closed = true; }
        }
        if (closed) break;
      }
    } catch (err: unknown) {
      if ((err as Error).name !== "AbortError") {
        const msg = (err as Error).message ?? "";
        setMessages(prev => prev.map(m => m.id === assistantId ? { ...m, content: msg.includes("fetch") ? "⚠️ Backend offline — run `python main.py`" : `⚠️ ${msg}` } : m));
      }
    } finally {
      setStreaming(false); abortRef.current = null;
    }
  }

  const filteredConvs = searchQ
    ? convs.filter(c => c.title.toLowerCase().includes(searchQ.toLowerCase()))
    : convs;
  const activeAgent = agents.find(a => a.id === agentId);

  return (
    <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>
      {/* Sidebar */}
      <div style={S.chatSidebar}>
        <div style={{ padding: "10px 10px 6px", display: "flex", gap: 6 }}>
          <select value={projectId} onChange={e => setProjectId(e.target.value)} style={{ ...S.projectSelect, flex: 1 }}>
            <option value="demo">Demo Project</option>
            {projects.filter(p => p.id !== "00000000-0000-0000-0000-000000000001").map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </div>
        <div style={{ padding: "0 10px 6px" }}>
          <select value={agentId} onChange={e => setAgentId(e.target.value)} style={{ ...S.projectSelect, width: "100%" }}>
            <option value="default">🤖 Claude (default)</option>
            {agents.map(a => <option key={a.id} value={a.id}>{a.avatar} {a.name}</option>)}
          </select>
        </div>
        <div style={{ padding: "0 8px 6px", display: "flex", gap: 6 }}>
          <button onClick={() => { setActiveConv(null); setMessages([]); }} style={{ ...S.newChatBtn, flex: 1 }}>+ New Chat</button>
          {activeConv && <button onClick={exportConv} title="Export as Markdown" style={{ ...S.newChatBtn, width: 36, padding: 0, textAlign: "center", fontSize: 14 }}>↓</button>}
        </div>
        <div style={{ padding: "0 8px 6px" }}>
          <input value={searchQ} onChange={e => setSearchQ(e.target.value)} placeholder="Search…" style={{ ...S.textInput, fontSize: 12, padding: "6px 10px" }} />
        </div>
        <div style={{ flex: 1, overflowY: "auto" }}>
          {filteredConvs.length === 0 && <div style={{ padding: "12px 16px", fontSize: 12, color: "#4b5980" }}>No conversations</div>}
          {filteredConvs.map(c => (
            <div key={c.id} onClick={() => { setActiveConv(c.id); loadMessages(c.id); }}
              style={{ ...S.convItem, ...(c.id === activeConv ? S.convItemActive : {}) }}>
              <div style={S.convTitle}>{c.title}</div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 2 }}>
                <span style={S.convTime}>{relTime(c.updated_at)}</span>
                <span onClick={e => deleteConv(e, c.id)} style={{ color: "#4b5980", fontSize: 11, cursor: "pointer" }}>✕</span>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Main */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        <header style={S.header}>
          <span style={S.headerTitle}>{activeAgent ? `${activeAgent.avatar} ${activeAgent.name}` : "Chat with Claude"}</span>
          <span style={S.headerSub}>{activeAgent?.model ?? "claude-sonnet-4-6"}</span>
        </header>
        <div style={S.messages}>
          {messages.length === 0 && (
            <div style={S.empty}>
              <div style={{ width: 72, height: 72, borderRadius: 20, margin: "0 auto 20px", background: "linear-gradient(135deg, rgba(139,92,246,.25), rgba(99,102,241,.2))", border: "1px solid rgba(139,92,246,.2)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 34 }}>
                {activeAgent ? activeAgent.avatar : "◈"}
              </div>
              <div style={{ fontSize: 20, fontWeight: 700, color: "#f1f5f9", marginBottom: 8, letterSpacing: "-.3px" }}>
                {activeAgent ? activeAgent.name : "AI Automation Studio"}
              </div>
              <div style={{ fontSize: 14, color: "rgba(148,163,184,.5)", maxWidth: 340, lineHeight: 1.6 }}>
                {activeAgent?.description ?? "ابدأ محادثة جديدة أو اختر واحدة من القائمة الجانبية"}
              </div>
            </div>
          )}
          {messages.map((m, idx) => (
            <div key={m.id} style={m.role === "user" ? S.msgRowUser : S.msgRowAssist} className="msg-row">
              {m.role === "assistant" && (
                <div style={S.avatar}>
                  <span style={{ fontSize: 18 }}>{activeAgent ? activeAgent.avatar : "◈"}</span>
                </div>
              )}
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={m.role === "user" ? S.msgLabelUser : S.msgLabelAssist}>
                  {m.role === "user" ? "أنت" : (activeAgent?.name ?? "Claude")}
                  <span style={S.msgTime}>{idx === messages.length - 1 ? "الآن" : ""}</span>
                </div>
                {m.role === "user" ? (
                  <div style={S.msgBubbleUser}>{m.content}</div>
                ) : m.content === "" ? (
                  <div style={{ padding: "8px 0" }} className="typing"><span /><span /><span /></div>
                ) : (
                  <div style={S.msgBubbleAssist} className="md-body">
                    <ReactMarkdown>{m.content}</ReactMarkdown>
                  </div>
                )}
              </div>
              {m.role === "user" && (
                <div style={S.avatarUser}>Y</div>
              )}
            </div>
          ))}
          <div ref={bottomRef} />
        </div>
        <div style={S.inputRow}>
          <textarea value={prompt} onChange={e => setPrompt(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); } }}
            placeholder="Message… (Enter to send, Shift+Enter for new line)"
            style={S.input} rows={1} />
          {streaming
            ? <button onClick={() => abortRef.current?.abort()} style={{ ...S.sendBtn, background: "#f87171" }}>■</button>
            : <button onClick={sendMessage} disabled={!prompt.trim()} style={S.sendBtn}>↑</button>}
        </div>
      </div>
    </div>
  );
}

// ── Agents Page ───────────────────────────────────────────────────────────────
const AGENT_TEMPLATES = [
  { name: "Code Reviewer", avatar: "🔍", description: "Reviews code for bugs, style, and improvements", system_prompt: "You are an expert code reviewer. Analyze code thoroughly, pointing out bugs, security issues, performance problems, and style improvements. Be specific with line references and provide corrected code snippets." },
  { name: "Python Tutor", avatar: "🐍", description: "Teaches Python clearly with examples", system_prompt: "You are an expert Python tutor. Explain concepts clearly with working examples, explain each line, and encourage best practices. Tailor your explanations to the student's level." },
  { name: "DevOps Engineer", avatar: "⚙️", description: "Docker, CI/CD, infrastructure specialist", system_prompt: "You are a senior DevOps engineer specializing in Docker, Kubernetes, CI/CD pipelines, and cloud infrastructure. Provide production-ready solutions with security and scalability in mind." },
  { name: "Data Analyst", avatar: "📊", description: "Data analysis, SQL, pandas expert", system_prompt: "You are a data analyst expert in SQL, Python (pandas/numpy/matplotlib), and data visualization. Help users analyze data, write efficient queries, and create insightful visualizations." },
  { name: "Creative Writer", avatar: "✍️", description: "Engaging creative and technical writing", system_prompt: "You are a skilled creative writer. Help with storytelling, blog posts, documentation, and any writing task. Focus on clarity, engagement, and the right tone for the audience." },
  { name: "Security Auditor", avatar: "🛡️", description: "Security analysis and best practices", system_prompt: "You are a cybersecurity expert. Analyze code and systems for vulnerabilities (OWASP Top 10, injection, auth issues), suggest hardening measures, and explain security concepts clearly." },
];

function AgentsPage() {
  const toast = useToast();
  const [agents, setAgents]     = useState<Agent[]>([]);
  const [loading, setLoading]   = useState(true);
  const [editing, setEditing]   = useState<Partial<Agent> | null>(null);
  const [saving, setSaving]     = useState(false);
  const [view, setView]         = useState<"list" | "form">("list");

  const load = useCallback(async () => {
    setLoading(true);
    try { const r = await fetch(`${API}/api/agents`); setAgents(await r.json()); }
    catch { toast("Could not load agents", "err"); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  async function save() {
    if (!editing?.name?.trim() || !editing?.system_prompt?.trim()) return;
    setSaving(true);
    try {
      const isEdit = editing.id;
      const url  = isEdit ? `${API}/api/agents/${editing.id}` : `${API}/api/agents`;
      const method = isEdit ? "PUT" : "POST";
      const r = await fetch(url, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(editing) });
      if (!r.ok) throw new Error();
      toast(isEdit ? "Agent updated" : "Agent created");
      setView("list"); setEditing(null); load();
    } catch { toast("Failed to save", "err"); }
    finally { setSaving(false); }
  }

  async function del(id: string, name: string) {
    if (!confirm(`Delete agent "${name}"?`)) return;
    await fetch(`${API}/api/agents/${id}`, { method: "DELETE" });
    toast(`Deleted ${name}`); load();
  }

  function fromTemplate(t: typeof AGENT_TEMPLATES[0]) {
    setEditing({ name: t.name, avatar: t.avatar, description: t.description, system_prompt: t.system_prompt, model: "claude-sonnet-4-6", temperature: 1 });
    setView("form");
  }

  if (view === "form") {
    return (
      <>
        <header style={S.header}>
          <span style={S.headerTitle}>{editing?.id ? "Edit Agent" : "New Agent"}</span>
          <button onClick={() => { setView("list"); setEditing(null); }} style={S.btnSecondary}>← Back</button>
        </header>
        <div style={{ flex: 1, overflowY: "auto", padding: 24 }}>
          <div style={{ maxWidth: 640, display: "flex", flexDirection: "column", gap: 14 }}>
            <div style={{ display: "flex", gap: 10 }}>
              <div style={{ width: 70 }}>
                <label style={S.label}>Avatar</label>
                <input value={editing?.avatar ?? "🤖"} onChange={e => setEditing(p => ({ ...p, avatar: e.target.value }))} style={{ ...S.textInput, textAlign: "center", fontSize: 24 }} maxLength={2} />
              </div>
              <div style={{ flex: 1 }}>
                <label style={S.label}>Name *</label>
                <input value={editing?.name ?? ""} onChange={e => setEditing(p => ({ ...p, name: e.target.value }))} style={S.textInput} placeholder="My Agent" />
              </div>
            </div>
            <div>
              <label style={S.label}>Description</label>
              <input value={editing?.description ?? ""} onChange={e => setEditing(p => ({ ...p, description: e.target.value }))} style={S.textInput} placeholder="What does this agent do?" />
            </div>
            <div>
              <label style={S.label}>System Prompt *</label>
              <textarea value={editing?.system_prompt ?? ""} onChange={e => setEditing(p => ({ ...p, system_prompt: e.target.value }))}
                style={{ ...S.textInput, minHeight: 200, lineHeight: 1.6 }} placeholder="You are an expert in…" />
            </div>
            <div style={{ display: "flex", gap: 10 }}>
              <div style={{ flex: 1 }}>
                <label style={S.label}>Model</label>
                <select value={editing?.model ?? "claude-sonnet-4-6"} onChange={e => setEditing(p => ({ ...p, model: e.target.value }))} style={S.textInput}>
                  <option value="claude-sonnet-4-6">Sonnet 4.6 (recommended)</option>
                  <option value="claude-opus-4-8">Opus 4.8 (most capable)</option>
                  <option value="claude-haiku-4-5-20251001">Haiku 4.5 (fastest)</option>
                </select>
              </div>
              <div style={{ width: 100 }}>
                <label style={S.label}>Temperature</label>
                <input type="number" min={0} max={1} step={0.1} value={editing?.temperature ?? 1}
                  onChange={e => setEditing(p => ({ ...p, temperature: parseFloat(e.target.value) }))} style={S.textInput} />
              </div>
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <button onClick={save} disabled={saving || !editing?.name?.trim() || !editing?.system_prompt?.trim()} style={S.btnPrimary}>
                {saving ? "Saving…" : "Save Agent"}
              </button>
              <button onClick={() => { setView("list"); setEditing(null); }} style={S.btnSecondary}>Cancel</button>
            </div>
          </div>
        </div>
      </>
    );
  }

  return (
    <>
      <header style={S.header}>
        <span style={S.headerTitle}>Agents</span>
        <button onClick={() => { setEditing({ avatar: "🤖", model: "claude-sonnet-4-6", temperature: 1 }); setView("form"); }} style={S.btnPrimary}>
          + New Agent
        </button>
      </header>
      <div style={{ flex: 1, overflowY: "auto", padding: 24, display: "flex", flexDirection: "column", gap: 20 }}>
        {/* My agents */}
        {!loading && agents.length > 0 && (
          <div>
            <div style={{ fontSize: 13, fontWeight: 600, color: "#8896b3", marginBottom: 10 }}>MY AGENTS</div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(280px,1fr))", gap: 12 }}>
              {agents.map(a => (
                <div key={a.id} style={{ ...S.card, cursor: "default" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                    <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
                      <div style={{ width: 44, height: 44, borderRadius: 12, background: "#1a1f2e", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 24 }}>{a.avatar}</div>
                      <div>
                        <div style={S.cardTitle}>{a.name}</div>
                        <div style={{ fontSize: 11, color: "#4b5980", marginTop: 2 }}>{a.model?.split("-").slice(1, 3).join("-")}</div>
                      </div>
                    </div>
                    <div style={{ display: "flex", gap: 4 }}>
                      <button onClick={() => { setEditing(a); setView("form"); }} style={{ background: "none", border: "none", color: "#6c8ef7", cursor: "pointer", fontSize: 14 }}>✏️</button>
                      <button onClick={() => del(a.id, a.name)} style={{ background: "none", border: "none", color: "#4b5980", cursor: "pointer", fontSize: 14 }}>🗑</button>
                    </div>
                  </div>
                  {a.description && <div style={{ ...S.muted, marginTop: 10, fontSize: 12 }}>{a.description}</div>}
                  <div style={{ marginTop: 10, fontSize: 11, color: "#4b5980" }}>
                    {a.message_count} messages · {relTime(a.created_at)}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Templates */}
        <div>
          <div style={{ fontSize: 13, fontWeight: 600, color: "#8896b3", marginBottom: 10 }}>QUICK START TEMPLATES</div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(280px,1fr))", gap: 12 }}>
            {AGENT_TEMPLATES.map(t => (
              <div key={t.name} style={{ ...S.card, cursor: "pointer", transition: "border-color .15s" }}
                onClick={() => fromTemplate(t)}
                onMouseEnter={e => (e.currentTarget.style.borderColor = "#6c8ef7")}
                onMouseLeave={e => (e.currentTarget.style.borderColor = "#1e2438")}>
                <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
                  <div style={{ width: 44, height: 44, borderRadius: 12, background: "#1a1f2e", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 24 }}>{t.avatar}</div>
                  <div>
                    <div style={S.cardTitle}>{t.name}</div>
                    <div style={{ fontSize: 12, color: "#6b7a99", marginTop: 3 }}>{t.description}</div>
                  </div>
                </div>
                <div style={{ marginTop: 12, fontSize: 11, color: "#6c8ef7" }}>Click to use this template →</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </>
  );
}

// ── Build Page ─────────────────────────────────────────────────────────────────
type BuildFile = { path: string; content: string };
type BuildState = "idle" | "building" | "done" | "error";

const BUILD_TEMPLATES = [
  { label: "🐍 Python CLI", prompt: "Build a Python command-line calculator with add, subtract, multiply, divide operations. Use argparse for arguments." },
  { label: "🌐 Web App",    prompt: "Build a beautiful responsive to-do list web app in a single HTML file with embedded CSS and JavaScript. Support add, complete, and delete tasks with local storage." },
  { label: "🎮 Game",       prompt: "Build a Snake game in a single HTML file with embedded CSS and JavaScript. Include score, game over screen, and restart button." },
  { label: "📊 Dashboard",  prompt: "Build a beautiful data dashboard in a single HTML file showing fake sales analytics with charts using Chart.js from CDN." },
  { label: "🔗 REST API",   prompt: "Build a FastAPI REST API with SQLite for a simple blog: CRUD for posts (title, content, author, created_at). Include requirements.txt." },
  { label: "🤖 Chatbot",    prompt: "Build a Python chatbot using the anthropic library that reads ANTHROPIC_API_KEY from environment. Include requirements.txt and README." },
];

function BuildPage() {
  const toast = useToast();
  const [projects, setProjects]         = useState<Project[]>([]);
  const [projectId, setProjectId]       = useState("demo");
  const [prompt, setPrompt]             = useState("");
  const [state, setState]               = useState<BuildState>("idle");
  const [status, setStatus]             = useState("");
  const [files, setFiles]               = useState<BuildFile[]>([]);
  const [activeFile, setActiveFile]     = useState<BuildFile | null>(null);
  const [runCmd, setRunCmd]             = useState("");
  const [runOutput, setRunOutput]       = useState("");
  const [running, setRunning]           = useState(false);
  const [description, setDescription]  = useState("");
  const [existingFiles, setExistingFiles] = useState<{ path: string; size: number }[]>([]);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => { fetch(`${API}/api/projects`).then(r => r.json()).then(setProjects).catch(() => {}); }, []);
  useEffect(() => { loadExisting(); }, [projectId]);

  async function loadExisting() {
    try { const r = await fetch(`${API}/api/projects/${projectId}/files`); const d = await r.json(); setExistingFiles(d.files ?? []); } catch {}
  }

  async function loadFile(path: string) {
    try { const r = await fetch(`${API}/api/projects/${projectId}/files/${path}`); const d = await r.json(); setActiveFile({ path: d.path, content: d.content }); } catch {}
  }

  async function clearWorkspace() {
    if (!confirm("Clear all files?")) return;
    await fetch(`${API}/api/projects/${projectId}/files`, { method: "DELETE" });
    setFiles([]); setExistingFiles([]); setActiveFile(null); setRunOutput(""); setRunCmd(""); toast("Workspace cleared");
  }

  async function build() {
    if (!prompt.trim() || state === "building") return;
    setState("building"); setStatus("Connecting to Claude…"); setFiles([]); setActiveFile(null); setRunOutput(""); setDescription("");
    const controller = new AbortController(); abortRef.current = controller;
    try {
      const res = await fetch(`${API}/api/build/stream`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ project_id: projectId, prompt }), signal: controller.signal });
      if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);
      const reader = res.body.getReader(); const decoder = new TextDecoder(); let buf = "";
      while (true) {
        const { done, value } = await reader.read(); if (done) break;
        buf += decoder.decode(value, { stream: true }); const lines = buf.split("\n"); buf = lines.pop() ?? "";
        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const ev = JSON.parse(line.slice(6));
          if (ev.type === "status") { setStatus(ev.message); }
          else if (ev.type === "file") { setFiles(p => [...p, { path: ev.path, content: ev.content }]); setStatus(`Writing ${ev.path}…`); }
          else if (ev.type === "done") { setDescription(ev.description); setRunCmd(ev.run_command || ""); setState("done"); setStatus(`Built ${ev.files.length} files`); loadExisting(); toast(`Built: ${ev.description || ev.files.length + " files"}`); }
          else if (ev.type === "error") { setState("error"); setStatus(`Error: ${ev.message}`); toast(ev.message, "err"); }
        }
      }
    } catch (err: unknown) {
      if ((err as Error).name !== "AbortError") { setState("error"); setStatus(`Error: ${(err as Error).message}`); }
      else { setState("idle"); setStatus(""); }
    }
  }

  async function runCode() {
    if (!runCmd.trim()) return;
    setRunning(true); setRunOutput("Running…\n");
    try {
      const r = await fetch(`${API}/api/projects/${projectId}/run`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ command: runCmd }) });
      const d = await r.json();
      if (!r.ok) { setRunOutput(`Error: ${d.detail}`); return; }
      setRunOutput([d.stdout ? `$ ${d.command}\n${d.stdout}` : `$ ${d.command}`, d.stderr ? `\nstderr:\n${d.stderr}` : "", `\n[exit ${d.returncode}]`].join(""));
    } catch (e) { setRunOutput(`Error: ${e}`); }
    finally { setRunning(false); }
  }

  const allFiles = state === "done" ? files : existingFiles.map(f => ({ path: f.path, content: "" }));

  return (
    <>
      <header style={S.header}>
        <span style={S.headerTitle}>🔨 Build</span>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <select value={projectId} onChange={e => setProjectId(e.target.value)} style={{ ...S.projectSelect, width: "auto" }}>
            <option value="demo">Demo Project</option>
            {projects.filter(p => p.id !== "00000000-0000-0000-0000-000000000001").map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
          {allFiles.length > 0 && <button onClick={clearWorkspace} style={{ ...S.btnSecondary, fontSize: 12, padding: "6px 12px" }}>🗑 Clear</button>}
        </div>
      </header>
      <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>
        {/* Left panel */}
        <div style={{ width: 280, borderRight: "1px solid #1e2438", display: "flex", flexDirection: "column", background: "#0a0c10" }}>
          <div style={{ padding: 12, borderBottom: "1px solid #1e2438" }}>
            <textarea value={prompt} onChange={e => setPrompt(e.target.value)}
              onKeyDown={e => { if (e.key === "Enter" && e.ctrlKey) build(); }}
              placeholder={"Describe what to build…\n\nCtrl+Enter to build"}
              style={{ ...S.input, height: 120, fontSize: 12, width: "100%" }} />
            <button onClick={state === "building" ? () => abortRef.current?.abort() : build}
              disabled={!prompt.trim() && state !== "building"} style={{ ...S.btnPrimary, width: "100%", marginTop: 8 }}>
              {state === "building" ? "⏹ Stop" : "🔨 Build"}
            </button>
            {status && <div style={{ marginTop: 8, fontSize: 11, color: state === "error" ? "#f87171" : "#34d399", lineHeight: 1.4 }}>{status}</div>}
            {description && <div style={{ marginTop: 8, fontSize: 12, color: "#8896b3", background: "#13172080", borderRadius: 6, padding: 8, lineHeight: 1.5 }}>{description}</div>}
          </div>
          {/* Templates */}
          <div style={{ padding: "8px 12px", borderBottom: "1px solid #1e2438" }}>
            <div style={{ fontSize: 11, color: "#4b5980", marginBottom: 6, fontWeight: 600 }}>TEMPLATES</div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
              {BUILD_TEMPLATES.map(t => (
                <button key={t.label} onClick={() => setPrompt(t.prompt)} style={{ ...S.btnSecondary, fontSize: 11, padding: "3px 8px" }}>{t.label}</button>
              ))}
            </div>
          </div>
          {/* File tree */}
          <div style={{ flex: 1, overflowY: "auto" }}>
            {allFiles.length === 0 && <div style={{ padding: 16, fontSize: 12, color: "#4b5980" }}>No files yet</div>}
            {allFiles.map(f => (
              <div key={f.path} onClick={() => state === "done" ? setActiveFile(f) : loadFile(f.path)}
                style={{ padding: "7px 14px", cursor: "pointer", fontSize: 12, color: activeFile?.path === f.path ? "#c8d3f0" : "#8896b3", background: activeFile?.path === f.path ? "#1a1f2e" : "transparent", borderLeft: activeFile?.path === f.path ? "2px solid #6c8ef7" : "2px solid transparent", display: "flex", gap: 6, alignItems: "center" }}>
                <span>{fileIcon(f.path)}</span>
                <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{f.path}</span>
              </div>
            ))}
          </div>
        </div>
        {/* Right: code + terminal */}
        <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
          <div style={{ flex: 1, overflow: "auto", background: "#080a0f" }}>
            {activeFile ? (
              <div>
                <div style={{ padding: "10px 20px", borderBottom: "1px solid #1e2438", fontSize: 12, color: "#6b7a99", display: "flex", justifyContent: "space-between" }}>
                  <span>{fileIcon(activeFile.path)} {activeFile.path}</span>
                  <span>{activeFile.content.split("\n").length} lines</span>
                </div>
                <pre style={{ margin: 0, padding: "16px 20px", fontSize: 13, color: "#c8d3f0", lineHeight: 1.6, fontFamily: "'Consolas','Courier New',monospace", overflowX: "auto" }}><code>{activeFile.content}</code></pre>
              </div>
            ) : (
              <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%", color: "#4b5980", flexDirection: "column", gap: 10 }}>
                <span style={{ fontSize: 36 }}>🔨</span>
                <span>Select a file or build something</span>
              </div>
            )}
          </div>
          <div style={{ height: 190, borderTop: "1px solid #1e2438", display: "flex", flexDirection: "column", background: "#040506" }}>
            <div style={{ padding: "6px 12px", borderBottom: "1px solid #1e2438", display: "flex", gap: 8, alignItems: "center" }}>
              <span style={{ fontSize: 11, color: "#6b7a99", flexShrink: 0 }}>▶</span>
              <input value={runCmd} onChange={e => setRunCmd(e.target.value)} onKeyDown={e => { if (e.key === "Enter") runCode(); }}
                placeholder="python main.py" style={{ flex: 1, background: "none", border: "none", color: "#c8d3f0", fontSize: 12, fontFamily: "monospace" }} />
              <button onClick={runCode} disabled={running || !runCmd.trim()} style={{ ...S.btnPrimary, padding: "4px 12px", fontSize: 12 }}>{running ? "…" : "Run ▶"}</button>
            </div>
            <pre style={{ flex: 1, margin: 0, padding: "10px 14px", overflowY: "auto", fontSize: 12, color: "#34d399", fontFamily: "monospace", lineHeight: 1.5 }}>
              {runOutput || <span style={{ color: "#4b5980" }}>Output will appear here…</span>}
            </pre>
          </div>
        </div>
      </div>
    </>
  );
}

function fileIcon(path: string) {
  const ext = path.split(".").pop()?.toLowerCase() ?? "";
  const map: Record<string, string> = { py: "🐍", js: "🟨", ts: "🔷", tsx: "⚛️", jsx: "⚛️", html: "🌐", css: "🎨", json: "📋", md: "📄", txt: "📝", sh: "⚙️", bat: "⚙️", yaml: "📋", yml: "📋", sql: "🗄️", env: "🔑", dockerfile: "🐳", requirements: "📦", toml: "📋" };
  return map[ext] ?? "📄";
}

// ── Social Page ───────────────────────────────────────────────────────────────
type SocialTab = "youtube" | "facebook";
type YTInfo = { title: string; channel: string; duration: number; view_count: number; like_count: number; description: string; thumbnail: string; upload_date: string };
type SocialVariation = { text: string; hashtags?: string[]; tip?: string };

function SocialPage() {
  const toast = useToast();
  const [tab, setTab] = useState<SocialTab>("youtube");
  return (
    <>
      <header style={S.header}>
        <span style={S.headerTitle}>🌐 Social Media</span>
        <div style={{ display: "flex", gap: 4, background: "rgba(255,255,255,.04)", borderRadius: 12, padding: 4 }}>
          {([["youtube","▶ YouTube"],["facebook","📘 Social"]] as [SocialTab,string][]).map(([id,label]) => (
            <button key={id} onClick={() => setTab(id)}
              style={{ padding: "7px 18px", borderRadius: 9, border: "none", cursor: "pointer", fontSize: 13, fontWeight: 500, transition: "all .18s",
                background: tab === id ? "linear-gradient(135deg,#8b5cf6,#6366f1)" : "transparent",
                color: tab === id ? "#fff" : "rgba(148,163,184,.6)",
                boxShadow: tab === id ? "0 2px 12px rgba(139,92,246,.35)" : "none" }}>
              {label}
            </button>
          ))}
        </div>
      </header>
      <div style={{ flex: 1, overflow: "hidden", display: "flex", flexDirection: "column" }}>
        {tab === "youtube"  && <YouTubePage toast={toast} />}
        {tab === "facebook" && <FacebookPage toast={toast} />}
      </div>
    </>
  );
}

// ── YouTube Tab ────────────────────────────────────────────────────────────────
function YouTubePage({ toast }: { toast: (m: string, k?: "ok"|"err"|"info") => void }) {
  const [url, setUrl]               = useState("");
  const [loading, setLoading]       = useState(false);
  const [info, setInfo]             = useState<YTInfo | null>(null);
  const [transcript, setTranscript] = useState("");
  const [transcriptLoading, setTL]  = useState(false);
  const [question, setQuestion]     = useState("");
  const [answer, setAnswer]         = useState("");
  const [answering, setAnswering]   = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  async function fetchInfo() {
    if (!url.trim()) return;
    setLoading(true); setInfo(null); setTranscript(""); setAnswer("");
    try {
      const r = await fetch(`${API}/api/youtube/info`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ url }) });
      if (!r.ok) { const d = await r.json(); throw new Error(d.detail); }
      setInfo(await r.json()); toast("Video info loaded");
    } catch (e: any) { toast(e.message, "err"); }
    finally { setLoading(false); }
  }

  async function fetchTranscript() {
    if (!url.trim()) return;
    setTL(true); setTranscript("");
    try {
      const r = await fetch(`${API}/api/youtube/transcript`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ url }) });
      if (!r.ok) { const d = await r.json(); throw new Error(d.detail); }
      const d = await r.json(); setTranscript(d.transcript); toast(`Transcript loaded (${d.language})`);
    } catch (e: any) { toast(e.message, "err"); }
    finally { setTL(false); }
  }

  async function askQuestion(q?: string) {
    const finalQ = q ?? question.trim();
    if (!finalQ) return;
    setQuestion(finalQ); setAnswer(""); setAnswering(true);
    const ctrl = new AbortController(); abortRef.current = ctrl;
    try {
      const res = await fetch(`${API}/api/youtube/analyze/stream`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url, question: finalQ, transcript }),
        signal: ctrl.signal,
      });
      const reader = res.body!.getReader(); const dec = new TextDecoder(); let buf = "";
      while (true) {
        const { done, value } = await reader.read(); if (done) break;
        buf += dec.decode(value, { stream: true });
        const lines = buf.split("\n"); buf = lines.pop() ?? "";
        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const ev = JSON.parse(line.slice(6));
          if (ev.type === "delta") setAnswer(p => p + ev.text);
          else if (ev.type === "error") { toast(ev.message, "err"); break; }
        }
      }
    } catch (e: any) { if (e.name !== "AbortError") toast(e.message, "err"); }
    finally { setAnswering(false); }
  }

  const quickQ = ["لخّص هذا الفيديو", "ما أهم النقاط؟", "ما رأيك في المحتوى؟", "Summarize in English"];
  const fmtDur = (s: number) => `${Math.floor(s/60)}:${String(s%60).padStart(2,"0")}`;
  const fmtNum = (n: number) => n >= 1e6 ? `${(n/1e6).toFixed(1)}M` : n >= 1e3 ? `${(n/1e3).toFixed(1)}K` : String(n);

  return (
    <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>
      {/* Left panel */}
      <div style={{ width: 340, borderRight: "1px solid rgba(255,255,255,.05)", display: "flex", flexDirection: "column", background: "rgba(8,10,20,.6)", flexShrink: 0 }}>
        <div style={{ padding: 16, borderBottom: "1px solid rgba(255,255,255,.05)" }}>
          <div style={{ fontSize: 12, color: "rgba(148,163,184,.5)", marginBottom: 8, fontWeight: 500 }}>رابط الفيديو</div>
          <div style={{ display: "flex", gap: 8 }}>
            <input value={url} onChange={e => setUrl(e.target.value)}
              onKeyDown={e => e.key === "Enter" && fetchInfo()}
              placeholder="https://youtube.com/watch?v=..." style={{ ...S.textInput, flex: 1, fontSize: 12 }} />
            <button onClick={fetchInfo} disabled={loading || !url.trim()} style={{ ...S.btnPrimary, padding: "0 14px", flexShrink: 0 }}>
              {loading ? "…" : "→"}
            </button>
          </div>
        </div>

        {/* Video card */}
        {info && (
          <div style={{ padding: 16, borderBottom: "1px solid rgba(255,255,255,.05)", overflowY: "auto" }}>
            {info.thumbnail && (
              <div style={{ borderRadius: 12, overflow: "hidden", marginBottom: 12, position: "relative" }}>
                <img src={info.thumbnail} alt="" style={{ width: "100%", display: "block", aspectRatio: "16/9", objectFit: "cover" }} />
                <div style={{ position: "absolute", bottom: 8, right: 8, background: "rgba(0,0,0,.8)", color: "#fff", fontSize: 11, padding: "2px 7px", borderRadius: 5, fontFamily: "monospace" }}>
                  {fmtDur(info.duration)}
                </div>
              </div>
            )}
            <div style={{ fontSize: 14, fontWeight: 600, color: "#f1f5f9", lineHeight: 1.4, marginBottom: 6 }}>{info.title}</div>
            <div style={{ fontSize: 12, color: "rgba(148,163,184,.6)", marginBottom: 10 }}>{info.channel}</div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 10 }}>
              {[["👁", fmtNum(info.view_count), "مشاهدة"], ["👍", fmtNum(info.like_count || 0), "إعجاب"]].map(([icon,val,label]) => (
                <div key={label} style={{ background: "rgba(255,255,255,.05)", borderRadius: 8, padding: "5px 10px", fontSize: 12, color: "#e2e8f0", display: "flex", gap: 4, alignItems: "center" }}>
                  {icon} {val} <span style={{ color: "rgba(148,163,184,.4)" }}>{label}</span>
                </div>
              ))}
            </div>
            {info.description && <div style={{ fontSize: 12, color: "rgba(148,163,184,.5)", lineHeight: 1.6 }}>{info.description}</div>}
            <button onClick={fetchTranscript} disabled={transcriptLoading}
              style={{ ...S.btnSecondary, width: "100%", marginTop: 12, fontSize: 12 }}>
              {transcriptLoading ? "⏳ جاري استخراج النص…" : transcript ? "✅ النص مُحمَّل" : "📄 استخرج النص"}
            </button>
          </div>
        )}

        {/* Quick questions */}
        {info && (
          <div style={{ padding: 12 }}>
            <div style={{ fontSize: 11, color: "rgba(148,163,184,.4)", marginBottom: 8, fontWeight: 600 }}>أسئلة سريعة</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              {quickQ.map(q => (
                <button key={q} onClick={() => askQuestion(q)}
                  style={{ ...S.btnSecondary, fontSize: 12, textAlign: "left", padding: "8px 12px", borderRadius: 8 }}>
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Right panel — chat */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        {!info ? (
          <div style={{ margin: "auto", textAlign: "center", color: "rgba(148,163,184,.3)" }}>
            <div style={{ fontSize: 64, marginBottom: 16 }}>▶</div>
            <div style={{ fontSize: 18, fontWeight: 600, color: "rgba(148,163,184,.5)", marginBottom: 8 }}>YouTube Analyzer</div>
            <div style={{ fontSize: 14 }}>الصق رابط فيديو وابدأ التحليل بالذكاء الاصطناعي</div>
          </div>
        ) : (
          <>
            <div style={{ flex: 1, overflowY: "auto", padding: "24px 32px", display: "flex", flexDirection: "column", gap: 16 }}>
              {!answer && !answering && (
                <div style={{ textAlign: "center", color: "rgba(148,163,184,.3)", padding: "40px 0" }}>
                  <div style={{ fontSize: 32, marginBottom: 10 }}>💬</div>
                  <div>اسأل Claude عن محتوى الفيديو</div>
                </div>
              )}
              {(answer || answering) && (
                <div style={{ display: "flex", gap: 14, alignItems: "flex-start" }}>
                  <div style={S.avatar}><span style={{ fontSize: 18 }}>◈</span></div>
                  <div>
                    <div style={S.msgLabelAssist}>Claude</div>
                    {answering && !answer ? (
                      <div className="typing"><span /><span /><span /></div>
                    ) : (
                      <div style={{ fontSize: 15, color: "#e2e8f0", lineHeight: 1.8 }} className="md-body">
                        <ReactMarkdown>{answer}</ReactMarkdown>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
            <div style={S.inputRow}>
              <input value={question} onChange={e => setQuestion(e.target.value)}
                onKeyDown={e => e.key === "Enter" && askQuestion()}
                placeholder="اسأل عن الفيديو…"
                style={{ ...S.input, borderRadius: 12, padding: "12px 16px" }} />
              <button onClick={() => askQuestion()} disabled={answering || !question.trim()} style={S.sendBtn}>↑</button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// ── Facebook / Social Tab ──────────────────────────────────────────────────────
function FacebookPage({ toast }: { toast: (m: string, k?: "ok"|"err"|"info") => void }) {
  const [topic, setTopic]       = useState("");
  const [platform, setPlatform] = useState("facebook");
  const [contentType, setCType] = useState("post");
  const [tone, setTone]         = useState("engaging");
  const [language, setLanguage] = useState("arabic");
  const [hashtags, setHashtags] = useState(true);
  const [emoji, setEmoji]       = useState(true);
  const [variations, setVars]   = useState<SocialVariation[]>([]);
  const [generating, setGen]    = useState(false);
  const [status, setStatus]     = useState("");
  const [copied, setCopied]     = useState<number | null>(null);

  async function generate() {
    if (!topic.trim()) return;
    setGen(true); setVars([]); setStatus("Connecting…");
    try {
      const res = await fetch(`${API}/api/social/generate/stream`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ topic, platform, content_type: contentType, tone, language, include_hashtags: hashtags, include_emoji: emoji, variations: 3 }),
      });
      const reader = res.body!.getReader(); const dec = new TextDecoder(); let buf = "";
      while (true) {
        const { done, value } = await reader.read(); if (done) break;
        buf += dec.decode(value, { stream: true });
        const lines = buf.split("\n"); buf = lines.pop() ?? "";
        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const ev = JSON.parse(line.slice(6));
          if (ev.type === "status")    setStatus(ev.message);
          else if (ev.type === "variation") setVars(p => [...p, ev.data]);
          else if (ev.type === "done") { setStatus(""); toast(`تم توليد ${ev.count} نسخ`); }
          else if (ev.type === "error") { setStatus(""); toast(ev.message, "err"); }
        }
      }
    } catch (e: any) { toast(e.message, "err"); setStatus(""); }
    finally { setGen(false); }
  }

  function copy(text: string, i: number) {
    navigator.clipboard.writeText(text);
    setCopied(i); setTimeout(() => setCopied(null), 2000);
    toast("تم النسخ");
  }

  const platformIcon: Record<string,string> = { facebook:"📘", instagram:"📸", twitter:"🐦", linkedin:"💼" };
  const Select = ({ value, onChange, opts }: { value: string; onChange: (v:string)=>void; opts: [string,string][] }) => (
    <select value={value} onChange={e => onChange(e.target.value)} style={{ ...S.textInput, cursor: "pointer" }}>
      {opts.map(([v,l]) => <option key={v} value={v}>{l}</option>)}
    </select>
  );

  return (
    <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>
      {/* Settings panel */}
      <div style={{ width: 300, borderRight: "1px solid rgba(255,255,255,.05)", overflowY: "auto", padding: 20, display: "flex", flexDirection: "column", gap: 16, background: "rgba(8,10,20,.6)", flexShrink: 0 }}>
        <div>
          <label style={S.label}>المنصة</label>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
            {(["facebook","instagram","twitter","linkedin"] as const).map(p => (
              <button key={p} onClick={() => setPlatform(p)}
                style={{ padding: "9px 6px", borderRadius: 10, border: "none", cursor: "pointer", fontSize: 13, fontWeight: 500, transition: "all .18s",
                  background: platform === p ? "linear-gradient(135deg,#8b5cf6,#6366f1)" : "rgba(255,255,255,.05)",
                  color: platform === p ? "#fff" : "rgba(148,163,184,.6)",
                  boxShadow: platform === p ? "0 2px 12px rgba(139,92,246,.3)" : "none" }}>
                {platformIcon[p]} {p.charAt(0).toUpperCase()+p.slice(1)}
              </button>
            ))}
          </div>
        </div>
        <div>
          <label style={S.label}>نوع المحتوى</label>
          <Select value={contentType} onChange={setCType} opts={[["post","منشور عادي"],["ad","إعلان مدفوع"],["story","ستوري"],["reel_caption","كابشن ريلز"],["thread","ثريد"]]} />
        </div>
        <div>
          <label style={S.label}>الأسلوب</label>
          <Select value={tone} onChange={setTone} opts={[["engaging","جذاب وتفاعلي"],["professional","احترافي ورسمي"],["funny","مرح وفكاهي"],["inspirational","ملهم وتحفيزي"],["urgent","عاجل ومُلحّ"]]} />
        </div>
        <div>
          <label style={S.label}>اللغة</label>
          <Select value={language} onChange={setLanguage} opts={[["arabic","عربي"],["english","English"],["both","عربي + English"]]} />
        </div>
        <div style={{ display: "flex", justifyContent: "space-between" }}>
          <label style={{ ...S.label, marginBottom: 0, cursor: "pointer", display: "flex", alignItems: "center", gap: 8 }}>
            <input type="checkbox" checked={hashtags} onChange={e => setHashtags(e.target.checked)} /> هاشتاقات
          </label>
          <label style={{ ...S.label, marginBottom: 0, cursor: "pointer", display: "flex", alignItems: "center", gap: 8 }}>
            <input type="checkbox" checked={emoji} onChange={e => setEmoji(e.target.checked)} /> إيموجي
          </label>
        </div>
        <div>
          <label style={S.label}>الموضوع / المنتج / الفكرة *</label>
          <textarea value={topic} onChange={e => setTopic(e.target.value)}
            placeholder={"مثال: متجر إلكتروني يبيع عطوراً فاخرة، عرض خصم 30%"}
            style={{ ...S.textInput, minHeight: 100, lineHeight: 1.6 }} />
        </div>
        <button onClick={generate} disabled={generating || !topic.trim()} style={{ ...S.btnPrimary, width: "100%", padding: "12px" }}>
          {generating ? "⏳ جاري التوليد…" : "✨ ولّد المحتوى"}
        </button>
        {status && <div style={{ fontSize: 12, color: "#a78bfa", textAlign: "center" }}>{status}</div>}
      </div>

      {/* Results panel */}
      <div style={{ flex: 1, overflowY: "auto", padding: 24, display: "flex", flexDirection: "column", gap: 16 }}>
        {variations.length === 0 && !generating && (
          <div style={{ margin: "auto", textAlign: "center", color: "rgba(148,163,184,.3)" }}>
            <div style={{ fontSize: 56, marginBottom: 14 }}>{platformIcon[platform]}</div>
            <div style={{ fontSize: 18, fontWeight: 600, color: "rgba(148,163,184,.5)", marginBottom: 8 }}>
              منشئ محتوى السوشيال ميديا
            </div>
            <div style={{ fontSize: 14, maxWidth: 340, lineHeight: 1.7 }}>
              أدخل موضوعك في الإعدادات واضغط "ولّد المحتوى" للحصول على 3 نسخ احترافية
            </div>
          </div>
        )}
        {variations.map((v, i) => (
          <div key={i} style={{ ...S.card, display: "flex", flexDirection: "column", gap: 14, animation: "slideIn .25s ease" }} className="card-hover">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{ width: 28, height: 28, borderRadius: 8, background: "linear-gradient(135deg,#8b5cf6,#6366f1)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 12, fontWeight: 700, color: "#fff" }}>{i + 1}</span>
                <span style={{ fontSize: 13, fontWeight: 600, color: "#f1f5f9" }}>النسخة {i + 1}</span>
              </div>
              <div style={{ display: "flex", gap: 6 }}>
                <button onClick={() => copy(v.text + (v.hashtags?.length ? "\n\n" + v.hashtags.join(" ") : ""), i)}
                  style={{ ...S.btnSecondary, fontSize: 12, padding: "5px 12px" }}>
                  {copied === i ? "✅ تم النسخ" : "📋 نسخ"}
                </button>
              </div>
            </div>
            <div style={{ fontSize: 15, color: "#e2e8f0", lineHeight: 1.85, whiteSpace: "pre-wrap", direction: language === "english" ? "ltr" : "rtl", textAlign: language === "english" ? "left" : "right" }}>
              {v.text}
            </div>
            {v.hashtags && v.hashtags.length > 0 && (
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {v.hashtags.map((h: string) => (
                  <span key={h} style={{ background: "rgba(139,92,246,.15)", border: "1px solid rgba(139,92,246,.25)", borderRadius: 20, padding: "3px 10px", fontSize: 12, color: "#c4b5fd" }}>
                    {h.startsWith("#") ? h : `#${h}`}
                  </span>
                ))}
              </div>
            )}
            {v.tip && (
              <div style={{ fontSize: 12, color: "rgba(148,163,184,.5)", borderTop: "1px solid rgba(255,255,255,.05)", paddingTop: 10, fontStyle: "italic" }}>
                💡 {v.tip}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Projects Page ─────────────────────────────────────────────────────────────
function ProjectsPage() {
  const toast = useToast();
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading]   = useState(true);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName]   = useState("");
  const [newDesc, setNewDesc]   = useState("");
  const [saving, setSaving]     = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try { const r = await fetch(`${API}/api/projects`); setProjects(await r.json()); }
    catch { toast("Could not load projects", "err"); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  async function create() {
    if (!newName.trim()) return;
    setSaving(true);
    try {
      const r = await fetch(`${API}/api/projects`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: newName.trim(), description: newDesc.trim() || null }) });
      if (!r.ok) throw new Error();
      setNewName(""); setNewDesc(""); setCreating(false); load(); toast("Project created");
    } catch { toast("Failed to create", "err"); }
    finally { setSaving(false); }
  }

  async function del(id: string, name: string) {
    if (!confirm(`Delete "${name}"?`)) return;
    await fetch(`${API}/api/projects/${id}`, { method: "DELETE" });
    toast(`Deleted "${name}"`); load();
  }

  return (
    <>
      <header style={S.header}>
        <span style={S.headerTitle}>Projects</span>
        <button onClick={() => setCreating(true)} style={S.btnPrimary}>+ New Project</button>
      </header>
      <div style={{ flex: 1, overflowY: "auto", padding: 24 }}>
        {creating && (
          <div style={{ ...S.card, marginBottom: 16 }}>
            <div style={S.cardTitle}>New Project</div>
            <input value={newName} onChange={e => setNewName(e.target.value)} placeholder="Project name *" style={{ ...S.textInput, marginTop: 12 }} autoFocus />
            <input value={newDesc} onChange={e => setNewDesc(e.target.value)} placeholder="Description (optional)" style={{ ...S.textInput, marginTop: 10 }} />
            <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
              <button onClick={create} disabled={saving || !newName.trim()} style={S.btnPrimary}>{saving ? "Saving…" : "Create"}</button>
              <button onClick={() => { setCreating(false); setNewName(""); setNewDesc(""); }} style={S.btnSecondary}>Cancel</button>
            </div>
          </div>
        )}
        {loading && <div style={S.muted}>Loading…</div>}
        {!loading && projects.length === 0 && !creating && <div style={S.emptyState}><div style={{ fontSize: 32, marginBottom: 10 }}>📁</div><div style={{ color: "#c8d3f0", fontWeight: 600 }}>No projects yet</div></div>}
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {projects.map(p => (
            <div key={p.id} style={S.card}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                <div style={{ flex: 1 }}>
                  <div style={S.cardTitle}>{p.name}</div>
                  {p.description && <div style={{ ...S.muted, marginTop: 4 }}>{p.description}</div>}
                  <div style={{ ...S.muted, marginTop: 8, fontSize: 11 }}>
                    Created {new Date(p.created_at).toLocaleDateString()} · <span style={{ color: p.status === "active" ? "#34d399" : "#f87171", fontWeight: 600 }}>{p.status}</span>
                  </div>
                </div>
                {p.id !== "00000000-0000-0000-0000-000000000001" && (
                  <button onClick={() => del(p.id, p.name)} style={{ background: "none", border: "none", color: "#4b5980", cursor: "pointer", fontSize: 16, padding: 4 }}>🗑</button>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    </>
  );
}

// ── Settings Page ─────────────────────────────────────────────────────────────
function SettingsPage() {
  const toast = useToast();
  const [health, setHealth] = useState<Record<string, string> | null>(null);
  const [stats, setStats]   = useState<Record<string, number> | null>(null);

  useEffect(() => {
    fetch(`${API}/health`).then(r => r.json()).then(setHealth).catch(() => {});
    fetch(`${API}/api/stats`).then(r => r.json()).then(setStats).catch(() => {});
  }, []);

  return (
    <>
      <header style={S.header}><span style={S.headerTitle}>Settings</span></header>
      <div style={{ flex: 1, overflowY: "auto", padding: 24, display: "flex", flexDirection: "column", gap: 16 }}>
        <div style={S.card}>
          <div style={S.cardTitle}>Backend Status</div>
          {health ? (
            <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 8 }}>
              <Row label="Status"     value={<span style={{ color: "#34d399", fontWeight: 600 }}>● {health.status}</span>} />
              <Row label="Database"   value={health.db} />
              <Row label="PostgreSQL" value={health.pg_version?.split(" on ")[0]} />
            </div>
          ) : (
            <div style={{ color: "#f87171", marginTop: 8, fontSize: 13 }}>⚠️ Backend offline — run <code style={S.code}>python main.py</code></div>
          )}
        </div>
        {stats && (
          <div style={S.card}>
            <div style={S.cardTitle}>Usage Statistics</div>
            <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 8 }}>
              <Row label="Projects"      value={String(stats.projects)} />
              <Row label="Conversations" value={String(stats.conversations)} />
              <Row label="Messages"      value={String(stats.messages)} />
              <Row label="Agent Runs"    value={String(stats.agent_runs)} />
              <Row label="Success Rate"  value={`${stats.success_rate}%`} />
            </div>
          </div>
        )}
        <div style={S.card}>
          <div style={S.cardTitle}>API Key</div>
          <div style={{ ...S.muted, margin: "6px 0 10px" }}>Update ANTHROPIC_API_KEY in .env and restart the backend.</div>
          <input type="password" defaultValue="sk-ant-api03-••••••••" style={S.textInput} readOnly />
          <a href="https://console.anthropic.com/settings/billing" target="_blank" style={{ display: "block", marginTop: 8, fontSize: 12, color: "#6c8ef7" }}>
            Add credits → console.anthropic.com/settings/billing ↗
          </a>
        </div>
        <div style={S.card}>
          <div style={S.cardTitle}>About</div>
          <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 6 }}>
            <Row label="App"      value="AI Automation Studio" />
            <Row label="Version"  value="3.0.0" />
            <Row label="Frontend" value="React 19 + Vite 8" />
            <Row label="Backend"  value="FastAPI + asyncpg" />
            <Row label="Database" value="PostgreSQL 18" />
          </div>
        </div>
      </div>
    </>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13 }}>
      <span style={{ color: "#6b7a99" }}>{label}</span>
      <span style={{ color: "#c8d3f0", fontWeight: 500 }}>{value}</span>
    </div>
  );
}

function relTime(iso: string) {
  const s = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return new Date(iso).toLocaleDateString();
}

// ── Root ──────────────────────────────────────────────────────────────────────
export default function App() {
  const [page, setPage] = useState<Page>("dashboard");

  const nav: [Page, string, string][] = [
    ["dashboard", "📊", "Dashboard"],
    ["chat",      "💬", "Chat"],
    ["agents",    "🤖", "Agents"],
    ["build",     "🔨", "Build"],
    ["social",    "🌐", "Social"],
    ["projects",  "📁", "Projects"],
    ["settings",  "⚙️",  "Settings"],
  ];

  return (
    <ToastProvider>
      <div style={S.root}>
        <aside style={S.sidebar}>
          <div style={S.sidebarLogo}>◈ AI Studio</div>
          <nav style={S.nav}>
            {nav.map(([id, icon, label]) => (
              <div key={id} onClick={() => setPage(id)}
                className="nav-item"
              style={{ ...S.navItem, ...(page === id ? S.navItemActive : {}) }}>
                <span style={{ fontSize: 16 }}>{icon}</span> {label}
              </div>
            ))}
          </nav>
          <div style={{ marginTop: "auto", padding: "0 10px 16px" }}>
            <div style={{ fontSize: 11, color: "#2a3050", textAlign: "center" }}>v3.0 · Powered by Claude</div>
          </div>
        </aside>

        <main style={S.main}>
          {page === "dashboard" && <DashboardPage />}
          {page === "chat"      && <ChatPage />}
          {page === "agents"    && <AgentsPage />}
          {page === "build"     && <BuildPage />}
          {page === "social"    && <SocialPage />}
          {page === "projects"  && <ProjectsPage />}
          {page === "settings"  && <SettingsPage />}
        </main>

        <style>{`
          @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

          *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
          body { margin: 0; font-family: 'Inter', 'Segoe UI', system-ui, sans-serif; }
          textarea { resize: none; }
          *:focus { outline: none; }

          ::-webkit-scrollbar { width: 4px; height: 4px; }
          ::-webkit-scrollbar-track { background: transparent; }
          ::-webkit-scrollbar-thumb { background: rgba(139,92,246,.3); border-radius: 4px; }
          ::-webkit-scrollbar-thumb:hover { background: rgba(139,92,246,.6); }

          input::placeholder, textarea::placeholder { color: rgba(148,163,184,.35); }
          input, textarea, select { font-family: inherit; }

          /* Focus glow */
          input:focus, textarea:focus, select:focus {
            box-shadow: 0 0 0 2px rgba(139,92,246,.4) !important;
            border-color: rgba(139,92,246,.6) !important;
          }

          /* Animations */
          @keyframes bounce { 0%,80%,100% { transform:translateY(0);opacity:.4 } 40% { transform:translateY(-6px);opacity:1 } }
          @keyframes slideIn { from { opacity:0;transform:translateY(8px) } to { opacity:1;transform:translateY(0) } }
          @keyframes fadeIn  { from { opacity:0 } to { opacity:1 } }
          @keyframes pulse   { 0%,100% { opacity:1 } 50% { opacity:.5 } }
          @keyframes shimmer { 0% { background-position: -200% 0 } 100% { background-position: 200% 0 } }

          /* Typing dots */
          .typing { display:flex;align-items:center;gap:4px;padding:4px 0 }
          .typing span { display:inline-block;width:7px;height:7px;border-radius:50%;background:linear-gradient(135deg,#8b5cf6,#6366f1);animation:bounce 1.4s infinite }
          .typing span:nth-child(2) { animation-delay:.2s }
          .typing span:nth-child(3) { animation-delay:.4s }

          /* Hover transitions */
          .nav-item { transition: all .18s cubic-bezier(.4,0,.2,1) !important; }
          .nav-item:hover { background: rgba(139,92,246,.08) !important; color: #e2e8f0 !important; transform: translateX(2px); }
          .card-hover { transition: border-color .2s, box-shadow .2s, transform .2s !important; }
          .card-hover:hover { border-color: rgba(139,92,246,.4) !important; box-shadow: 0 0 24px rgba(139,92,246,.08) !important; transform: translateY(-1px); }
          .btn-primary-hover { transition: all .18s !important; }
          .btn-primary-hover:hover { filter: brightness(1.1); transform: translateY(-1px); box-shadow: 0 4px 20px rgba(139,92,246,.4) !important; }
          .btn-primary-hover:active { transform: translateY(0); }

          /* Message rows centering */
          .msg-row { align-self: stretch; }

          /* Markdown — tuned for 15px base */
          .md-body { line-height: 1.8; font-size: 15px; color: #e2e8f0; }
          .md-body p { margin: 0 0 12px; }
          .md-body p:last-child { margin: 0; }
          .md-body pre {
            background: rgba(0,0,0,.45);
            border: 1px solid rgba(139,92,246,.18);
            border-radius: 14px; padding: 18px 20px;
            overflow-x: auto; margin: 14px 0;
            font-family: 'JetBrains Mono', 'Consolas', monospace;
          }
          .md-body code {
            background: rgba(139,92,246,.14);
            padding: 2px 8px; border-radius: 6px;
            font-size: 13px; color: #c4b5fd;
            font-family: 'JetBrains Mono', 'Consolas', monospace;
          }
          .md-body pre code { background: none; padding: 0; color: #e2e8f0; font-size: 13.5px; }
          .md-body ul, .md-body ol { padding-left: 24px; margin: 8px 0; }
          .md-body li { margin: 5px 0; line-height: 1.7; }
          .md-body h1 { font-size: 20px; font-weight: 700; color: #f1f5f9; margin: 20px 0 10px; letter-spacing: -.3px; }
          .md-body h2 { font-size: 17px; font-weight: 600; color: #f1f5f9; margin: 18px 0 8px; }
          .md-body h3 { font-size: 15px; font-weight: 600; color: #e2e8f0; margin: 14px 0 6px; }
          .md-body strong { color: #f1f5f9; font-weight: 600; }
          .md-body em { color: #c4b5fd; }
          .md-body a { color: #818cf8; text-decoration: none; border-bottom: 1px solid rgba(129,140,248,.3); }
          .md-body a:hover { border-bottom-color: #818cf8; }
          .md-body blockquote {
            border-left: 3px solid rgba(139,92,246,.5);
            padding: 4px 0 4px 16px; margin: 12px 0;
            color: #94a3b8; font-style: italic;
          }
          .md-body hr { border: none; border-top: 1px solid rgba(255,255,255,.07); margin: 16px 0; }
          .md-body table { border-collapse: collapse; width: 100%; margin: 14px 0; border-radius: 10px; overflow: hidden; }
          .md-body th, .md-body td { border: 1px solid rgba(255,255,255,.06); padding: 10px 16px; font-size: 14px; }
          .md-body th { background: rgba(139,92,246,.14); color: #e2e8f0; font-weight: 600; }
          .md-body tr:nth-child(even) td { background: rgba(255,255,255,.02); }
        `}</style>
      </div>
    </ToastProvider>
  );
}

// ── Styles ────────────────────────────────────────────────────────────────────
// Palette: deep space bg · violet/indigo accent · glass cards
const S: Record<string, React.CSSProperties> = {
  // Layout
  root: {
    display: "flex", height: "100vh", overflow: "hidden",
    background: "linear-gradient(135deg, #05070f 0%, #080c1a 50%, #05070f 100%)",
    color: "#e2e8f0", fontFamily: "'Inter','Segoe UI',system-ui,sans-serif",
  },

  // Sidebar
  sidebar: {
    width: 220, flexShrink: 0, display: "flex", flexDirection: "column",
    background: "rgba(8,10,20,.85)", backdropFilter: "blur(20px)",
    borderRight: "1px solid rgba(139,92,246,.12)",
    padding: "0 0 16px",
  },
  sidebarLogo: {
    padding: "22px 20px 18px",
    borderBottom: "1px solid rgba(139,92,246,.1)",
    marginBottom: 10,
    fontSize: 16, fontWeight: 700, letterSpacing: "-0.3px",
    background: "linear-gradient(135deg, #a78bfa, #6366f1)",
    WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent",
  },
  nav:           { display: "flex", flexDirection: "column", gap: 2, padding: "0 10px" },
  navItem: {
    padding: "10px 14px", borderRadius: 10, fontSize: 13, fontWeight: 500,
    color: "rgba(148,163,184,.7)", cursor: "pointer",
    display: "flex", alignItems: "center", gap: 10,
    transition: "all .18s",
  },
  navItemActive: {
    background: "linear-gradient(135deg, rgba(139,92,246,.2), rgba(99,102,241,.15))",
    color: "#e2e8f0",
    boxShadow: "inset 0 0 0 1px rgba(139,92,246,.25), 0 0 20px rgba(139,92,246,.08)",
  },
  main: { flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" },

  // Header
  header: {
    padding: "16px 28px",
    borderBottom: "1px solid rgba(255,255,255,.05)",
    display: "flex", justifyContent: "space-between", alignItems: "center", flexShrink: 0,
    background: "rgba(8,10,20,.6)", backdropFilter: "blur(12px)",
  },
  headerTitle: { fontSize: 16, fontWeight: 600, color: "#f1f5f9", letterSpacing: "-0.2px" },
  headerSub:   { fontSize: 12, color: "rgba(148,163,184,.5)", fontWeight: 400 },

  // Cards
  card: {
    background: "rgba(255,255,255,.03)",
    border: "1px solid rgba(255,255,255,.07)",
    borderRadius: 16, padding: "20px 22px",
    backdropFilter: "blur(10px)",
  },
  cardTitle: { fontSize: 14, fontWeight: 600, color: "#f1f5f9", letterSpacing: "-0.1px" },
  muted:     { fontSize: 13, color: "rgba(148,163,184,.6)", lineHeight: 1.5 },
  emptyState:{ textAlign: "center", padding: "60px 20px", color: "rgba(148,163,184,.4)" },

  // Chat sidebar
  chatSidebar: {
    width: 230, flexShrink: 0, display: "flex", flexDirection: "column",
    background: "rgba(8,10,20,.7)", backdropFilter: "blur(16px)",
    borderRight: "1px solid rgba(255,255,255,.05)",
  },
  projectSelect: {
    width: "100%", background: "rgba(255,255,255,.04)",
    border: "1px solid rgba(255,255,255,.08)", borderRadius: 10,
    padding: "8px 12px", color: "#e2e8f0", fontSize: 12,
    cursor: "pointer", transition: "border-color .2s",
  },
  newChatBtn: {
    width: "100%", background: "rgba(139,92,246,.1)",
    border: "1px solid rgba(139,92,246,.2)", borderRadius: 10,
    padding: "9px 12px", color: "rgba(167,139,250,.8)", fontSize: 12,
    cursor: "pointer", textAlign: "left", transition: "all .18s",
  },
  convItem:      { padding: "10px 14px", cursor: "pointer", transition: "background .15s" },
  convItemActive:{ background: "rgba(139,92,246,.1)", borderRight: "2px solid #8b5cf6" },
  convTitle:     { fontSize: 12, fontWeight: 500, color: "#e2e8f0", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" },
  convTime:      { fontSize: 10, color: "rgba(148,163,184,.4)" },

  // Messages
  messages: {
    flex: 1, overflowY: "auto", padding: "32px 0",
    display: "flex", flexDirection: "column", gap: 0,
  },
  empty: { margin: "auto", textAlign: "center", color: "rgba(148,163,184,.35)", paddingBottom: 80 },

  // New message rows
  msgRowAssist: {
    display: "flex", gap: 14, alignItems: "flex-start",
    padding: "18px 32px", maxWidth: 900, width: "100%",
    animation: "slideIn .22s ease",
  },
  msgRowUser: {
    display: "flex", gap: 14, alignItems: "flex-start",
    padding: "18px 32px", maxWidth: 900, width: "100%",
    alignSelf: "flex-end", flexDirection: "row-reverse",
    animation: "slideIn .22s ease",
  },
  avatar: {
    width: 36, height: 36, borderRadius: 10, flexShrink: 0,
    background: "linear-gradient(135deg, rgba(139,92,246,.3), rgba(99,102,241,.2))",
    border: "1px solid rgba(139,92,246,.25)",
    display: "flex", alignItems: "center", justifyContent: "center",
    marginTop: 2,
  },
  avatarUser: {
    width: 36, height: 36, borderRadius: 10, flexShrink: 0,
    background: "linear-gradient(135deg, #6366f1, #8b5cf6)",
    display: "flex", alignItems: "center", justifyContent: "center",
    fontSize: 13, fontWeight: 700, color: "#fff", marginTop: 2,
  },
  msgLabelAssist: {
    fontSize: 12, fontWeight: 600, color: "rgba(167,139,250,.8)",
    marginBottom: 8, display: "flex", alignItems: "center", gap: 8,
    letterSpacing: "0.02em",
  },
  msgLabelUser: {
    fontSize: 12, fontWeight: 600, color: "rgba(148,163,184,.5)",
    marginBottom: 8, display: "flex", alignItems: "center", gap: 8,
    justifyContent: "flex-end", letterSpacing: "0.02em",
  },
  msgTime: { fontSize: 10, color: "rgba(148,163,184,.3)", fontWeight: 400 },
  msgBubbleAssist: {
    fontSize: 15, color: "#e2e8f0", lineHeight: 1.8,
    fontWeight: 400,
  },
  msgBubbleUser: {
    fontSize: 15, color: "#e2e8f0", lineHeight: 1.75,
    background: "linear-gradient(135deg, rgba(99,102,241,.22), rgba(139,92,246,.18))",
    border: "1px solid rgba(139,92,246,.28)",
    borderRadius: 16, borderTopRightRadius: 4,
    padding: "12px 18px",
    boxShadow: "0 2px 16px rgba(99,102,241,.1)",
    display: "inline-block",
  },

  // Input row
  inputRow: {
    padding: "16px 24px", gap: 12,
    borderTop: "1px solid rgba(255,255,255,.05)",
    display: "flex", alignItems: "flex-end",
    background: "rgba(8,10,20,.6)", backdropFilter: "blur(12px)",
  },
  input: {
    flex: 1, fontSize: 14, lineHeight: 1.6,
    background: "rgba(255,255,255,.04)",
    border: "1px solid rgba(255,255,255,.08)",
    borderRadius: 14, padding: "12px 16px",
    color: "#e2e8f0", maxHeight: 160, overflowY: "auto",
    transition: "border-color .2s, box-shadow .2s",
  },
  sendBtn: {
    width: 44, height: 44, borderRadius: 12, flexShrink: 0,
    background: "linear-gradient(135deg, #8b5cf6, #6366f1)",
    color: "#fff", border: "none", fontSize: 18, cursor: "pointer",
    display: "flex", alignItems: "center", justifyContent: "center",
    boxShadow: "0 4px 16px rgba(139,92,246,.4)",
    transition: "all .18s",
  },

  // Forms
  textInput: {
    width: "100%", fontSize: 13,
    background: "rgba(255,255,255,.04)",
    border: "1px solid rgba(255,255,255,.08)",
    borderRadius: 10, padding: "10px 14px",
    color: "#e2e8f0", transition: "border-color .2s, box-shadow .2s",
  },
  label: { fontSize: 12, color: "rgba(148,163,184,.6)", display: "block", marginBottom: 6, fontWeight: 500 },

  // Buttons
  btnPrimary: {
    background: "linear-gradient(135deg, #8b5cf6, #6366f1)",
    color: "#fff", border: "none", borderRadius: 10,
    padding: "9px 20px", fontSize: 13, fontWeight: 600, cursor: "pointer",
    boxShadow: "0 4px 14px rgba(139,92,246,.35)",
    transition: "all .18s",
  },
  btnSecondary: {
    background: "rgba(255,255,255,.05)",
    color: "rgba(148,163,184,.8)",
    border: "1px solid rgba(255,255,255,.08)",
    borderRadius: 10, padding: "9px 20px", fontSize: 13, cursor: "pointer",
    transition: "all .18s",
  },

  // Misc
  code: {
    background: "rgba(139,92,246,.15)", padding: "2px 8px",
    borderRadius: 6, fontSize: 12, color: "#c4b5fd",
    fontFamily: "'Consolas','Courier New',monospace",
  },
};
