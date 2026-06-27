import { useState, useRef, useEffect, useCallback } from "react";
import ReactMarkdown from "react-markdown";

type Page = "chat" | "build" | "projects" | "settings";
type Message  = { id: string; role: "user" | "assistant"; content: string };
type Conv     = { id: string; title: string; updated_at: string };
type Project  = { id: string; name: string; description: string; status: string; created_at: string };

const API = "http://127.0.0.1:8000";

// ─── Chat Page ────────────────────────────────────────────────────────────────
function ChatPage() {
  const [projects, setProjects]       = useState<Project[]>([]);
  const [projectId, setProjectId]     = useState("demo");
  const [convs, setConvs]             = useState<Conv[]>([]);
  const [activeConv, setActiveConv]   = useState<string | null>(null);
  const [messages, setMessages]       = useState<Message[]>([]);
  const [prompt, setPrompt]           = useState("");
  const [streaming, setStreaming]     = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const abortRef  = useRef<(() => void) | null>(null);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages]);

  const loadProjects = useCallback(async () => {
    try { const r = await fetch(`${API}/api/projects`); setProjects(await r.json()); } catch {}
  }, []);

  const loadConvs = useCallback(async () => {
    try {
      const r = await fetch(`${API}/api/conversations?project_id=${projectId}`);
      setConvs(await r.json());
    } catch {}
  }, [projectId]);

  const loadMessages = useCallback(async (cid: string) => {
    try {
      const r = await fetch(`${API}/api/conversations/${cid}/messages`);
      const msgs: { id: string; role: string; content: string }[] = await r.json();
      setMessages(msgs.map(m => ({ id: m.id, role: m.role as "user"|"assistant", content: m.content })));
    } catch {}
  }, []);

  useEffect(() => { loadProjects(); }, [loadProjects]);
  useEffect(() => { loadConvs(); setActiveConv(null); setMessages([]); }, [loadConvs]);

  function newChat() { setActiveConv(null); setMessages([]); }

  async function selectConv(cid: string) {
    setActiveConv(cid);
    await loadMessages(cid);
  }

  async function deleteConv(e: React.MouseEvent, cid: string) {
    e.stopPropagation();
    await fetch(`${API}/api/conversations/${cid}`, { method: "DELETE" });
    if (activeConv === cid) { setActiveConv(null); setMessages([]); }
    loadConvs();
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

    let closed = false;
    const es = new EventSource(`${API}/run/stream?` + new URLSearchParams(), );

    // Use fetch for SSE so we can POST
    const controller = new AbortController();
    abortRef.current = () => controller.abort();

    try {
      const res = await fetch(`${API}/run/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project_id: projectId, prompt: text, conversation_id: activeConv }),
        signal: controller.signal,
      });

      if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);

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
          if (!line.startsWith("data: ")) continue;
          const payload = JSON.parse(line.slice(6));

          if (payload.type === "conv_id" && !activeConv) {
            setActiveConv(payload.conv_id);
            loadConvs();
          } else if (payload.type === "delta") {
            setMessages(prev => prev.map(m =>
              m.id === assistantId ? { ...m, content: m.content + payload.text } : m
            ));
          } else if (payload.type === "error") {
            setMessages(prev => prev.map(m =>
              m.id === assistantId ? { ...m, content: `⚠️ ${payload.message}` } : m
            ));
            closed = true; break;
          } else if (payload.type === "done") {
            loadConvs(); closed = true;
          }
        }
        if (closed) break;
      }
    } catch (err: unknown) {
      if ((err as Error).name !== "AbortError") {
        const msg = (err as Error).message ?? String(err);
        const offline = msg.includes("fetch") || msg.includes("Failed to fetch");
        setMessages(prev => prev.map(m =>
          m.id === assistantId
            ? { ...m, content: offline ? "⚠️ Backend offline — run `python main.py` on port 8000." : `⚠️ ${msg}` }
            : m
        ));
      }
    } finally {
      setStreaming(false);
      abortRef.current = null;
    }
  }

  const activeProject = projects.find(p => p.id === projectId);

  return (
    <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>
      {/* Chat history sidebar */}
      <div style={S.chatSidebar}>
        <div style={{ padding: "12px 12px 8px" }}>
          <select
            value={projectId}
            onChange={e => setProjectId(e.target.value)}
            style={S.projectSelect}
          >
            <option value="demo">Demo Project</option>
            {projects.filter(p => p.id !== "00000000-0000-0000-0000-000000000001").map(p => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
        </div>
        <div style={{ padding: "0 8px 8px" }}>
          <button onClick={newChat} style={S.newChatBtn}>+ New Chat</button>
        </div>
        <div style={{ flex: 1, overflowY: "auto" }}>
          {convs.length === 0 && (
            <div style={{ padding: "12px 16px", fontSize: 12, color: "#4b5980" }}>No conversations yet</div>
          )}
          {convs.map(c => (
            <div
              key={c.id}
              onClick={() => selectConv(c.id)}
              style={{ ...S.convItem, ...(c.id === activeConv ? S.convItemActive : {}) }}
            >
              <div style={S.convTitle}>{c.title}</div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 2 }}>
                <span style={S.convTime}>{relTime(c.updated_at)}</span>
                <span
                  onClick={e => deleteConv(e, c.id)}
                  style={{ color: "#4b5980", fontSize: 12, cursor: "pointer", opacity: 0.6 }}
                >✕</span>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Main chat */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        <header style={S.header}>
          <span style={S.headerTitle}>Chat with Claude</span>
          <span style={S.headerSub}>
            claude-sonnet-4-6 · {activeProject?.name ?? "Demo Project"}
          </span>
        </header>

        <div style={S.messages}>
          {messages.length === 0 && (
            <div style={S.empty}>
              <div style={{ fontSize: 40, color: "#6c8ef7", marginBottom: 12 }}>◈</div>
              <div style={{ fontSize: 20, fontWeight: 700, color: "#c8d3f0", marginBottom: 8 }}>AI Automation Studio</div>
              <div style={{ fontSize: 14 }}>Start a new conversation or pick one from the sidebar.</div>
            </div>
          )}
          {messages.map(m => (
            <div key={m.id} style={{ ...S.bubble, ...(m.role === "user" ? S.bubbleUser : S.bubbleAssist) }}>
              <div style={S.bubbleRole}>{m.role === "user" ? "You" : "Claude"}</div>
              {m.role === "assistant" && m.content === "" ? (
                <div className="typing"><span /><span /><span /></div>
              ) : m.role === "assistant" ? (
                <div style={S.bubbleText} className="md-body">
                  <ReactMarkdown>{m.content}</ReactMarkdown>
                </div>
              ) : (
                <div style={S.bubbleText}>{m.content}</div>
              )}
            </div>
          ))}
          <div ref={bottomRef} />
        </div>

        <div style={S.inputRow}>
          <textarea
            value={prompt}
            onChange={e => setPrompt(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); } }}
            placeholder="Message Claude… (Enter to send)"
            style={S.input} rows={1}
          />
          {streaming
            ? <button onClick={() => abortRef.current?.()} style={{ ...S.sendBtn, background: "#f87171" }}>■</button>
            : <button onClick={sendMessage} disabled={!prompt.trim()} style={S.sendBtn}>↑</button>
          }
        </div>
      </div>
    </div>
  );
}

// ─── Build Page ───────────────────────────────────────────────────────────────
type BuildFile = { path: string; content: string };
type BuildState = "idle" | "building" | "done" | "error";

function BuildPage() {
  const [projects, setProjects]       = useState<Project[]>([]);
  const [projectId, setProjectId]     = useState("demo");
  const [prompt, setPrompt]           = useState("");
  const [state, setState]             = useState<BuildState>("idle");
  const [status, setStatus]           = useState("");
  const [files, setFiles]             = useState<BuildFile[]>([]);
  const [activeFile, setActiveFile]   = useState<BuildFile | null>(null);
  const [runCmd, setRunCmd]           = useState("");
  const [runOutput, setRunOutput]     = useState("");
  const [running, setRunning]         = useState(false);
  const [description, setDescription] = useState("");
  const [existingFiles, setExistingFiles] = useState<{path:string;size:number}[]>([]);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    fetch(`${API}/api/projects`).then(r => r.json()).then(setProjects).catch(() => {});
  }, []);

  useEffect(() => {
    loadExisting();
  }, [projectId]);

  async function loadExisting() {
    try {
      const r = await fetch(`${API}/api/projects/${projectId}/files`);
      const d = await r.json();
      setExistingFiles(d.files ?? []);
    } catch {}
  }

  async function loadFile(path: string) {
    try {
      const r = await fetch(`${API}/api/projects/${projectId}/files/${path}`);
      const d = await r.json();
      setActiveFile({ path: d.path, content: d.content });
    } catch {}
  }

  async function clearWorkspace() {
    if (!confirm("Clear all files in this workspace?")) return;
    await fetch(`${API}/api/projects/${projectId}/files`, { method: "DELETE" });
    setFiles([]); setExistingFiles([]); setActiveFile(null); setRunOutput(""); setRunCmd("");
  }

  async function build() {
    if (!prompt.trim() || state === "building") return;
    setState("building"); setStatus("🤖 Connecting to Claude…");
    setFiles([]); setActiveFile(null); setRunOutput(""); setDescription("");

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const res = await fetch(`${API}/api/build/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project_id: projectId, prompt }),
        signal: controller.signal,
      });
      if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);

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
          if (!line.startsWith("data: ")) continue;
          const ev = JSON.parse(line.slice(6));
          if (ev.type === "status") {
            setStatus(ev.message);
          } else if (ev.type === "file") {
            setFiles(prev => [...prev, { path: ev.path, content: ev.content }]);
            setStatus(`📝 Writing ${ev.path}…`);
          } else if (ev.type === "done") {
            setDescription(ev.description);
            setRunCmd(ev.run_command || "");
            setState("done");
            setStatus(`✅ Built ${ev.files.length} files`);
            loadExisting();
          } else if (ev.type === "error") {
            setState("error");
            setStatus(`❌ ${ev.message}`);
          }
        }
      }
    } catch (err: unknown) {
      if ((err as Error).name !== "AbortError") {
        setState("error");
        setStatus(`❌ ${(err as Error).message}`);
      } else {
        setState("idle"); setStatus("");
      }
    }
  }

  async function runCode() {
    if (!runCmd.trim()) return;
    setRunning(true); setRunOutput("Running…\n");
    try {
      const r = await fetch(`${API}/api/projects/${projectId}/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ command: runCmd }),
      });
      const d = await r.json();
      if (!r.ok) { setRunOutput(`❌ ${d.detail}`); return; }
      const out = [
        d.stdout ? `$ ${d.command}\n${d.stdout}` : `$ ${d.command}`,
        d.stderr ? `\n--- stderr ---\n${d.stderr}` : "",
        `\n[exit code: ${d.returncode}]`,
      ].join("");
      setRunOutput(out);
    } catch (e) {
      setRunOutput(`Error: ${e}`);
    } finally {
      setRunning(false);
    }
  }

  const allFiles = state === "done" ? files : existingFiles.map(f => ({ path: f.path, content: "" }));

  return (
    <>
      <header style={S.header}>
        <span style={S.headerTitle}>🔨 Build Programs</span>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <select value={projectId} onChange={e => setProjectId(e.target.value)} style={{ ...S.projectSelect, width: "auto" }}>
            <option value="demo">Demo Project</option>
            {projects.filter(p => p.id !== "00000000-0000-0000-0000-000000000001").map(p => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
          {(allFiles.length > 0) && (
            <button onClick={clearWorkspace} style={{ ...S.btnSecondary, fontSize: 12, padding: "6px 12px" }}>
              🗑 Clear
            </button>
          )}
        </div>
      </header>

      <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>
        {/* Left: prompt + file tree */}
        <div style={{ width: 280, borderRight: "1px solid #1e2438", display: "flex", flexDirection: "column", background: "#0a0c10" }}>
          {/* Prompt */}
          <div style={{ padding: 14, borderBottom: "1px solid #1e2438" }}>
            <textarea
              value={prompt}
              onChange={e => setPrompt(e.target.value)}
              onKeyDown={e => { if (e.key === "Enter" && e.ctrlKey) build(); }}
              placeholder={"Describe what to build…\n\nExamples:\n• Calculator in Python\n• Todo list web app\n• Snake game in HTML\n• REST API with FastAPI"}
              style={{ ...S.input, height: 140, fontSize: 12, width: "100%" }}
            />
            <button
              onClick={state === "building" ? () => abortRef.current?.abort() : build}
              disabled={!prompt.trim() && state !== "building"}
              style={{ ...S.btnPrimary, width: "100%", marginTop: 8, fontSize: 13 }}
            >
              {state === "building" ? "⏹ Stop" : "🔨 Build"}
            </button>
            {status && (
              <div style={{ marginTop: 8, fontSize: 11, color: state === "error" ? "#f87171" : "#34d399", lineHeight: 1.4 }}>
                {status}
              </div>
            )}
            {description && (
              <div style={{ marginTop: 8, fontSize: 12, color: "#8896b3", lineHeight: 1.5, background: "#13172080", borderRadius: 6, padding: 8 }}>
                {description}
              </div>
            )}
          </div>

          {/* File tree */}
          <div style={{ flex: 1, overflowY: "auto", padding: "8px 0" }}>
            {allFiles.length === 0 && (
              <div style={{ padding: "16px", fontSize: 12, color: "#4b5980" }}>
                No files yet — describe a program and click Build.
              </div>
            )}
            {allFiles.map(f => (
              <div
                key={f.path}
                onClick={() => state === "done" ? setActiveFile(f) : loadFile(f.path)}
                style={{
                  padding: "7px 16px", cursor: "pointer", fontSize: 12,
                  color: activeFile?.path === f.path ? "#c8d3f0" : "#8896b3",
                  background: activeFile?.path === f.path ? "#1a1f2e" : "transparent",
                  borderLeft: activeFile?.path === f.path ? "2px solid #6c8ef7" : "2px solid transparent",
                  display: "flex", alignItems: "center", gap: 6,
                }}
              >
                <span>{fileIcon(f.path)}</span>
                <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{f.path}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Right: code viewer + terminal */}
        <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
          {/* Code viewer */}
          <div style={{ flex: 1, overflow: "auto", background: "#080a0f" }}>
            {activeFile ? (
              <div>
                <div style={{ padding: "10px 20px", borderBottom: "1px solid #1e2438", fontSize: 12, color: "#6b7a99", display: "flex", justifyContent: "space-between" }}>
                  <span>{fileIcon(activeFile.path)} {activeFile.path}</span>
                  <span>{activeFile.content.split("\n").length} lines</span>
                </div>
                <pre style={{ margin: 0, padding: "16px 20px", fontSize: 13, color: "#c8d3f0", lineHeight: 1.6, overflowX: "auto", fontFamily: "'Consolas','Courier New',monospace" }}>
                  <code>{activeFile.content}</code>
                </pre>
              </div>
            ) : (
              <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%", color: "#4b5980", flexDirection: "column", gap: 10 }}>
                <span style={{ fontSize: 36 }}>🔨</span>
                <span style={{ fontSize: 14 }}>Select a file to view its code</span>
              </div>
            )}
          </div>

          {/* Terminal */}
          <div style={{ height: 200, borderTop: "1px solid #1e2438", display: "flex", flexDirection: "column", background: "#040506" }}>
            <div style={{ padding: "6px 12px", borderBottom: "1px solid #1e2438", display: "flex", gap: 8, alignItems: "center" }}>
              <span style={{ fontSize: 11, color: "#6b7a99", flexShrink: 0 }}>▶ Run:</span>
              <input
                value={runCmd}
                onChange={e => setRunCmd(e.target.value)}
                onKeyDown={e => { if (e.key === "Enter") runCode(); }}
                placeholder="python main.py"
                style={{ flex: 1, background: "none", border: "none", color: "#c8d3f0", fontSize: 12, fontFamily: "monospace" }}
              />
              <button onClick={runCode} disabled={running || !runCmd.trim()} style={{ ...S.btnPrimary, padding: "4px 12px", fontSize: 12 }}>
                {running ? "Running…" : "Run ▶"}
              </button>
            </div>
            <pre style={{ flex: 1, margin: 0, padding: "10px 14px", overflowY: "auto", fontSize: 12, color: "#34d399", fontFamily: "'Consolas','Courier New',monospace", lineHeight: 1.5 }}>
              {runOutput || <span style={{ color: "#4b5980" }}>Output will appear here…</span>}
            </pre>
          </div>
        </div>
      </div>
    </>
  );
}

function fileIcon(path: string) {
  const ext = path.split(".").pop()?.toLowerCase();
  const map: Record<string, string> = {
    py: "🐍", js: "🟨", ts: "🔷", tsx: "⚛️", jsx: "⚛️",
    html: "🌐", css: "🎨", json: "📋", md: "📄",
    txt: "📝", sh: "⚙️", bat: "⚙️", yaml: "📋", yml: "📋",
    sql: "🗄️", env: "🔑", gitignore: "🔧", dockerfile: "🐳",
    requirements: "📦", toml: "📋",
  };
  return map[ext ?? ""] ?? "📄";
}

// ─── Projects Page ────────────────────────────────────────────────────────────
function ProjectsPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading]   = useState(true);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName]   = useState("");
  const [newDesc, setNewDesc]   = useState("");
  const [saving, setSaving]     = useState(false);
  const [error, setError]       = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try { const r = await fetch(`${API}/api/projects`); setProjects(await r.json()); }
    catch { setError("Could not load projects."); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  async function create() {
    if (!newName.trim()) return;
    setSaving(true);
    try {
      const r = await fetch(`${API}/api/projects`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: newName.trim(), description: newDesc.trim() || null }),
      });
      if (!r.ok) throw new Error();
      setNewName(""); setNewDesc(""); setCreating(false); load();
    } catch { alert("Failed to create project."); }
    finally { setSaving(false); }
  }

  async function del(id: string, name: string) {
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
          <div style={{ ...S.card, marginBottom: 16 }}>
            <div style={S.cardTitle}>New Project</div>
            <input value={newName} onChange={e => setNewName(e.target.value)}
              placeholder="Project name *" style={{ ...S.textInput, marginTop: 12 }} autoFocus />
            <input value={newDesc} onChange={e => setNewDesc(e.target.value)}
              placeholder="Description (optional)" style={{ ...S.textInput, marginTop: 10 }} />
            <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
              <button onClick={create} disabled={saving || !newName.trim()} style={S.btnPrimary}>
                {saving ? "Saving…" : "Create"}
              </button>
              <button onClick={() => { setCreating(false); setNewName(""); setNewDesc(""); }} style={S.btnSecondary}>
                Cancel
              </button>
            </div>
          </div>
        )}
        {error && <div style={{ color: "#f87171", fontSize: 13, marginBottom: 12 }}>{error}</div>}
        {loading && <div style={S.muted}>Loading…</div>}
        {!loading && projects.length === 0 && !creating && (
          <div style={S.emptyState}>
            <div style={{ fontSize: 32, marginBottom: 10 }}>📁</div>
            <div style={{ color: "#c8d3f0", fontWeight: 600, marginBottom: 6 }}>No projects yet</div>
            <div style={S.muted}>Click "New Project" to get started.</div>
          </div>
        )}
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {projects.map(p => (
            <div key={p.id} style={S.card}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                <div style={{ flex: 1 }}>
                  <div style={S.cardTitle}>{p.name}</div>
                  {p.description && <div style={{ ...S.muted, marginTop: 4 }}>{p.description}</div>}
                  <div style={{ ...S.muted, marginTop: 8, fontSize: 11 }}>
                    Created {new Date(p.created_at).toLocaleDateString()} ·{" "}
                    <span style={{ color: p.status === "active" ? "#34d399" : "#f87171", fontWeight: 600 }}>
                      {p.status}
                    </span>
                  </div>
                </div>
                {p.id !== "00000000-0000-0000-0000-000000000001" && (
                  <button onClick={() => del(p.id, p.name)}
                    style={{ background: "none", border: "none", color: "#4b5980", cursor: "pointer", fontSize: 16, padding: 4 }}>
                    🗑
                  </button>
                )}
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
  const [stats,  setStats]  = useState<Record<string, number> | null>(null);
  const [saved,  setSaved]  = useState(false);

  useEffect(() => {
    fetch(`${API}/health`).then(r => r.json()).then(setHealth).catch(() => null);
    fetch(`${API}/api/stats`).then(r => r.json()).then(setStats).catch(() => null);
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
              <Row label="API URL"    value="http://127.0.0.1:8000" />
            </div>
          ) : (
            <div style={{ color: "#f87171", marginTop: 8, fontSize: 13 }}>
              ⚠️ Backend offline — run <code style={S.code}>python main.py</code>
            </div>
          )}
        </div>

        {stats && (
          <div style={S.card}>
            <div style={S.cardTitle}>Usage Statistics</div>
            <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 8 }}>
              <Row label="Projects"       value={String(stats.projects)} />
              <Row label="Conversations"  value={String(stats.conversations)} />
              <Row label="Messages"       value={String(stats.messages)} />
              <Row label="Agent Runs"     value={String(stats.agent_runs)} />
              <Row label="Success Rate"   value={`${stats.success_rate}%`} />
            </div>
          </div>
        )}

        <div style={S.card}>
          <div style={S.cardTitle}>Model</div>
          <select style={{ ...S.textInput, marginTop: 10, cursor: "pointer" }}>
            <option>claude-sonnet-4-6 (default)</option>
            <option>claude-opus-4-8 (most capable)</option>
            <option>claude-haiku-4-5-20251001 (fastest)</option>
          </select>
        </div>

        <div style={S.card}>
          <div style={S.cardTitle}>API Key</div>
          <div style={{ ...S.muted, margin: "6px 0 10px" }}>Get a key at console.anthropic.com</div>
          <input type="password" defaultValue="sk-ant-api03-••••••••••" style={S.textInput} />
          <div style={{ marginTop: 10 }}>
            <button onClick={() => { setSaved(true); setTimeout(() => setSaved(false), 2000); }} style={S.btnPrimary}>
              {saved ? "✓ Saved" : "Save"}
            </button>
          </div>
          <div style={{ ...S.muted, marginTop: 8, fontSize: 11 }}>
            To apply a new key, update ANTHROPIC_API_KEY in .env and restart the backend.
          </div>
        </div>

        <div style={S.card}>
          <div style={S.cardTitle}>About</div>
          <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 6 }}>
            <Row label="App"      value="AI Automation Studio" />
            <Row label="Version"  value="2.0.0" />
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
  if (s < 3600) return `${Math.floor(s/60)}m ago`;
  if (s < 86400) return `${Math.floor(s/3600)}h ago`;
  return new Date(iso).toLocaleDateString();
}

// ─── Root ─────────────────────────────────────────────────────────────────────
export default function App() {
  const [page, setPage] = useState<Page>("chat");

  return (
    <div style={S.root}>
      <aside style={S.sidebar}>
        <div style={S.sidebarLogo}>◈ AI Studio</div>
        <nav style={S.nav}>
          {([ ["chat","💬","Chat"], ["build","🔨","Build"], ["projects","📁","Projects"], ["settings","⚙️","Settings"] ] as const).map(([id,icon,label]) => (
            <div key={id} onClick={() => setPage(id)}
              style={{ ...S.navItem, ...(page === id ? S.navItemActive : {}) }}>
              {icon} {label}
            </div>
          ))}
          <a href="/dashboard.html" target="_blank"
            style={{ ...S.navItem, textDecoration: "none" }}>
            📊 Dashboard ↗
          </a>
        </nav>
      </aside>

      <main style={S.main}>
        {page === "chat"     && <ChatPage />}
        {page === "build"    && <BuildPage />}
        {page === "projects" && <ProjectsPage />}
        {page === "settings" && <SettingsPage />}
      </main>

      <style>{`
        @keyframes bounce{0%,80%,100%{transform:translateY(0);opacity:.4}40%{transform:translateY(-6px);opacity:1}}
        .typing span{display:inline-block;width:6px;height:6px;background:#6c8ef7;border-radius:50%;margin:0 2px;animation:bounce 1.2s infinite}
        .typing span:nth-child(2){animation-delay:.2s}.typing span:nth-child(3){animation-delay:.4s}
        textarea{resize:none} *:focus{outline:none} *{box-sizing:border-box} body{margin:0}
        ::-webkit-scrollbar{width:6px}::-webkit-scrollbar-track{background:#0d0f14}::-webkit-scrollbar-thumb{background:#2a3050;border-radius:3px}
        input::placeholder,textarea::placeholder{color:#4b5980}
        .md-body p{margin:0 0 8px}.md-body p:last-child{margin:0}
        .md-body pre{background:#0d0f14;border:1px solid #2a3050;border-radius:8px;padding:12px;overflow-x:auto;margin:8px 0}
        .md-body code{background:#1a1f2e;padding:2px 5px;border-radius:4px;font-size:12px;color:#a78bfa}
        .md-body pre code{background:none;padding:0;color:#c8d3f0;font-size:13px}
        .md-body ul,.md-body ol{padding-left:20px;margin:4px 0}
        .md-body li{margin:2px 0}
        .md-body h1,.md-body h2,.md-body h3{color:#f0f4ff;margin:12px 0 6px}
        .md-body strong{color:#f0f4ff}
        .md-body a{color:#6c8ef7}
        .md-body blockquote{border-left:3px solid #6c8ef7;padding-left:12px;margin:8px 0;color:#8896b3}
        .md-body table{border-collapse:collapse;width:100%;margin:8px 0}
        .md-body th,.md-body td{border:1px solid #2a3050;padding:6px 10px;font-size:13px}
        .md-body th{background:#1a1f2e;color:#c8d3f0}
      `}</style>
    </div>
  );
}

// ─── Styles ───────────────────────────────────────────────────────────────────
const S: Record<string, React.CSSProperties> = {
  root:          { display:"flex", height:"100vh", background:"#0d0f14", color:"#e2e8f0", fontFamily:"'Segoe UI',system-ui,sans-serif", overflow:"hidden" },
  sidebar:       { width:200, background:"#0a0c10", borderRight:"1px solid #1e2438", display:"flex", flexDirection:"column", padding:"20px 0", flexShrink:0 },
  sidebarLogo:   { fontSize:17, fontWeight:700, color:"#6c8ef7", padding:"0 20px 20px", borderBottom:"1px solid #1e2438", marginBottom:12 },
  nav:           { display:"flex", flexDirection:"column", gap:2, padding:"0 10px" },
  navItem:       { padding:"9px 12px", borderRadius:8, fontSize:13, color:"#8896b3", cursor:"pointer" },
  navItemActive: { background:"#1a1f2e", color:"#c8d3f0" },
  main:          { flex:1, display:"flex", flexDirection:"column", overflow:"hidden" },
  chatSidebar:   { width:220, borderRight:"1px solid #1e2438", display:"flex", flexDirection:"column", background:"#0a0c10", flexShrink:0 },
  projectSelect: { width:"100%", background:"#0d0f14", border:"1px solid #2a3050", borderRadius:8, padding:"7px 10px", color:"#c8d3f0", fontSize:12, cursor:"pointer" },
  newChatBtn:    { width:"100%", background:"#1a1f2e", border:"1px solid #2a3050", borderRadius:8, padding:"8px", color:"#8896b3", fontSize:12, cursor:"pointer", textAlign:"left" },
  convItem:      { padding:"10px 12px", cursor:"pointer", borderBottom:"1px solid #0d0f14" },
  convItemActive:{ background:"#1a1f2e" },
  convTitle:     { fontSize:12, color:"#c8d3f0", overflow:"hidden", textOverflow:"ellipsis", whiteSpace:"nowrap" },
  convTime:      { fontSize:10, color:"#4b5980" },
  header:        { padding:"14px 24px", borderBottom:"1px solid #1e2438", display:"flex", justifyContent:"space-between", alignItems:"center", flexShrink:0 },
  headerTitle:   { fontSize:15, fontWeight:600, color:"#f0f4ff" },
  headerSub:     { fontSize:12, color:"#4b5980" },
  messages:      { flex:1, overflowY:"auto", padding:24, display:"flex", flexDirection:"column", gap:16 },
  empty:         { margin:"auto", textAlign:"center", color:"#4b5980", paddingBottom:80 },
  bubble:        { maxWidth:740, padding:"12px 16px", borderRadius:12, lineHeight:1.6 },
  bubbleUser:    { alignSelf:"flex-end", background:"#1a2040", border:"1px solid #2a3458", borderBottomRightRadius:3 },
  bubbleAssist:  { alignSelf:"flex-start", background:"#131720cc", border:"1px solid #1e2438", borderBottomLeftRadius:3 },
  bubbleRole:    { fontSize:11, color:"#6c8ef7", fontWeight:600, marginBottom:6, textTransform:"uppercase", letterSpacing:0.5 },
  bubbleText:    { fontSize:14, color:"#c8d3f0" },
  inputRow:      { padding:"14px 20px", borderTop:"1px solid #1e2438", display:"flex", gap:10, alignItems:"flex-end" },
  input:         { flex:1, background:"#13172080", border:"1px solid #2a3050", borderRadius:10, padding:"11px 14px", color:"#e2e8f0", fontSize:14, lineHeight:1.5, maxHeight:140, overflowY:"auto" },
  sendBtn:       { width:40, height:40, borderRadius:10, background:"#6c8ef7", color:"#fff", border:"none", fontSize:18, cursor:"pointer", display:"flex", alignItems:"center", justifyContent:"center", flexShrink:0 },
  card:          { background:"#13172080", border:"1px solid #1e2438", borderRadius:14, padding:"18px 20px" },
  cardTitle:     { fontSize:14, fontWeight:600, color:"#c8d3f0" },
  muted:         { fontSize:13, color:"#6b7a99" },
  emptyState:    { textAlign:"center", padding:"60px 20px", color:"#4b5980" },
  textInput:     { width:"100%", background:"#0d0f14", border:"1px solid #2a3050", borderRadius:8, padding:"10px 14px", color:"#e2e8f0", fontSize:13 },
  btnPrimary:    { background:"#6c8ef7", color:"#fff", border:"none", borderRadius:8, padding:"8px 18px", fontSize:13, fontWeight:600, cursor:"pointer" },
  btnSecondary:  { background:"#1a1f2e", color:"#8896b3", border:"1px solid #2a3050", borderRadius:8, padding:"8px 18px", fontSize:13, cursor:"pointer" },
  code:          { background:"#1a1f2e", padding:"2px 6px", borderRadius:4, fontSize:12, color:"#a78bfa" },
};
