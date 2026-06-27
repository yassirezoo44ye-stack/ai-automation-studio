import { useState, useRef, useEffect, useCallback } from "react";

type Page = "chat" | "projects" | "settings";

type Message = { id: string; role: "user" | "assistant"; content: string };

type Project = {
  id: string; name: string; description: string;
  status: string; created_at: string;
};

const API = "http://127.0.0.1:8000";

// ─── Chat Page ────────────────────────────────────────────────────────────────
function ChatPage() {
  const [prompt, setPrompt] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages]);

  async function sendMessage() {
    const text = prompt.trim();
    if (!text || loading) return;
    setPrompt("");
    setMessages(prev => [...prev, { id: crypto.randomUUID(), role: "user", content: text }]);
    setLoading(true);
    try {
      const res = await fetch(`${API}/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project_id: "demo", prompt: text }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data?.detail || `Error ${res.status}`);
      setMessages(prev => [...prev, { id: crypto.randomUUID(), role: "assistant", content: data.result.summary }]);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      const offline = msg.includes("fetch") || msg.includes("Failed to fetch");
      setMessages(prev => [...prev, {
        id: crypto.randomUUID(), role: "assistant",
        content: offline ? "⚠️ Backend offline — run `python main.py` on port 8000." : `⚠️ ${msg}`,
      }]);
    } finally { setLoading(false); }
  }

  return (
    <>
      <header style={S.header}>
        <span style={S.headerTitle}>Chat with Claude</span>
        <span style={S.headerSub}>claude-sonnet-4-6 · Demo Project</span>
      </header>
      <div style={S.messages}>
        {messages.length === 0 && (
          <div style={S.empty}>
            <div style={{ fontSize: 40, color: "#6c8ef7", marginBottom: 12 }}>◈</div>
            <div style={{ fontSize: 20, fontWeight: 700, color: "#c8d3f0", marginBottom: 8 }}>AI Automation Studio</div>
            <div style={{ fontSize: 14 }}>Ask Claude anything to get started.</div>
          </div>
        )}
        {messages.map(m => (
          <div key={m.id} style={{ ...S.bubble, ...(m.role === "user" ? S.bubbleUser : S.bubbleAssist) }}>
            <div style={S.bubbleRole}>{m.role === "user" ? "You" : "Claude"}</div>
            <div style={S.bubbleText}>{m.content}</div>
          </div>
        ))}
        {loading && (
          <div style={{ ...S.bubble, ...S.bubbleAssist }}>
            <div style={S.bubbleRole}>Claude</div>
            <div className="typing"><span /><span /><span /></div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>
      <div style={S.inputRow}>
        <textarea
          value={prompt}
          onChange={e => setPrompt(e.target.value)}
          onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); } }}
          placeholder="Message Claude… (Enter to send, Shift+Enter for newline)"
          style={S.input} rows={1}
        />
        <button onClick={sendMessage} disabled={loading || !prompt.trim()} style={S.sendBtn}>
          {loading ? "…" : "↑"}
        </button>
      </div>
    </>
  );
}

// ─── Projects Page ────────────────────────────────────────────────────────────
function ProjectsPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const res = await fetch(`${API}/api/projects`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setProjects(await res.json());
    } catch { setError("Could not load projects — is the backend running?"); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  async function createProject() {
    if (!newName.trim()) return;
    setSaving(true);
    try {
      const res = await fetch(`${API}/api/projects`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: newName.trim(), description: newDesc.trim() || null }),
      });
      if (!res.ok) throw new Error();
      setNewName(""); setNewDesc(""); setCreating(false);
      load();
    } catch { alert("Failed to create project."); }
    finally { setSaving(false); }
  }

  async function deleteProject(id: string, name: string) {
    if (!confirm(`Delete "${name}"?`)) return;
    await fetch(`${API}/api/projects/${id}`, { method: "DELETE" });
    load();
  }

  return (
    <>
      <header style={S.header}>
        <span style={S.headerTitle}>Projects</span>
        <button onClick={() => setCreating(true)} style={S.btnPrimary}>+ New Project</button>
      </header>
      <div style={{ flex: 1, overflowY: "auto", padding: 24 }}>
        {creating && (
          <div style={S.card}>
            <div style={S.cardTitle}>New Project</div>
            <input
              value={newName} onChange={e => setNewName(e.target.value)}
              placeholder="Project name *" style={S.textInput} autoFocus
            />
            <input
              value={newDesc} onChange={e => setNewDesc(e.target.value)}
              placeholder="Description (optional)" style={{ ...S.textInput, marginTop: 10 }}
            />
            <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
              <button onClick={createProject} disabled={saving || !newName.trim()} style={S.btnPrimary}>
                {saving ? "Saving…" : "Create"}
              </button>
              <button onClick={() => { setCreating(false); setNewName(""); setNewDesc(""); }} style={S.btnSecondary}>
                Cancel
              </button>
            </div>
          </div>
        )}
        {loading && <div style={S.muted}>Loading projects…</div>}
        {error && <div style={{ color: "#f87171", fontSize: 13 }}>{error}</div>}
        {!loading && !error && projects.length === 0 && !creating && (
          <div style={S.emptyState}>
            <div style={{ fontSize: 32, marginBottom: 10 }}>📁</div>
            <div style={{ color: "#c8d3f0", fontWeight: 600, marginBottom: 6 }}>No projects yet</div>
            <div style={S.muted}>Click "New Project" to create one.</div>
          </div>
        )}
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {projects.map(p => (
            <div key={p.id} style={S.card}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                <div>
                  <div style={S.cardTitle}>{p.name}</div>
                  {p.description && <div style={{ ...S.muted, marginTop: 4 }}>{p.description}</div>}
                  <div style={{ ...S.muted, marginTop: 8, fontSize: 11 }}>
                    Created {new Date(p.created_at).toLocaleDateString()} ·
                    <span style={{
                      marginLeft: 6, color: p.status === "active" ? "#34d399" : "#f87171",
                      fontWeight: 600,
                    }}>{p.status}</span>
                  </div>
                </div>
                <button
                  onClick={() => deleteProject(p.id, p.name)}
                  style={{ background: "none", border: "none", color: "#4b5980", cursor: "pointer", fontSize: 16, padding: 4 }}
                  title="Delete"
                >🗑</button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </>
  );
}

// ─── Settings Page ────────────────────────────────────────────────────────────
function SettingsPage() {
  const [health, setHealth] = useState<Record<string, string> | null>(null);
  const [apiKey, setApiKey] = useState("sk-ant-api03-••••••••••••••••");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    fetch(`${API}/health`).then(r => r.json()).then(setHealth).catch(() => setHealth(null));
  }, []);

  function saveSettings() {
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  }

  return (
    <>
      <header style={S.header}>
        <span style={S.headerTitle}>Settings</span>
      </header>
      <div style={{ flex: 1, overflowY: "auto", padding: 24, display: "flex", flexDirection: "column", gap: 20 }}>

        {/* Backend status */}
        <div style={S.card}>
          <div style={S.cardTitle}>Backend Status</div>
          {health ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 10 }}>
              <Row label="Status" value={<span style={{ color: "#34d399", fontWeight: 600 }}>● {health.status}</span>} />
              <Row label="Database" value={health.db} />
              <Row label="PostgreSQL" value={health.pg_version?.split(" on ")[0]} />
              <Row label="Backend URL" value="http://127.0.0.1:8000" />
            </div>
          ) : (
            <div style={{ color: "#f87171", marginTop: 8, fontSize: 13 }}>⚠️ Backend offline — run <code style={S.code}>python main.py</code></div>
          )}
        </div>

        {/* API Key */}
        <div style={S.card}>
          <div style={S.cardTitle}>Anthropic API Key</div>
          <div style={{ ...S.muted, marginTop: 4, marginBottom: 12 }}>
            Used for all Claude requests. Get one at console.anthropic.com
          </div>
          <input
            value={apiKey} onChange={e => setApiKey(e.target.value)}
            placeholder="sk-ant-api03-…" style={S.textInput}
            type="password"
          />
          <div style={{ marginTop: 10 }}>
            <button onClick={saveSettings} style={S.btnPrimary}>
              {saved ? "✓ Saved" : "Save"}
            </button>
          </div>
          <div style={{ ...S.muted, marginTop: 10, fontSize: 11 }}>
            Note: To actually apply a new key, update ANTHROPIC_API_KEY in your .env file and restart the backend.
          </div>
        </div>

        {/* Model */}
        <div style={S.card}>
          <div style={S.cardTitle}>Model</div>
          <div style={{ marginTop: 10 }}>
            <select style={{ ...S.textInput, cursor: "pointer" }}>
              <option value="claude-sonnet-4-6">claude-sonnet-4-6 (default)</option>
              <option value="claude-opus-4-8">claude-opus-4-8 (most capable)</option>
              <option value="claude-haiku-4-5-20251001">claude-haiku-4-5-20251001 (fastest)</option>
            </select>
          </div>
        </div>

        {/* About */}
        <div style={S.card}>
          <div style={S.cardTitle}>About</div>
          <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 6 }}>
            <Row label="App" value="AI Automation Studio" />
            <Row label="Version" value="1.0.0" />
            <Row label="Frontend" value="React + Vite" />
            <Row label="Backend" value="FastAPI + asyncpg" />
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

// ─── Root App ─────────────────────────────────────────────────────────────────
export default function App() {
  const [page, setPage] = useState<Page>("chat");

  const navItems: { id: Page; icon: string; label: string }[] = [
    { id: "chat",     icon: "💬", label: "Chat"     },
    { id: "projects", icon: "📁", label: "Projects" },
    { id: "settings", icon: "⚙️",  label: "Settings" },
  ];

  return (
    <div style={S.root}>
      <aside style={S.sidebar}>
        <div style={S.sidebarLogo}>◈ AI Studio</div>
        <nav style={S.nav}>
          {navItems.map(n => (
            <div
              key={n.id}
              onClick={() => setPage(n.id)}
              style={{ ...S.navItem, ...(page === n.id ? S.navItemActive : {}) }}
            >
              {n.icon} {n.label}
            </div>
          ))}
          <a
            href="/dashboard.html"
            style={{ ...S.navItem, textDecoration: "none" }}
            target="_blank"
          >
            📊 Dashboard ↗
          </a>
        </nav>
      </aside>

      <main style={S.main}>
        {page === "chat"     && <ChatPage />}
        {page === "projects" && <ProjectsPage />}
        {page === "settings" && <SettingsPage />}
      </main>

      <style>{`
        @keyframes bounce {
          0%,80%,100%{transform:translateY(0);opacity:.4}
          40%{transform:translateY(-6px);opacity:1}
        }
        .typing span{display:inline-block;width:6px;height:6px;background:#6c8ef7;border-radius:50%;margin:0 2px;animation:bounce 1.2s infinite}
        .typing span:nth-child(2){animation-delay:.2s}
        .typing span:nth-child(3){animation-delay:.4s}
        textarea{resize:none} textarea:focus,button:focus,input:focus,select:focus{outline:none}
        *{box-sizing:border-box} body{margin:0}
        ::-webkit-scrollbar{width:6px}
        ::-webkit-scrollbar-track{background:#0d0f14}
        ::-webkit-scrollbar-thumb{background:#2a3050;border-radius:3px}
        input::placeholder,textarea::placeholder{color:#4b5980}
      `}</style>
    </div>
  );
}

// ─── Shared styles ────────────────────────────────────────────────────────────
const S: Record<string, React.CSSProperties> = {
  root:        { display:"flex", height:"100vh", background:"#0d0f14", color:"#e2e8f0", fontFamily:"'Segoe UI',system-ui,sans-serif", overflow:"hidden" },
  sidebar:     { width:220, background:"#0a0c10", borderRight:"1px solid #1e2438", display:"flex", flexDirection:"column", padding:"20px 0", flexShrink:0 },
  sidebarLogo: { fontSize:18, fontWeight:700, color:"#6c8ef7", padding:"0 20px 24px", borderBottom:"1px solid #1e2438", marginBottom:12 },
  nav:         { display:"flex", flexDirection:"column", gap:4, padding:"0 12px" },
  navItem:     { padding:"10px 12px", borderRadius:8, fontSize:13, color:"#8896b3", cursor:"pointer" },
  navItemActive:{ background:"#1a1f2e", color:"#c8d3f0" },
  main:        { flex:1, display:"flex", flexDirection:"column", overflow:"hidden" },
  header:      { padding:"16px 24px", borderBottom:"1px solid #1e2438", display:"flex", justifyContent:"space-between", alignItems:"center", background:"#0d0f14", flexShrink:0 },
  headerTitle: { fontSize:15, fontWeight:600, color:"#f0f4ff" },
  headerSub:   { fontSize:12, color:"#4b5980" },
  messages:    { flex:1, overflowY:"auto", padding:24, display:"flex", flexDirection:"column", gap:16 },
  empty:       { margin:"auto", textAlign:"center", color:"#4b5980", paddingBottom:80 },
  bubble:      { maxWidth:720, padding:"12px 16px", borderRadius:12, lineHeight:1.6 },
  bubbleUser:  { alignSelf:"flex-end", background:"#1a2040", border:"1px solid #2a3458", borderBottomRightRadius:3 },
  bubbleAssist:{ alignSelf:"flex-start", background:"#13172080", border:"1px solid #1e2438", borderBottomLeftRadius:3 },
  bubbleRole:  { fontSize:11, color:"#6c8ef7", fontWeight:600, marginBottom:6, textTransform:"uppercase", letterSpacing:0.5 },
  bubbleText:  { fontSize:14, color:"#c8d3f0", whiteSpace:"pre-wrap" },
  inputRow:    { padding:"16px 24px", borderTop:"1px solid #1e2438", display:"flex", gap:10, alignItems:"flex-end", background:"#0d0f14" },
  input:       { flex:1, background:"#13172080", border:"1px solid #2a3050", borderRadius:10, padding:"12px 16px", color:"#e2e8f0", fontSize:14, lineHeight:1.5, maxHeight:160, overflowY:"auto" },
  sendBtn:     { width:40, height:40, borderRadius:10, background:"#6c8ef7", color:"#fff", border:"none", fontSize:18, cursor:"pointer", display:"flex", alignItems:"center", justifyContent:"center", flexShrink:0 },
  card:        { background:"#13172080", border:"1px solid #1e2438", borderRadius:14, padding:"18px 20px" },
  cardTitle:   { fontSize:14, fontWeight:600, color:"#c8d3f0" },
  muted:       { fontSize:13, color:"#6b7a99" },
  emptyState:  { textAlign:"center", padding:"60px 20px", color:"#4b5980" },
  textInput:   { width:"100%", background:"#0d0f14", border:"1px solid #2a3050", borderRadius:8, padding:"10px 14px", color:"#e2e8f0", fontSize:13 },
  btnPrimary:  { background:"#6c8ef7", color:"#fff", border:"none", borderRadius:8, padding:"8px 18px", fontSize:13, fontWeight:600, cursor:"pointer" },
  btnSecondary:{ background:"#1a1f2e", color:"#8896b3", border:"1px solid #2a3050", borderRadius:8, padding:"8px 18px", fontSize:13, cursor:"pointer" },
  code:        { background:"#1a1f2e", padding:"2px 6px", borderRadius:4, fontSize:12, color:"#a78bfa" },
};
