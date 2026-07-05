import { useState, useRef, useEffect, useCallback } from "react";
import { useAppContext } from "../../contexts/AppContext";
import { useToast } from "../../contexts/ToastContext";
import { apiFetch, parseJSON } from "../../utils/api";
import { relTime } from "../../utils/time";
import { ProjectAvatar } from "../../components/ui/ProjectAvatar";
import { S } from "../../styles/theme";
import type { Project } from "../../types";

type HomeTab = "overview" | "projects";

// ── Stat card data type ───────────────────────────────────────────────────────
type StatCardDef = { label: string; value: string | number; color: string; icon: React.JSX.Element };

export function HomePage() {
  const { setPage } = useAppContext();
  const toast = useToast();
  const [tab, setTab] = useState<HomeTab>("overview");

  // ── Dashboard state ───────────────────────────────────────────────────────
  const [stats, setStats]     = useState<Record<string, number> | null>(null);
  const [series, setSeries]   = useState<{ labels: string[]; messages: number[]; builds: number[] } | null>(null);
  const [activity, setActivity] = useState<{ action: string; details: Record<string, string>; time: string }[]>([]);
  const [backendOk, setBackendOk] = useState<boolean | null>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  // ── Projects state ────────────────────────────────────────────────────────
  const [projects, setProjects]   = useState<Project[]>([]);
  const [loadingProj, setLoadingProj] = useState(true);
  const [creating, setCreating]   = useState(false);
  const [newName, setNewName]     = useState("");
  const [newDesc, setNewDesc]     = useState("");
  const [saving, setSaving]       = useState(false);
  const [search, setSearch]       = useState("");
  const [viewMode, setViewMode]   = useState<"grid" | "list">("grid");
  const [sortBy, setSortBy]       = useState<"name" | "date">("date");

  useEffect(() => {
    apiFetch("/api/stats").then(r => parseJSON<Record<string, number> & { recent_activity?: { action: string; details: Record<string, string>; time: string }[] }>(r, "/api/stats")).then(d => { setStats(d); setActivity(d.recent_activity ?? []); }).catch(() => {});
    apiFetch("/api/stats/timeseries?days=14").then(r => parseJSON<{ labels: string[]; messages: number[]; builds: number[] }>(r, "/api/stats/timeseries")).then(setSeries).catch(() => {});
    apiFetch("/health").then(r => setBackendOk(r.ok)).catch(() => setBackendOk(false));
  }, []);

  const loadProjects = useCallback(async () => {
    setLoadingProj(true);
    try { const r = await apiFetch("/api/projects"); setProjects(await parseJSON<Project[]>(r, "/api/projects")); }
    catch { toast("Could not load projects", "err"); }
    finally { setLoadingProj(false); }
  }, []);
  useEffect(() => { loadProjects(); }, [loadProjects]);

  // ── Canvas chart ──────────────────────────────────────────────────────────
  useEffect(() => {
    if (!series || !canvasRef.current) return;
    const canvas = canvasRef.current;
    const ctx = canvas.getContext("2d")!;
    const W = canvas.width, H = canvas.height;
    const pad = { top: 20, right: 20, bottom: 36, left: 40 };
    const gW = W - pad.left - pad.right, gH = H - pad.top - pad.bottom;
    ctx.clearRect(0, 0, W, H);
    const allVals = [...series.messages, ...series.builds];
    const maxVal  = Math.max(...allVals, 1);
    const n = series.labels.length;
    const x = (i: number) => n <= 1 ? pad.left + gW / 2 : pad.left + (i / (n - 1)) * gW;
    const y = (v: number) => pad.top + gH - (v / maxVal) * gH;

    ctx.strokeStyle = "#1e2438"; ctx.lineWidth = 1;
    for (let i = 0; i <= 4; i++) {
      const yy = pad.top + (i / 4) * gH;
      ctx.beginPath(); ctx.moveTo(pad.left, yy); ctx.lineTo(pad.left + gW, yy); ctx.stroke();
      ctx.fillStyle = "#4b5980"; ctx.font = "11px Segoe UI";
      ctx.fillText(String(Math.round(maxVal * (1 - i / 4))), 4, yy + 4);
    }

    const drawArea = (vals: number[], fillColor: string, lineColor: string, lineW: number) => {
      const grad = ctx.createLinearGradient(0, pad.top, 0, pad.top + gH);
      grad.addColorStop(0, fillColor); grad.addColorStop(1, fillColor.replace(/[\d.]+\)$/, "0)"));
      ctx.beginPath();
      ctx.moveTo(x(0), y(vals[0]));
      vals.forEach((v, i) => ctx.lineTo(x(i), y(v)));
      ctx.lineTo(x(n - 1), pad.top + gH); ctx.lineTo(x(0), pad.top + gH);
      ctx.closePath(); ctx.fillStyle = grad; ctx.fill();
      ctx.beginPath(); ctx.strokeStyle = lineColor; ctx.lineWidth = lineW;
      vals.forEach((v, i) => i === 0 ? ctx.moveTo(x(i), y(v)) : ctx.lineTo(x(i), y(v)));
      ctx.stroke();
    };
    drawArea(series.messages, "#6c8ef740", "#6c8ef7", 2.5);
    drawArea(series.builds,   "#34d39930", "#34d399", 2);

    ctx.fillStyle = "#4b5980"; ctx.font = "11px Segoe UI"; ctx.textAlign = "center";
    series.labels.forEach((l, i) => { if (i % 2 === 0) ctx.fillText(l, x(i), H - 8); });
    ctx.textAlign = "start";
  }, [series]);

  const statCards: StatCardDef[] = [
    { label: "Conversations", value: stats?.conversations ?? "—", color: "#6c8ef7", icon: <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg> },
    { label: "Messages",      value: stats?.messages      ?? "—", color: "#a78bfa", icon: <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/></svg> },
    { label: "Builds",        value: stats?.agent_runs    ?? "—", color: "#34d399", icon: <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg> },
    { label: "Projects",      value: stats?.projects      ?? "—", color: "#f59e0b", icon: <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg> },
    { label: "Success Rate",  value: stats ? `${stats.success_rate}%` : "—", color: "#10b981", icon: <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12"/></svg> },
    { label: "Agent Runs",    value: stats?.agent_runs    ?? "—", color: "#f87171", icon: <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 8 12 12 14 14"/></svg> },
  ];

  const actionMeta: Record<string, { label: string; color: string }> = {
    agent_run:       { label: "Chat",    color: "#6c8ef7" },
    build:           { label: "Build",   color: "#34d399" },
    project_created: { label: "Project", color: "#f59e0b" },
  };

  const hour = new Date().getHours();
  const greeting = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";

  const quickActions = [
    { label: "New Chat",    sub: "Start an AI conversation", page: "ai"  as const, color: "#6c8ef7", icon: <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg> },
    { label: "Build App",   sub: "Generate code with AI",    page: "dev" as const, color: "#34d399", icon: <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg> },
    { label: "New Agent",   sub: "Create an AI agent",       page: "ai"  as const, color: "#a78bfa", icon: <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M12 2a5 5 0 0 1 5 5v2a5 5 0 0 1-10 0V7a5 5 0 0 1 5-5z"/><path d="M2 20c0-3 3.5-5 10-5s10 2 10 5"/></svg> },
    { label: "New Project", sub: "Organize your work",       page: "home" as const, color: "#f59e0b", icon: <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg> },
  ];

  // ── Projects helpers ──────────────────────────────────────────────────────
  async function createProject() {
    if (!newName.trim()) return;
    setSaving(true);
    try {
      const r = await apiFetch("/api/projects", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: newName.trim(), description: newDesc.trim() || null }),
      });
      if (!r.ok) throw new Error();
      setNewName(""); setNewDesc(""); setCreating(false); loadProjects(); toast("Project created");
    } catch { toast("Failed to create", "err"); }
    finally { setSaving(false); }
  }

  async function deleteProject(id: string, name: string) {
    if (!confirm(`Delete "${name}"? This cannot be undone.`)) return;
    try {
      const r = await apiFetch(`/api/projects/${id}`, { method: "DELETE" });
      if (!r.ok) throw new Error();
      toast(`Deleted "${name}"`);
    } catch { toast("Failed to delete project", "err"); }
    finally { loadProjects(); }
  }

  const filteredProjects = projects
    .filter(p => !search || p.name.toLowerCase().includes(search.toLowerCase()) || p.description?.toLowerCase().includes(search.toLowerCase()))
    .sort((a, b) => sortBy === "name" ? a.name.localeCompare(b.name) : new Date(b.created_at).getTime() - new Date(a.created_at).getTime());

  // ── Tab bar ───────────────────────────────────────────────────────────────
  const tabs: [HomeTab, string][] = [["overview", "Overview"], ["projects", "Projects"]];

  return (
    <>
      <header style={S.header}>
        <span style={S.headerTitle}>Home</span>
        <div style={{ display: "flex", gap: 4, background: "rgba(255,255,255,.04)", borderRadius: 12, padding: 4 }}>
          {tabs.map(([id, label]) => (
            <button key={id} onClick={() => setTab(id)} style={{
              padding: "7px 18px", borderRadius: 9, border: "none", cursor: "pointer",
              fontSize: 13, fontWeight: 500, transition: "all .18s",
              background: tab === id ? "linear-gradient(135deg,#8b5cf6,#6366f1)" : "transparent",
              color: tab === id ? "#fff" : "rgba(148,163,184,.6)",
              boxShadow: tab === id ? "0 2px 12px rgba(139,92,246,.35)" : "none",
            }}>{label}</button>
          ))}
        </div>
        {tab === "projects" && (
          <button onClick={() => setCreating(c => !c)} style={S.btnPrimary}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
            New Project
          </button>
        )}
      </header>

      {/* ── Overview tab ─────────────────────────────────────────────────── */}
      {tab === "overview" && (
        <div style={{ flex: 1, overflowY: "auto", padding: 24, display: "flex", flexDirection: "column", gap: 20 }}>
          {/* Welcome */}
          <div className="welcome-header" style={{ direction: "ltr" }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16, flexWrap: "wrap" }}>
              <div>
                <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: "0.08em", color: "var(--ta)", textTransform: "uppercase", marginBottom: 6 }}>AXON PLATFORM</div>
                <h1 style={{ fontSize: 22, fontWeight: 700, color: "var(--t1)", letterSpacing: "-0.5px", margin: 0 }}>{greeting} 👋</h1>
                <p style={{ fontSize: 13, color: "var(--t4)", marginTop: 6, maxWidth: 400 }}>
                  {stats ? `You have ${stats.conversations ?? 0} conversations and ${stats.projects ?? 0} projects. Keep building.`
                    : "Your AI-powered automation studio is ready."}
                </p>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 6, padding: "6px 12px", borderRadius: "var(--r-full)", background: backendOk === true ? "var(--green-dim)" : backendOk === false ? "var(--red-dim)" : "rgba(255,255,255,0.04)", border: `1px solid ${backendOk === true ? "rgba(52,211,153,0.25)" : backendOk === false ? "rgba(248,113,113,0.25)" : "var(--b1)"}` }}>
                <div className={`health-dot ${backendOk === true ? "ok" : backendOk === false ? "err" : "warn"} ${backendOk === null ? "pulse" : ""}`} />
                <span style={{ fontSize: 11, fontWeight: 600, color: backendOk === true ? "var(--green)" : backendOk === false ? "var(--red)" : "var(--t4)" }}>
                  {backendOk === true ? "Backend online" : backendOk === false ? "Backend offline" : "Checking…"}
                </span>
              </div>
            </div>
          </div>

          {/* Quick actions */}
          <div>
            <div className="section-label" style={{ marginBottom: 10 }}>Quick Actions</div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(200px,1fr))", gap: 12 }}>
              {quickActions.map(qa => (
                <button key={qa.label} className="quick-action" onClick={() => { if (qa.label === "New Project") { setTab("projects"); setCreating(true); } else { setPage(qa.page); } }} style={{ textAlign: "left" }}>
                  <div style={{ width: 40, height: 40, borderRadius: 11, background: qa.color + "18", border: `1px solid ${qa.color}30`, display: "flex", alignItems: "center", justifyContent: "center", color: qa.color }}>{qa.icon}</div>
                  <div>
                    <div style={{ fontSize: 13, fontWeight: 600, color: "var(--t1)" }}>{qa.label}</div>
                    <div style={{ fontSize: 12, color: "var(--t4)", marginTop: 2 }}>{qa.sub}</div>
                  </div>
                </button>
              ))}
            </div>
          </div>

          {/* Stat cards */}
          <div>
            <div className="section-label" style={{ marginBottom: 10 }}>Overview</div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(200px,1fr))", gap: 12 }}>
              {statCards.map(c => (
                <div key={c.label} className="stat-card" style={{ ...S.card, display: "flex", alignItems: "center", gap: 14, padding: "18px 20px" }}>
                  <div style={{ width: 46, height: 46, borderRadius: 13, background: c.color + "1e", border: `1px solid ${c.color}30`, display: "flex", alignItems: "center", justifyContent: "center", color: c.color, flexShrink: 0 }}>{c.icon}</div>
                  <div style={{ minWidth: 0 }}>
                    {stats ? <div style={{ fontSize: 24, fontWeight: 700, color: c.color, lineHeight: 1, letterSpacing: "-0.5px" }}>{String(c.value)}</div>
                      : <div className="skeleton" style={{ width: 48, height: 24, marginBottom: 4 }} />}
                    <div style={{ fontSize: 12, color: "rgba(148,163,184,0.55)", marginTop: 4, whiteSpace: "nowrap" }}>{c.label}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Chart + activity */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 340px", gap: 16 }}>
            <div style={S.card}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
                <span style={S.cardTitle}>Activity — last 14 days</span>
                <div style={{ display: "flex", gap: 14, fontSize: 12 }}>
                  <span style={{ display: "flex", alignItems: "center", gap: 6, color: "#6c8ef7" }}><span style={{ width: 10, height: 3, borderRadius: 2, background: "#6c8ef7", display: "inline-block" }} />Messages</span>
                  <span style={{ display: "flex", alignItems: "center", gap: 6, color: "#34d399" }}><span style={{ width: 10, height: 3, borderRadius: 2, background: "#34d399", display: "inline-block" }} />Builds</span>
                </div>
              </div>
              {series ? <canvas ref={canvasRef} width={800} height={180} style={{ width: "100%", height: 180 }} />
                : <div className="skeleton" style={{ height: 180 }} />}
            </div>
            <div style={S.card}>
              <div style={{ ...S.cardTitle, marginBottom: 14 }}>Recent Activity</div>
              {activity.length === 0 && (
                <div className="empty-state" style={{ padding: "32px 0", direction: "ltr" }}>
                  <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M12 20V10"/><path d="M18 20V4"/><path d="M6 20v-6"/></svg>
                  <p>No activity yet — start a chat or build a project.</p>
                </div>
              )}
              <div style={{ display: "flex", flexDirection: "column" }}>
                {activity.slice(0, 8).map((a, i) => {
                  const meta = actionMeta[a.action] ?? { label: a.action, color: "var(--t4)" };
                  return (
                    <div key={i} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "9px 0", borderBottom: i < Math.min(activity.length, 8) - 1 ? "1px solid rgba(255,255,255,0.05)" : "none" }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
                        <span className="badge" style={{ background: meta.color + "1e", color: meta.color, border: `1px solid ${meta.color}30`, flexShrink: 0 }}>{meta.label}</span>
                        {a.details.prompt_preview && <span style={{ fontSize: 12, color: "var(--t4)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>"{a.details.prompt_preview}"</span>}
                      </div>
                      <span style={{ fontSize: 11, color: "var(--t5)", flexShrink: 0, marginLeft: 8 }}>{relTime(a.time)}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>

          {/* Recent projects strip */}
          {projects.length > 0 && (
            <div>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
                <div className="section-label">Recent Projects</div>
                <button onClick={() => setTab("projects")} style={{ background: "none", border: "none", color: "var(--ta)", fontSize: 12, cursor: "pointer", fontWeight: 500 }}>View all →</button>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(220px,1fr))", gap: 12 }}>
                {projects.slice(0, 4).map(p => (
                  <div key={p.id} style={{ ...S.card, padding: "16px 18px", display: "flex", alignItems: "center", gap: 12, cursor: "pointer" }} onClick={() => setTab("projects")}>
                    <ProjectAvatar name={p.name} size={36} />
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontSize: 13, fontWeight: 600, color: "var(--t1)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{p.name}</div>
                      <div style={{ fontSize: 11, color: "var(--t5)", marginTop: 2 }}>{relTime(p.created_at)}</div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── Projects tab ─────────────────────────────────────────────────── */}
      {tab === "projects" && (
        <div style={{ flex: 1, overflowY: "auto", padding: 24 }}>
          {/* Toolbar */}
          <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 20, flexWrap: "wrap" }}>
            <div style={{ position: "relative", display: "flex", alignItems: "center", flex: 1, maxWidth: 260 }}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ position: "absolute", left: 10, color: "var(--t4)", pointerEvents: "none" }}><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
              <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search projects…" style={{ ...S.textInput, paddingLeft: 32, fontSize: 12 }} />
            </div>
            <select value={sortBy} onChange={e => setSortBy(e.target.value as any)} style={{ ...S.projectSelect, width: "auto", fontSize: 12, padding: "8px 10px" }}>
              <option value="date">Latest</option>
              <option value="name">A → Z</option>
            </select>
            <div className="seg-ctrl" style={{ width: "auto" }}>
              <button className={`seg-btn${viewMode === "grid" ? " active" : ""}`} onClick={() => setViewMode("grid")} title="Grid" style={{ padding: "7px 10px" }}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>
              </button>
              <button className={`seg-btn${viewMode === "list" ? " active" : ""}`} onClick={() => setViewMode("list")} title="List" style={{ padding: "7px 10px" }}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg>
              </button>
            </div>
          </div>

          {/* New project form */}
          {creating && (
            <div style={{ ...S.card, marginBottom: 20, animation: "slideUp .2s ease" }}>
              <div style={{ ...S.cardTitle, marginBottom: 14 }}>New Project</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                <input value={newName} onChange={e => setNewName(e.target.value)} placeholder="Project name *" style={S.textInput} onKeyDown={e => e.key === "Enter" && createProject()} autoFocus />
                <textarea value={newDesc} onChange={e => setNewDesc(e.target.value)} placeholder="Description (optional)" style={{ ...S.textInput, resize: "vertical", minHeight: 70, fontFamily: "inherit" }} />
                <div style={{ display: "flex", gap: 8 }}>
                  <button onClick={createProject} disabled={saving || !newName.trim()} style={S.btnPrimary}>{saving ? "Creating…" : "Create Project"}</button>
                  <button onClick={() => { setCreating(false); setNewName(""); setNewDesc(""); }} style={S.btnSecondary}>Cancel</button>
                </div>
              </div>
            </div>
          )}

          {/* Projects grid/list */}
          {loadingProj ? (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(240px,1fr))", gap: 12 }}>
              {[1,2,3].map(i => <div key={i} className="skeleton" style={{ height: 100, borderRadius: 12 }} />)}
            </div>
          ) : filteredProjects.length === 0 ? (
            <div className="empty-state" style={{ direction: "ltr" }}>
              <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="var(--ta)" strokeWidth="1.2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
              <h3>No projects yet</h3>
              <p>Create your first project to get started.</p>
              <button onClick={() => setCreating(true)} style={S.btnPrimary}>New Project</button>
            </div>
          ) : viewMode === "grid" ? (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(240px,1fr))", gap: 12 }}>
              {filteredProjects.map(p => (
                <div key={p.id} style={{ ...S.card, padding: "20px", position: "relative", cursor: "default" }}>
                  <div style={{ display: "flex", alignItems: "flex-start", gap: 12, marginBottom: 10 }}>
                    <ProjectAvatar name={p.name} size={42} />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: 14, fontWeight: 600, color: "var(--t1)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{p.name}</div>
                      <div style={{ fontSize: 11, color: "var(--t5)", marginTop: 2 }}>{relTime(p.created_at)}</div>
                    </div>
                    <button onClick={() => deleteProject(p.id, p.name)} title="Delete" style={{ background: "none", border: "none", color: "var(--t5)", cursor: "pointer", padding: 4, borderRadius: 6, flexShrink: 0 }}
                      onMouseEnter={e => (e.currentTarget.style.color = "#f87171")} onMouseLeave={e => (e.currentTarget.style.color = "var(--t5)")}>
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/></svg>
                    </button>
                  </div>
                  {p.description && <p style={{ fontSize: 12, color: "var(--t4)", margin: 0, overflow: "hidden", display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical" }}>{p.description}</p>}
                </div>
              ))}
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {filteredProjects.map(p => (
                <div key={p.id} style={{ ...S.card, padding: "14px 18px", display: "flex", alignItems: "center", gap: 12 }}>
                  <ProjectAvatar name={p.name} size={32} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 13, fontWeight: 600, color: "var(--t1)" }}>{p.name}</div>
                    {p.description && <div style={{ fontSize: 12, color: "var(--t4)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{p.description}</div>}
                  </div>
                  <span style={{ fontSize: 11, color: "var(--t5)", flexShrink: 0 }}>{relTime(p.created_at)}</span>
                  <button onClick={() => deleteProject(p.id, p.name)} title="Delete" style={{ background: "none", border: "none", color: "var(--t5)", cursor: "pointer", padding: 4, borderRadius: 6 }}
                    onMouseEnter={e => (e.currentTarget.style.color = "#f87171")} onMouseLeave={e => (e.currentTarget.style.color = "var(--t5)")}>
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/></svg>
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </>
  );
}
