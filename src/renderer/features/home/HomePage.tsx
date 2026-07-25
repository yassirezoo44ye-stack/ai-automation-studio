import { useState, useRef, useEffect, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useAppContext } from "../../contexts/app";
import { useLangContext } from "../../contexts/lang";
import { useToast } from "../../contexts/toast";
import { apiFetch, parseJSON } from "../../utils/api";
import { relTime } from "../../utils/time";
import { motion } from "framer-motion";
import { ProjectAvatar } from "../../components/ui/ProjectAvatar";
import { KpiCard } from "../../shared/ui/gold";
import { S, C, withAlpha } from "../../styles/theme";
import { useAsyncData } from "../../shared/hooks/useAsyncData";
import { ErrorState } from "../../shared/ui/StateViews";
import type { Project } from "../../types";

type HomeTab = "overview" | "projects";
type ActivityEntry = { action: string; details: Record<string, string>; time: string };
type StatsResponse = Record<string, number> & { recent_activity?: ActivityEntry[] };
interface SeriesData { labels: string[]; messages: number[]; builds: number[] }

export function HomePage() {
  const { t } = useTranslation("home");
  const { setPage } = useAppContext();
  const { lang } = useLangContext();
  const toast = useToast();
  const [tab, setTab] = useState<HomeTab>("overview");

  // ── Dashboard state ───────────────────────────────────────────────────────
  const statsQuery = useAsyncData<StatsResponse>(
    () => apiFetch("/api/stats").then(r => parseJSON<StatsResponse>(r, "/api/stats")),
    [],
  );
  const seriesQuery = useAsyncData<SeriesData>(
    () => apiFetch("/api/stats/timeseries?days=14").then(r => parseJSON<SeriesData>(r, "/api/stats/timeseries")),
    [],
  );
  const stats    = statsQuery.data ?? null;
  const activity = statsQuery.data?.recent_activity ?? [];
  const series   = seriesQuery.data ?? null;
  // The backend-online pill is an infra ping, not a data widget — it keeps its
  // own lightweight boolean rather than going through useAsyncData's
  // loading/error/empty model, which doesn't apply to a health check.
  const [backendOk, setBackendOk] = useState<boolean | null>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    apiFetch("/health").then(r => setBackendOk(r.ok)).catch(() => setBackendOk(false));
  }, []);

  // ── Projects state ────────────────────────────────────────────────────────
  const projectsQuery = useAsyncData<Project[]>(
    () => apiFetch("/api/projects").then(r => parseJSON<Project[]>(r, "/api/projects")),
    [],
  );
  const projects    = projectsQuery.data ?? [];
  const loadingProj = projectsQuery.status === "loading";
  const [creating, setCreating]   = useState(false);
  const [newName, setNewName]     = useState("");
  const [newDesc, setNewDesc]     = useState("");
  const [saving, setSaving]       = useState(false);
  const [search, setSearch]       = useState("");
  const [viewMode, setViewMode]   = useState<"grid" | "list">("grid");
  const [sortBy, setSortBy]       = useState<"name" | "date">("date");

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

    ctx.strokeStyle = "#242424"; ctx.lineWidth = 1;
    for (let i = 0; i <= 4; i++) {
      const yy = pad.top + (i / 4) * gH;
      ctx.beginPath(); ctx.moveTo(pad.left, yy); ctx.lineTo(pad.left + gW, yy); ctx.stroke();
      ctx.fillStyle = C.slate; ctx.font = "11px Segoe UI";
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
    drawArea(series.messages, withAlpha("#6E32E0", "33"), "#6E32E0", 2.5);
    drawArea(series.builds,   withAlpha(C.green, "30"), C.green, 2);

    ctx.fillStyle = C.slate; ctx.font = "11px Segoe UI"; ctx.textAlign = "center";
    series.labels.forEach((l, i) => { if (i % 2 === 0) ctx.fillText(l, x(i), H - 8); });
    ctx.textAlign = "start";
  }, [series]);

  const kpis: { label: string; value: number; suffix: string; accent: boolean; icon: ReactNode; displayOverride?: string }[] = [
    { label: t("overview.kpiConversations"), value: stats?.conversations ?? 0, suffix: "", accent: true,  icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg> },
    { label: t("overview.kpiMessages"),      value: stats?.messages ?? 0,      suffix: "", accent: false, icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/></svg> },
    { label: t("overview.kpiBuilds"),        value: stats?.agent_runs ?? 0,    suffix: "", accent: false, icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg> },
    { label: t("overview.kpiProjects"),      value: stats?.projects ?? 0,      suffix: "", accent: false, icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg> },
    {
      label: t("overview.kpiSuccessRate"), value: stats?.success_rate ?? 0, suffix: "%",
      // A "0%" success rate reads as a bad result — but with zero builds run,
      // there's simply no data yet, so show a neutral N/A instead of an
      // alarming-looking zero.
      accent: !!stats?.agent_runs, displayOverride: stats?.agent_runs ? undefined : t("overview.notAvailable"),
      icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12"/></svg>,
    },
  ];

  const actionMeta: Record<string, { label: string; color: string }> = {
    agent_run:            { label: t("activity.chat"),         color: C.blue },
    message_sent:         { label: t("activity.message"),      color: C.sky },
    build:                { label: t("activity.build"),        color: C.green },
    project_created:      { label: t("activity.project"),      color: C.amber },
    conversation_created: { label: t("activity.conversation"), color: C.sky },
  };

  const hour = new Date().getHours();
  const greeting = hour < 12 ? t("greeting.morning") : hour < 17 ? t("greeting.afternoon") : t("greeting.evening");

  const quickActions = [
    { id: "new-chat",    label: t("quickActions.newChat.label"),    sub: t("quickActions.newChat.sub"), page: "ai"  as const, color: C.blue, icon: <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg> },
    { id: "build-app",   label: t("quickActions.buildApp.label"),   sub: t("quickActions.buildApp.sub"),    page: "dev" as const, color: C.green, icon: <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg> },
    { id: "new-agent",   label: t("quickActions.newAgent.label"),   sub: t("quickActions.newAgent.sub"),       page: "ai"  as const, color: C.purple, icon: <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M12 2a5 5 0 0 1 5 5v2a5 5 0 0 1-10 0V7a5 5 0 0 1 5-5z"/><path d="M2 20c0-3 3.5-5 10-5s10 2 10 5"/></svg> },
    { id: "new-project", label: t("quickActions.newProject.label"), sub: t("quickActions.newProject.sub"),       page: "home" as const, color: C.amber, icon: <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg> },
  ];

  // ── Projects helpers ──────────────────────────────────────────────────────
  async function createProject() {
    if (newName.trim().length < 2) return;
    setSaving(true);
    try {
      const r = await apiFetch("/api/projects", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: newName.trim(), description: newDesc.trim() || null }),
      });
      if (!r.ok) throw new Error();
      setNewName(""); setNewDesc(""); setCreating(false); projectsQuery.refetch(); toast(t("toast.created"));
    } catch { toast(t("toast.createFailed"), "err"); }
    finally { setSaving(false); }
  }

  async function deleteProject(id: string, name: string) {
    if (!confirm(t("projects.deleteConfirm", { name }))) return;
    try {
      const r = await apiFetch(`/api/projects/${id}`, { method: "DELETE" });
      if (!r.ok) throw new Error();
      toast(t("toast.deleted", { name }));
    } catch { toast(t("toast.deleteFailed"), "err"); }
    finally { projectsQuery.refetch(); }
  }

  const filteredProjects = projects
    .filter(p => !search || p.name.toLowerCase().includes(search.toLowerCase()) || p.description?.toLowerCase().includes(search.toLowerCase()))
    .sort((a, b) => sortBy === "name" ? a.name.localeCompare(b.name) : new Date(b.created_at).getTime() - new Date(a.created_at).getTime());

  // ── Tab bar ───────────────────────────────────────────────────────────────
  const tabs: [HomeTab, string][] = [["overview", t("header.tabOverview")], ["projects", t("header.tabProjects")]];

  return (
    <>
      <header style={S.header}>
        <span style={S.headerTitle}>{t("header.title")}</span>
        <div style={{ display: "flex", gap: 4, background: "var(--bg-card)", borderRadius: 12, padding: 4 }}>
          {tabs.map(([id, label]) => (
            <button key={id} onClick={() => setTab(id)} style={{
              padding: "7px 18px", borderRadius: 9, border: "none", cursor: "pointer",
              fontSize: 13, fontWeight: 500, transition: "all .18s",
              background: tab === id ? "linear-gradient(135deg,var(--accent),var(--teal))" : "transparent",
              color: tab === id ? "#fff" : "var(--t4)",
              boxShadow: tab === id ? "0 2px 12px rgba(110,50,224,.35)" : "none",
            }}>{label}</button>
          ))}
        </div>
        {tab === "projects" && (
          <button onClick={() => setCreating(c => !c)} style={S.btnPrimary}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
            {t("header.newProject")}
          </button>
        )}
      </header>

      {/* ── Overview tab ─────────────────────────────────────────────────── */}
      {tab === "overview" && (
        <div style={{ flex: 1, overflowY: "auto", padding: 24, display: "flex", flexDirection: "column", gap: 20 }}>
          {/* Welcome */}
          <div className="welcome-header">
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16, flexWrap: "wrap" }}>
              <div>
                <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: "0.08em", color: "var(--ta)", textTransform: "uppercase", marginBottom: 6 }}>{t("welcome.platformLabel")}</div>
                <h1 style={{ fontSize: 22, fontWeight: 700, color: "var(--t1)", letterSpacing: "-0.5px", margin: 0 }}>{greeting} 👋</h1>
                <p style={{ fontSize: 13, color: "var(--t4)", marginTop: 6, maxWidth: 400 }}>
                  {stats ? t("welcome.withData", { conversations: stats.conversations ?? 0, projects: stats.projects ?? 0 })
                    : t("welcome.noData")}
                </p>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 6, padding: "6px 12px", borderRadius: "var(--r-full)", background: backendOk === true ? "var(--green-dim)" : backendOk === false ? "var(--red-dim)" : "var(--bg-card)", border: `1px solid ${backendOk === true ? "rgba(22,163,74,0.25)" : backendOk === false ? "rgba(220,38,38,0.25)" : "var(--b1)"}` }}>
                <div className={`health-dot ${backendOk === true ? "ok" : backendOk === false ? "err" : "warn"} ${backendOk === null ? "pulse" : ""}`} />
                <span style={{ fontSize: 11, fontWeight: 600, color: backendOk === true ? "var(--green)" : backendOk === false ? "var(--red)" : "var(--t4)" }}>
                  {backendOk === true ? t("welcome.backendOnline") : backendOk === false ? t("welcome.backendOffline") : t("welcome.checking")}
                </span>
              </div>
            </div>
          </div>

          {/* Quick actions */}
          <div>
            <div className="section-label" style={{ marginBottom: 10 }}>{t("quickActions.label")}</div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(200px,1fr))", gap: 12 }}>
              {quickActions.map(qa => (
                <button key={qa.id} className="quick-action" onClick={() => { if (qa.id === "new-project") { setTab("projects"); setCreating(true); } else { setPage(qa.page); } }} style={{ textAlign: "start" }}>
                  <div style={{ width: 40, height: 40, borderRadius: 11, background: qa.color + "18", border: `1px solid ${qa.color}30`, display: "flex", alignItems: "center", justifyContent: "center", color: qa.color }}>{qa.icon}</div>
                  <div>
                    <div style={{ fontSize: 13, fontWeight: 600, color: "var(--t1)" }}>{qa.label}</div>
                    <div style={{ fontSize: 12, color: "var(--t4)", marginTop: 2 }}>{qa.sub}</div>
                  </div>
                </button>
              ))}
            </div>
          </div>

          {/* KPI cards — animated count-up */}
          <div>
            <div className="section-label" style={{ marginBottom: 10 }}>{t("overview.label")}</div>
            {statsQuery.status === "error" ? (
              <ErrorState compact message={statsQuery.error ?? t("overview.statsError")} suggestedFix={statsQuery.suggestedFix} onRetry={statsQuery.refetch} />
            ) : stats ? (
              <motion.div
                style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(190px,1fr))", gap: 12 }}
                initial="hidden" animate="show"
                variants={{ show: { transition: { staggerChildren: 0.05 } } }}
              >
                {kpis.map(k => (
                  <motion.div key={k.label} variants={{ hidden: { opacity: 0, y: 10 }, show: { opacity: 1, y: 0 } }}>
                    <KpiCard label={k.label} value={k.value} suffix={k.suffix} icon={k.icon} accent={k.accent} displayOverride={k.displayOverride} />
                  </motion.div>
                ))}
              </motion.div>
            ) : (
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(190px,1fr))", gap: 12 }}>
                {[1,2,3,4,5].map(i => <div key={i} className="skeleton" style={{ height: 92, borderRadius: 18 }} />)}
              </div>
            )}
          </div>

          {/* Chart + activity */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 340px", gap: 16 }}>
            <div style={S.card}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
                <span style={S.cardTitle}>{t("chart.title")}</span>
                <div style={{ display: "flex", gap: 14, fontSize: 12 }}>
                  <span style={{ display: "flex", alignItems: "center", gap: 6, color: "var(--accent-2)" }}><span style={{ width: 10, height: 3, borderRadius: 2, background: "var(--accent-2)", display: "inline-block" }} />{t("chart.messages")}</span>
                  <span style={{ display: "flex", alignItems: "center", gap: 6, color: C.green }}><span style={{ width: 10, height: 3, borderRadius: 2, background: C.green, display: "inline-block" }} />{t("chart.builds")}</span>
                </div>
              </div>
              {seriesQuery.status === "error" ? (
                <ErrorState compact message={seriesQuery.error ?? t("chart.error")} suggestedFix={seriesQuery.suggestedFix} onRetry={seriesQuery.refetch} />
              ) : series ? <canvas ref={canvasRef} width={800} height={180} style={{ width: "100%", height: 180 }} />
                : <div className="skeleton" style={{ height: 180 }} />}
            </div>
            <div style={S.card}>
              <div style={{ ...S.cardTitle, marginBottom: 14 }}>{t("activity.title")}</div>
              {activity.length === 0 && (
                <div className="empty-state" style={{ padding: "32px 0" }}>
                  <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M12 20V10"/><path d="M18 20V4"/><path d="M6 20v-6"/></svg>
                  <p>{t("activity.empty")}</p>
                </div>
              )}
              <div style={{ display: "flex", flexDirection: "column" }}>
                {activity.slice(0, 8).map((a, i) => {
                  const meta = actionMeta[a.action] ?? { label: a.action, color: "var(--t4)" };
                  return (
                    <div key={i} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "9px 0", borderBottom: i < Math.min(activity.length, 8) - 1 ? "1px solid var(--b1)" : "none" }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
                        <span className="badge" style={{ background: meta.color + "1e", color: meta.color, border: `1px solid ${meta.color}30`, flexShrink: 0 }}>{meta.label}</span>
                        {a.details.prompt_preview && <span style={{ fontSize: 12, color: "var(--t4)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>"{a.details.prompt_preview}"</span>}
                      </div>
                      <span style={{ fontSize: 11, color: "var(--t5)", flexShrink: 0, marginInlineStart: 8 }}>{relTime(a.time, lang)}</span>
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
                <div className="section-label">{t("recentProjects.title")}</div>
                <button onClick={() => setTab("projects")} style={{ background: "none", border: "none", color: "var(--ta)", fontSize: 12, cursor: "pointer", fontWeight: 500 }}>{t("recentProjects.viewAll")}</button>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(220px,1fr))", gap: 12 }}>
                {projects.slice(0, 4).map(p => (
                  <div key={p.id} role="button" tabIndex={0}
                    style={{ ...S.card, padding: "16px 18px", display: "flex", alignItems: "center", gap: 12, cursor: "pointer" }}
                    onClick={() => setTab("projects")}
                    onKeyDown={e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setTab("projects"); } }}>
                    <ProjectAvatar name={p.name} size={36} />
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontSize: 13, fontWeight: 600, color: "var(--t1)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{p.name}</div>
                      <div style={{ fontSize: 11, color: "var(--t5)", marginTop: 2 }}>{relTime(p.created_at, lang)}</div>
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
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ position: "absolute", insetInlineStart: 10, color: "var(--t4)", pointerEvents: "none" }}><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
              <input value={search} onChange={e => setSearch(e.target.value)} placeholder={t("toolbar.searchPlaceholder")} style={{ ...S.textInput, paddingInlineStart: 32, fontSize: 12 }} />
            </div>
            <select value={sortBy} onChange={e => setSortBy(e.target.value as "date" | "name")} style={{ ...S.projectSelect, width: "auto", fontSize: 12, padding: "8px 10px" }}>
              <option value="date">{t("toolbar.sortLatest")}</option>
              <option value="name">{t("toolbar.sortAZ")}</option>
            </select>
            <div className="seg-ctrl" style={{ width: "auto" }}>
              <button className={`seg-btn${viewMode === "grid" ? " active" : ""}`} onClick={() => setViewMode("grid")} title={t("toolbar.gridView")} style={{ padding: "7px 10px" }}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>
              </button>
              <button className={`seg-btn${viewMode === "list" ? " active" : ""}`} onClick={() => setViewMode("list")} title={t("toolbar.listView")} style={{ padding: "7px 10px" }}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg>
              </button>
            </div>
          </div>

          {/* New project form */}
          {creating && (
            <div style={{ ...S.card, marginBottom: 20, animation: "slideUp .2s ease" }}>
              <div style={{ ...S.cardTitle, marginBottom: 14 }}>{t("newProjectForm.title")}</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                <input value={newName} onChange={e => setNewName(e.target.value)} placeholder={t("newProjectForm.namePlaceholder")} style={S.textInput} onKeyDown={e => e.key === "Enter" && createProject()} autoFocus />
                {newName.length > 0 && newName.trim().length < 2 && (
                  <span style={{ fontSize: 11, color: "var(--red)", marginTop: -4 }}>{t("newProjectForm.nameHint")}</span>
                )}
                <textarea value={newDesc} onChange={e => setNewDesc(e.target.value)} placeholder={t("newProjectForm.descPlaceholder")} style={{ ...S.textInput, resize: "vertical", minHeight: 70, fontFamily: "inherit" }} />
                <div style={{ display: "flex", gap: 8 }}>
                  <button onClick={createProject} disabled={saving || newName.trim().length < 2} style={S.btnPrimary}>{saving ? t("newProjectForm.creating") : t("newProjectForm.create")}</button>
                  <button onClick={() => { setCreating(false); setNewName(""); setNewDesc(""); }} style={S.btnSecondary}>{t("common:actions.cancel")}</button>
                </div>
              </div>
            </div>
          )}

          {/* Projects grid/list */}
          {loadingProj ? (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(240px,1fr))", gap: 12 }}>
              {[1,2,3].map(i => <div key={i} className="skeleton" style={{ height: 100, borderRadius: 12 }} />)}
            </div>
          ) : projectsQuery.status === "error" ? (
            <ErrorState message={projectsQuery.error ?? t("projects.loadError")} suggestedFix={projectsQuery.suggestedFix} onRetry={projectsQuery.refetch} />
          ) : filteredProjects.length === 0 ? (
            <div className="empty-state">
              <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="var(--ta)" strokeWidth="1.2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
              <h3>{t("projects.emptyTitle")}</h3>
              <p>{t("projects.emptyDesc")}</p>
              <button onClick={() => setCreating(true)} style={S.btnPrimary}>{t("header.newProject")}</button>
            </div>
          ) : viewMode === "grid" ? (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(240px,1fr))", gap: 12 }}>
              {filteredProjects.map(p => (
                <div key={p.id} style={{ ...S.card, padding: "20px", position: "relative", cursor: "default" }}>
                  <div style={{ display: "flex", alignItems: "flex-start", gap: 12, marginBottom: 10 }}>
                    <ProjectAvatar name={p.name} size={42} />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: 14, fontWeight: 600, color: "var(--t1)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{p.name}</div>
                      <div style={{ fontSize: 11, color: "var(--t5)", marginTop: 2 }}>{relTime(p.created_at, lang)}</div>
                    </div>
                    <button onClick={() => deleteProject(p.id, p.name)} title={t("projects.delete")} style={{ background: "none", border: "none", color: "var(--t5)", cursor: "pointer", padding: 4, borderRadius: 6, flexShrink: 0 }}
                      onMouseEnter={e => (e.currentTarget.style.color = C.redSoft)} onMouseLeave={e => (e.currentTarget.style.color = "var(--t5)")}>
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
                  <span style={{ fontSize: 11, color: "var(--t5)", flexShrink: 0 }}>{relTime(p.created_at, lang)}</span>
                  <button onClick={() => deleteProject(p.id, p.name)} title={t("projects.delete")} style={{ background: "none", border: "none", color: "var(--t5)", cursor: "pointer", padding: 4, borderRadius: 6 }}
                    onMouseEnter={e => (e.currentTarget.style.color = C.redSoft)} onMouseLeave={e => (e.currentTarget.style.color = "var(--t5)")}>
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
