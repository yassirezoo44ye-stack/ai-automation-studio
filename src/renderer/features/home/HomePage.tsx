/**
 * Flow Dashboard — redesigned to Hercules-grade enterprise quality.
 * Layout:
 *   AI Builder hero → KPI stats → Apps grid → Activity + Quick Nav
 */
import { useState, useRef, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { useAppContext } from "../../contexts/app";
import { useLangContext } from "../../contexts/lang";
import { useToast } from "../../contexts/toast";
import { apiFetch, parseJSON } from "../../utils/api";
import { relTime } from "../../utils/time";
import { motion, AnimatePresence } from "framer-motion";
import { ProjectAvatar } from "../../components/ui/ProjectAvatar";
import { useAsyncData } from "../../shared/hooks/useAsyncData";
import { ErrorState } from "../../shared/ui/StateViews";
import type { Project } from "../../types";

type ActivityEntry = { action: string; details: Record<string, string>; time: string };
type StatsResponse = Record<string, number> & { recent_activity?: ActivityEntry[] };

type AgentLive = { status: "running" | "idle" | "error" | string };
type AgentEntry = {
  name: string;
  description: string;
  live: AgentLive;
  stats: { run_count: number; fail_count: number };
};
type AgentsResponse = { count: number; agents: AgentEntry[] };

type WorkflowRun = { id: string; name: string; status: string; started_at?: string };
type WorkflowsResponse = { runs: WorkflowRun[] };

const STATUS_COLOR: Record<string, string> = {
  active: "var(--green)", building: "var(--blue)", error: "var(--red)", draft: "var(--t4)",
};

const EXAMPLE_PROMPTS = [
  "Build a CRM for my sales team with contacts, deals, and follow-ups",
  "Create an inventory management system with low-stock alerts",
  "Build an HR onboarding portal with task checklists and document storage",
  "Create a customer support ticketing system with AI triage",
  "Build a project tracker with time logging and team collaboration",
];

const ACTION_META: Record<string, { labelKey: string; color: string; icon: React.ReactNode }> = {
  agent_run:            { labelKey: "activity.actions.agentRun",           color: "var(--accent)", icon: <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3"/></svg> },
  message_sent:         { labelKey: "activity.actions.messageSent",        color: "var(--blue)",   icon: <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg> },
  build:                { labelKey: "activity.actions.build",              color: "var(--green)",  icon: <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg> },
  project_created:      { labelKey: "activity.actions.projectCreated",     color: "var(--yellow)", icon: <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg> },
  conversation_created: { labelKey: "activity.actions.conversationCreated",color: "var(--blue)",   icon: <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg> },
};

/* ── App card ─────────────────────────────────────────────────────── */
function AppCard({ project, onOpen, onDelete }: {
  project: Project;
  onOpen: () => void;
  onDelete: () => void;
}) {
  const { t } = useTranslation("home");
  const { lang } = useLangContext();
  const status = project.status ?? "active";
  const statusColor = STATUS_COLOR[status] ?? "var(--t4)";

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.97 }}
      className="app-card"
      onClick={onOpen}
      role="button"
      tabIndex={0}
      aria-label={`Open ${project.name}`}
      onKeyDown={e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onOpen(); } }}
    >
      {/* Header */}
      <div style={{ display: "flex", alignItems: "flex-start", gap: 12 }}>
        <ProjectAvatar name={project.name} size={40} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: "var(--t1)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", lineHeight: 1.3 }}>
            {project.name}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 5, marginTop: 4 }}>
            <span style={{ width: 5, height: 5, borderRadius: "50%", background: statusColor, flexShrink: 0 }} />
            <span style={{ fontSize: 10, color: statusColor, fontWeight: 600, textTransform: "capitalize", letterSpacing: "0.02em" }}>
              {status}
            </span>
          </div>
        </div>
        <button
          onClick={e => { e.stopPropagation(); onDelete(); }}
          style={{
            background: "none", border: "none", cursor: "pointer", color: "var(--t5)",
            padding: 4, borderRadius: 6, flexShrink: 0, display: "flex",
            transition: "color 0.12s",
          }}
          onMouseEnter={e => (e.currentTarget.style.color = "var(--red)")}
          onMouseLeave={e => (e.currentTarget.style.color = "var(--t5)")}
          title={t("card.deleteTitle")}
          aria-label={`Delete ${project.name}`}
        >
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <polyline points="3 6 5 6 21 6"/>
            <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/>
            <path d="M10 11v6M14 11v6"/>
          </svg>
        </button>
      </div>

      {/* Description */}
      {project.description && (
        <p style={{
          fontSize: 11, color: "var(--t4)", margin: 0, lineHeight: 1.55,
          overflow: "hidden", display: "-webkit-box",
          WebkitLineClamp: 2, WebkitBoxOrient: "vertical",
        }}>
          {project.description}
        </p>
      )}

      {/* Footer */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: "auto", paddingTop: 4 }}>
        <span style={{ fontSize: 10, color: "var(--t5)" }}>
          {t("card.updatedAt", { time: relTime(project.created_at, lang) })}
        </span>
        <button
          onClick={e => { e.stopPropagation(); onOpen(); }}
          style={{
            background: "var(--accent-dim)", border: "1px solid var(--accent-border)",
            borderRadius: 7, padding: "4px 10px", fontSize: 11, fontWeight: 600,
            color: "var(--accent)", cursor: "pointer", transition: "background 0.12s",
          }}
          onMouseEnter={e => { e.currentTarget.style.background = "var(--accent)"; e.currentTarget.style.color = "white"; }}
          onMouseLeave={e => { e.currentTarget.style.background = "var(--accent-dim)"; e.currentTarget.style.color = "var(--accent)"; }}
        >
          {t("card.open")}
        </button>
      </div>
    </motion.div>
  );
}

/* ══════════════════════════════════════════════════════════════════
   HomePage
   ══════════════════════════════════════════════════════════════════ */
export function HomePage() {
  const { t } = useTranslation("home");
  const { setPage } = useAppContext();
  const { lang } = useLangContext();
  const toast = useToast();

  const [prompt, setPrompt]   = useState("");
  const [promptIdx, setPromptIdx] = useState(0);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName]   = useState("");
  const [newDesc, setNewDesc]   = useState("");
  const [saving, setSaving]     = useState(false);
  const [search, setSearch]     = useState("");
  const promptRef = useRef<HTMLTextAreaElement>(null);

  // Cycle placeholder
  useEffect(() => {
    const id = setInterval(() => setPromptIdx(i => (i + 1) % EXAMPLE_PROMPTS.length), 4000);
    return () => clearInterval(id);
  }, []);

  // Stats
  const statsQuery = useAsyncData<StatsResponse>(
    () => apiFetch("/api/stats").then(r => parseJSON<StatsResponse>(r, "/api/stats")),
    [],
  );
  const stats    = statsQuery.data ?? null;
  const activity = statsQuery.data?.recent_activity ?? [];

  // Projects
  const projectsQuery = useAsyncData<Project[]>(
    () => apiFetch("/api/projects").then(r => parseJSON<Project[]>(r, "/api/projects")),
    [],
  );
  const projects    = projectsQuery.data ?? [];
  const loadingProj = projectsQuery.status === "loading";

  // Active Agents — GET /api/agentos/agents
  const agentsQuery = useAsyncData<AgentsResponse>(
    () => apiFetch("/api/agentos/agents").then(r => parseJSON<AgentsResponse>(r, "/api/agentos/agents")),
    [],
  );
  const agents = agentsQuery.data?.agents ?? [];

  // Active Workflow Runs — GET /api/workflows/active
  const workflowsQuery = useAsyncData<WorkflowsResponse>(
    () => apiFetch("/api/workflows/active").then(r => parseJSON<WorkflowsResponse>(r, "/api/workflows/active")),
    [],
  );
  const workflowRuns = workflowsQuery.data?.runs ?? [];

  const filteredProjects = projects
    .filter(p => !search || p.name.toLowerCase().includes(search.toLowerCase()))
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());

  /* ── Build with AI ──────────────────────────────────── */
  function handleBuildApp() {
    if (prompt.trim().length > 3) {
      sessionStorage.setItem("flow_builder_prompt", prompt.trim());
    }
    setPage("app-builder");
  }

  /* ── Project CRUD ───────────────────────────────────── */
  async function createProject() {
    if (newName.trim().length < 2) return;
    setSaving(true);
    try {
      const r = await apiFetch("/api/projects", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: newName.trim(), description: newDesc.trim() || null }),
      });
      if (!r.ok) throw new Error();
      setNewName(""); setNewDesc(""); setCreating(false);
      projectsQuery.refetch();
      toast(t("toast.created"), "ok");
    } catch { toast(t("toast.createFailed"), "err"); }
    finally { setSaving(false); }
  }

  async function deleteProject(id: string, name: string) {
    if (!confirm(t("card.deleteConfirm", { name }))) return;
    try {
      const r = await apiFetch(`/api/projects/${id}`, { method: "DELETE" });
      if (!r.ok) throw new Error();
      toast(t("toast.deleted", { name }), "ok");
    } catch { toast(t("toast.deleteFailed"), "err"); }
    finally { projectsQuery.refetch(); }
  }

  /* ── Quick nav items ─────────────────────────────────── */
  const quickNavItems = [
    { labelKey: "quickNav.agents",       page: "agentos"      as const, color: "#6E32E0", icon: <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M4.22 4.22l2.12 2.12M17.66 17.66l2.12 2.12M2 12h3M19 12h3"/></svg> },
    { labelKey: "quickNav.automations",  page: "automation"   as const, color: "#2563EB", icon: <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><polyline points="9 11 12 14 22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg> },
    { labelKey: "quickNav.runs",         page: "runs"         as const, color: "#0B7A70", icon: <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg> },
    { labelKey: "quickNav.integrations", page: "integrations" as const, color: "#A16207", icon: <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg> },
  ];

  // Template chips from locale
  const ideaChips = t("buildSection.ideas", { returnObjects: true }) as string[];

  /* ── KPI data ────────────────────────────────────────── */
  const kpis = [
    {
      label: t("stats.appsBuilt"),
      value: stats?.projects ?? 0,
      accent: true,
      icon: <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/></svg>,
    },
    {
      label: t("stats.aiConversations"),
      value: stats?.conversations ?? 0,
      accent: false,
      icon: <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>,
    },
    {
      label: t("stats.agentRuns"),
      value: stats?.agent_runs ?? 0,
      accent: false,
      icon: <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>,
    },
    {
      label: t("stats.successRate"),
      value: stats?.agent_runs ? `${stats.success_rate ?? 0}%` : "—",
      accent: false,
      icon: <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><polyline points="20 6 9 17 4 12"/></svg>,
    },
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      {/* ── Sub-header: page title + actions ─────────────────────── */}
      <div style={{
        padding: "0 24px", height: 52, minHeight: 52,
        borderBottom: "1px solid var(--b1)",
        display: "flex", alignItems: "center", justifyContent: "space-between",
        background: "var(--bg-surface)", flexShrink: 0,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <div>
            <div style={{ fontSize: 15, fontWeight: 700, color: "var(--t1)", lineHeight: 1.2 }}>
              {t("header.title")}
            </div>
          </div>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <button
            onClick={() => setCreating(true)}
            style={{
              display: "flex", alignItems: "center", gap: 6,
              padding: "6px 13px", borderRadius: 8,
              border: "1px solid var(--b2)",
              background: "transparent", color: "var(--t2)",
              fontSize: 12, fontWeight: 500, cursor: "pointer",
              transition: "border-color 0.12s, background 0.12s",
            }}
            onMouseEnter={e => (e.currentTarget.style.borderColor = "var(--ba)")}
            onMouseLeave={e => (e.currentTarget.style.borderColor = "var(--b2)")}
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>
            </svg>
            {t("header.newApp")}
          </button>
          <button
            onClick={handleBuildApp}
            style={{
              display: "flex", alignItems: "center", gap: 6,
              padding: "6px 14px", borderRadius: 8, border: "none",
              background: "linear-gradient(135deg, var(--accent) 0%, var(--teal) 100%)",
              color: "white", fontSize: 12, fontWeight: 600, cursor: "pointer",
              boxShadow: "0 2px 10px rgba(110,50,224,0.30)",
            }}
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
              <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/>
            </svg>
            {t("header.buildWithAI")}
          </button>
        </div>
      </div>

      {/* ── Scrollable content ────────────────────────────────────── */}
      <div style={{ flex: 1, overflowY: "auto", padding: "24px 24px 40px" }}>

        {/* ── AI Builder Hero ──────────────────────────────────── */}
        <div className="dash-hero" style={{ marginBottom: 20 }}>
          <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: "0.10em", color: "var(--accent)", textTransform: "uppercase", marginBottom: 8 }}>
            {t("buildSection.label")}
          </div>
          <h1 style={{ fontSize: 20, fontWeight: 700, color: "var(--t1)", letterSpacing: "-0.4px", margin: "0 0 14px" }}>
            {t("buildSection.title")}
          </h1>

          {/* Prompt textarea */}
          <div style={{ position: "relative" }}>
            <textarea
              ref={promptRef}
              value={prompt}
              onChange={e => setPrompt(e.target.value)}
              onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleBuildApp(); } }}
              placeholder={EXAMPLE_PROMPTS[promptIdx]}
              rows={2}
              style={{
                width: "100%", padding: "13px 120px 13px 16px",
                fontSize: 13, lineHeight: 1.6,
                background: "var(--bg-base)",
                border: "1px solid var(--b1)",
                borderRadius: 10, color: "var(--t1)",
                resize: "none", outline: "none",
                fontFamily: "inherit",
                boxSizing: "border-box",
                transition: "border-color 0.15s, box-shadow 0.15s",
              }}
              onFocus={e => {
                e.target.style.borderColor = "var(--accent)";
                e.target.style.boxShadow = "0 0 0 3px var(--accent-dim)";
              }}
              onBlur={e => {
                e.target.style.borderColor = "var(--b1)";
                e.target.style.boxShadow = "none";
              }}
            />
            <button
              onClick={handleBuildApp}
              style={{
                position: "absolute", insetInlineEnd: 10, top: "50%", transform: "translateY(-50%)",
                padding: "7px 16px", borderRadius: 8, border: "none",
                background: prompt.trim().length > 2
                  ? "linear-gradient(135deg, var(--accent) 0%, var(--teal) 100%)"
                  : "var(--bg-card)",
                color: prompt.trim().length > 2 ? "white" : "var(--t4)",
                fontSize: 12, fontWeight: 600, cursor: "pointer",
                transition: "all 0.15s",
                boxShadow: prompt.trim().length > 2 ? "0 2px 10px rgba(110,50,224,0.28)" : "none",
              }}
            >
              {t("buildSection.buildBtn")}
            </button>
          </div>

          {/* Template chips */}
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 10 }}>
            {ideaChips.map(idea => (
              <button
                key={idea}
                onClick={() => { setPrompt(t("buildSection.ideaPrompt", { idea })); promptRef.current?.focus(); }}
                style={{
                  padding: "4px 11px", borderRadius: 99, fontSize: 11, fontWeight: 500,
                  background: "var(--bg-card)", border: "1px solid var(--b1)",
                  color: "var(--t3)", cursor: "pointer",
                  transition: "all 0.12s",
                }}
                onMouseEnter={e => {
                  (e.currentTarget as HTMLButtonElement).style.borderColor = "var(--ba)";
                  (e.currentTarget as HTMLButtonElement).style.color = "var(--accent)";
                  (e.currentTarget as HTMLButtonElement).style.background = "var(--accent-dim)";
                }}
                onMouseLeave={e => {
                  (e.currentTarget as HTMLButtonElement).style.borderColor = "var(--b1)";
                  (e.currentTarget as HTMLButtonElement).style.color = "var(--t3)";
                  (e.currentTarget as HTMLButtonElement).style.background = "var(--bg-card)";
                }}
              >
                {idea}
              </button>
            ))}
          </div>
        </div>

        {/* ── KPI Stats ───────────────────────────────────────── */}
        {stats && (
          <div className="dash-kpi-grid" style={{ marginBottom: 20 }}>
            {kpis.map((k, i) => (
              <div key={i} className={`dash-kpi${k.accent ? " dash-kpi--accent" : ""}`}>
                <div className="dash-kpi__icon">{k.icon}</div>
                <div className="dash-kpi__body">
                  <div className="dash-kpi__value">{k.value}</div>
                  <div className="dash-kpi__label">{k.label}</div>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* ── My Apps ─────────────────────────────────────────── */}
        <div style={{ marginBottom: 20 }}>
          {/* Section header */}
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
            <div>
              <div className="dash-section-title">{t("apps.title")}</div>
              <div className="dash-section-sub">
                {projects.length > 0
                  ? t("apps.count", { count: projects.length })
                  : t("apps.noApps")}
              </div>
            </div>
            {projects.length > 0 && (
              <div style={{ position: "relative", display: "flex", alignItems: "center" }}>
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ position: "absolute", insetInlineStart: 10, color: "var(--t5)", pointerEvents: "none" }}>
                  <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
                </svg>
                <input
                  value={search}
                  onChange={e => setSearch(e.target.value)}
                  placeholder={t("apps.search")}
                  style={{
                    paddingInlineStart: 30, paddingInlineEnd: 12, paddingTop: 6, paddingBottom: 6,
                    fontSize: 12, borderRadius: 8, border: "1px solid var(--b1)",
                    background: "var(--bg-card)", color: "var(--t1)", outline: "none",
                  }}
                />
              </div>
            )}
          </div>

          {/* New project form */}
          <AnimatePresence>
            {creating && (
              <motion.div
                initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }}
                style={{
                  background: "var(--bg-surface)", border: "1px solid var(--accent-border)",
                  borderRadius: 12, padding: "18px", marginBottom: 12,
                  boxShadow: "0 0 0 3px var(--accent-dim)",
                }}
              >
                <div style={{ fontSize: 12, fontWeight: 700, color: "var(--t1)", marginBottom: 10 }}>{t("createForm.title")}</div>
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  <input
                    value={newName} onChange={e => setNewName(e.target.value)}
                    placeholder={t("createForm.namePlaceholder")}
                    style={{
                      padding: "9px 12px", fontSize: 13, borderRadius: 8,
                      border: "1px solid var(--b1)", background: "var(--bg-card)", color: "var(--t1)", outline: "none",
                    }}
                    onKeyDown={e => e.key === "Enter" && createProject()}
                    autoFocus
                  />
                  <textarea
                    value={newDesc} onChange={e => setNewDesc(e.target.value)}
                    placeholder={t("createForm.descPlaceholder")}
                    style={{
                      padding: "9px 12px", fontSize: 12, borderRadius: 8,
                      border: "1px solid var(--b1)", background: "var(--bg-card)", color: "var(--t1)", outline: "none",
                      resize: "vertical", minHeight: 56, fontFamily: "inherit",
                    }}
                  />
                  <div style={{ display: "flex", gap: 8 }}>
                    <button
                      onClick={createProject}
                      disabled={saving || newName.trim().length < 2}
                      style={{
                        padding: "7px 16px", borderRadius: 8, border: "none", cursor: "pointer",
                        background: "linear-gradient(135deg, var(--accent) 0%, var(--teal) 100%)",
                        color: "white", fontSize: 12, fontWeight: 600,
                        opacity: saving || newName.trim().length < 2 ? 0.5 : 1,
                      }}
                    >
                      {saving ? t("createForm.creating") : t("createForm.create")}
                    </button>
                    <button
                      onClick={() => { setCreating(false); setNewName(""); setNewDesc(""); }}
                      style={{
                        padding: "7px 14px", borderRadius: 8, border: "1px solid var(--b1)",
                        background: "transparent", color: "var(--t3)", fontSize: 12, cursor: "pointer",
                      }}
                    >
                      {t("createForm.cancel")}
                    </button>
                  </div>
                </div>
              </motion.div>
            )}
          </AnimatePresence>

          {/* Apps grid */}
          {loadingProj ? (
            <div className="dash-apps-grid">
              {[1, 2, 3].map(i => <div key={i} className="skeleton" style={{ height: 140, borderRadius: 12 }} />)}
            </div>
          ) : projectsQuery.status === "error" ? (
            <ErrorState message={t("apps.loadError")} onRetry={projectsQuery.refetch} />
          ) : filteredProjects.length === 0 && !creating ? (
            <div style={{
              display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
              padding: "40px 24px", gap: 12,
              background: "var(--bg-card)", borderRadius: 12, border: "1px dashed var(--b2)",
            }}>
              <div style={{
                width: 48, height: 48, borderRadius: 14,
                background: "var(--accent-dim)", display: "flex", alignItems: "center", justifyContent: "center",
                color: "var(--accent)",
              }}>
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
                  <rect x="2" y="3" width="20" height="14" rx="2"/>
                  <path d="M8 21h8M12 17v4M7 8l2 2-2 2M11 12h4"/>
                </svg>
              </div>
              <div style={{ textAlign: "center" }}>
                <div style={{ fontSize: 14, fontWeight: 700, color: "var(--t1)", marginBottom: 5 }}>{t("apps.emptyTitle")}</div>
                <div style={{ fontSize: 12, color: "var(--t4)", maxWidth: 260, lineHeight: 1.6 }}>{t("apps.emptyDesc")}</div>
              </div>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", justifyContent: "center" }}>
                <button
                  onClick={handleBuildApp}
                  style={{
                    padding: "8px 18px", borderRadius: 9, border: "none",
                    background: "linear-gradient(135deg, var(--accent) 0%, var(--teal) 100%)",
                    color: "white", fontSize: 12, fontWeight: 600, cursor: "pointer",
                  }}
                >{t("apps.buildWithAI")}</button>
                <button
                  onClick={() => setCreating(true)}
                  style={{
                    padding: "8px 16px", borderRadius: 9, border: "1px solid var(--b1)",
                    background: "transparent", color: "var(--t2)", fontSize: 12, cursor: "pointer",
                  }}
                >{t("apps.createManually")}</button>
              </div>
            </div>
          ) : (
            <motion.div className="dash-apps-grid" layout>
              <AnimatePresence>
                {filteredProjects.map(p => (
                  <AppCard
                    key={p.id}
                    project={p}
                    onOpen={() => {
                      sessionStorage.setItem("flow_active_project", p.id);
                      setPage("app-builder");
                    }}
                    onDelete={() => deleteProject(p.id, p.name)}
                  />
                ))}
              </AnimatePresence>
            </motion.div>
          )}
        </div>

        {/* ── Active Agents ──────────────────────────────────── */}
        <div style={{ marginBottom: 20 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
            <div className="dash-section-title">{t("agents.title")}</div>
            <button
              onClick={() => setPage("agentos")}
              style={{ fontSize: 11, color: "var(--accent)", background: "none", border: "none", cursor: "pointer", fontWeight: 600 }}
            >
              {t("quickNav.agents.label")} →
            </button>
          </div>
          {agentsQuery.status === "loading" ? (
            <div style={{ display: "flex", gap: 10 }}>
              {[1, 2, 3].map(i => <div key={i} className="skeleton" style={{ height: 56, borderRadius: 10, flex: 1 }} />)}
            </div>
          ) : agents.length === 0 ? (
            <div style={{
              padding: "20px 24px", background: "var(--bg-card)", borderRadius: 12,
              border: "1px dashed var(--b2)", textAlign: "center",
            }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: "var(--t3)", marginBottom: 3 }}>{t("agents.empty")}</div>
              <div style={{ fontSize: 11, color: "var(--t5)" }}>{t("agents.emptyDesc")}</div>
            </div>
          ) : (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: 10 }}>
              {agents.slice(0, 6).map(ag => {
                const liveStatus = ag.live?.status ?? "idle";
                const statusColor = liveStatus === "running" ? "var(--green)" : liveStatus === "error" ? "var(--red)" : "var(--t5)";
                return (
                  <div
                    key={ag.name}
                    style={{
                      padding: "12px 14px", background: "var(--bg-card)", borderRadius: 10,
                      border: `1px solid ${liveStatus === "running" ? "var(--accent-border)" : "var(--b1)"}`,
                      display: "flex", alignItems: "center", gap: 10,
                    }}
                  >
                    <div style={{
                      width: 32, height: 32, borderRadius: 9, flexShrink: 0,
                      background: liveStatus === "running" ? "var(--accent-dim)" : "var(--bg-base)",
                      display: "flex", alignItems: "center", justifyContent: "center",
                      color: liveStatus === "running" ? "var(--accent)" : "var(--t4)",
                    }}>
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3"/></svg>
                    </div>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: 12, fontWeight: 700, color: "var(--t1)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{ag.name}</div>
                      <div style={{ display: "flex", alignItems: "center", gap: 4, marginTop: 2 }}>
                        <span style={{ width: 5, height: 5, borderRadius: "50%", background: statusColor, flexShrink: 0 }} />
                        <span style={{ fontSize: 10, color: statusColor, fontWeight: 600, textTransform: "capitalize" }}>
                          {t(`agents.status.${liveStatus}`, { defaultValue: liveStatus })}
                        </span>
                        {ag.stats?.run_count > 0 && (
                          <span style={{ fontSize: 10, color: "var(--t5)", marginLeft: 4 }}>
                            {ag.stats.run_count} runs
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* ── Automations ─────────────────────────────────────── */}
        <div style={{ marginBottom: 20 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
            <div className="dash-section-title">{t("automations.title")}</div>
            <button
              onClick={() => setPage("automation")}
              style={{ fontSize: 11, color: "var(--accent)", background: "none", border: "none", cursor: "pointer", fontWeight: 600 }}
            >
              {t("automations.viewAll")} →
            </button>
          </div>
          {workflowsQuery.status === "loading" ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {[1, 2].map(i => <div key={i} className="skeleton" style={{ height: 44, borderRadius: 10 }} />)}
            </div>
          ) : workflowRuns.length === 0 ? (
            <div style={{
              padding: "20px 24px", background: "var(--bg-card)", borderRadius: 12,
              border: "1px dashed var(--b2)", textAlign: "center",
            }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: "var(--t3)", marginBottom: 3 }}>{t("automations.empty")}</div>
              <div style={{ fontSize: 11, color: "var(--t5)" }}>{t("automations.emptyDesc")}</div>
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {workflowRuns.slice(0, 5).map(run => {
                const runColor = run.status === "completed" ? "var(--green)" : run.status === "running" ? "var(--accent)" : run.status === "failed" ? "var(--red)" : "var(--t5)";
                return (
                  <div
                    key={run.id}
                    style={{
                      padding: "10px 14px", background: "var(--bg-card)", borderRadius: 10,
                      border: "1px solid var(--b1)", display: "flex", alignItems: "center", gap: 10,
                    }}
                  >
                    <div style={{ width: 5, height: 5, borderRadius: "50%", background: runColor, flexShrink: 0 }} />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <span style={{ fontSize: 12, fontWeight: 600, color: "var(--t1)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", display: "block" }}>
                        {run.name}
                      </span>
                    </div>
                    <span style={{ fontSize: 10, color: runColor, fontWeight: 600, textTransform: "capitalize", flexShrink: 0 }}>{run.status}</span>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* ── Bottom row: Activity + Quick Nav ─────────────── */}
        <div style={{
          display: "grid",
          gridTemplateColumns: "1fr 280px",
          gap: 14,
        }}>
          {/* Recent Activity */}
          <div className="dash-activity">
            <div style={{ fontSize: 13, fontWeight: 700, color: "var(--t1)", marginBottom: 14 }}>
              {t("activity.title")}
            </div>
            {activity.length === 0 ? (
              <div style={{
                display: "flex", flexDirection: "column", alignItems: "center",
                padding: "20px 0", gap: 8, color: "var(--t4)",
              }}>
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                  <path d="M12 20V10M18 20V4M6 20v-6"/>
                </svg>
                <span style={{ fontSize: 12 }}>{t("activity.empty")}</span>
              </div>
            ) : (
              <div>
                {activity.slice(0, 8).map((a, i) => {
                  const meta = ACTION_META[a.action] ?? { labelKey: a.action, color: "var(--t4)", icon: null };
                  return (
                    <div
                      key={i}
                      className="dash-activity-item"
                      style={{
                        borderBottom: i < Math.min(activity.length, 8) - 1 ? "1px solid var(--b1)" : "none",
                      }}
                    >
                      <div
                        className="dash-activity-icon"
                        style={{ background: meta.color + "1a", color: meta.color }}
                      >
                        {meta.icon}
                      </div>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: 12, fontWeight: 600, color: "var(--t2)" }}>{t(meta.labelKey)}</div>
                        {a.details.prompt_preview && (
                          <div style={{
                            fontSize: 11, color: "var(--t4)",
                            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                          }}>
                            "{a.details.prompt_preview}"
                          </div>
                        )}
                      </div>
                      <span style={{ fontSize: 10, color: "var(--t5)", flexShrink: 0 }}>
                        {relTime(a.time, lang)}
                      </span>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Quick Nav */}
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: "var(--t4)", textTransform: "uppercase", letterSpacing: "0.08em", padding: "0 2px", marginBottom: 2 }}>
              Quick Access
            </div>
            {quickNavItems.map(item => (
              <button
                key={item.labelKey}
                className="dash-qnav"
                onClick={() => setPage(item.page)}
              >
                <div style={{
                  width: 32, height: 32, borderRadius: 9, flexShrink: 0,
                  background: item.color + "15", color: item.color,
                  display: "flex", alignItems: "center", justifyContent: "center",
                }}>
                  {item.icon}
                </div>
                <div style={{ flex: 1, minWidth: 0, textAlign: "start" }}>
                  <div style={{ fontSize: 12, fontWeight: 600, color: "var(--t1)" }}>
                    {t(`${item.labelKey}.label`)}
                  </div>
                  <div style={{ fontSize: 10, color: "var(--t4)", marginTop: 1 }}>
                    {t(`${item.labelKey}.desc`)}
                  </div>
                </div>
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ color: "var(--t5)", flexShrink: 0 }}>
                  <polyline points="9 18 15 12 9 6"/>
                </svg>
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
