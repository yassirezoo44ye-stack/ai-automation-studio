/**
 * Flow Dashboard — the main entry point.
 * Focuses on: "What do you want to build?" AI prompt → Your Apps → Activity.
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

/* ── Color helpers ─────────────────────────────────────────────────── */
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

/* ── Stat card ─────────────────────────────────────────────────────── */
function StatCard({ label, value, icon, accent }: { label: string; value: string | number; icon: React.ReactNode; accent?: boolean }) {
  return (
    <div style={{
      background: accent ? "linear-gradient(135deg, var(--accent) 0%, var(--teal) 100%)" : "var(--bg-surface)",
      border: accent ? "none" : "1px solid var(--b1)",
      borderRadius: 16, padding: "20px 22px",
      display: "flex", alignItems: "center", gap: 14,
      boxShadow: accent ? "var(--shadow-md)" : "var(--shadow-xs)",
      flex: "1 1 160px", minWidth: 140,
    }}>
      <div style={{
        width: 40, height: 40, borderRadius: 12, flexShrink: 0,
        background: accent ? "rgba(255,255,255,0.18)" : "var(--accent-dim)",
        display: "flex", alignItems: "center", justifyContent: "center",
        color: accent ? "white" : "var(--accent)",
      }}>
        {icon}
      </div>
      <div>
        <div style={{ fontSize: 22, fontWeight: 700, color: accent ? "white" : "var(--t1)", lineHeight: 1.1 }}>{value}</div>
        <div style={{ fontSize: 12, color: accent ? "rgba(255,255,255,0.75)" : "var(--t4)", marginTop: 3 }}>{label}</div>
      </div>
    </div>
  );
}

/* ── App card ──────────────────────────────────────────────────────── */
function AppCard({ project, onOpen, onDelete }: {
  project: Project;
  onOpen: () => void;
  onDelete: () => void;
}) {
  const { lang } = useLangContext();
  const status = project.status ?? "active";
  const statusColor = STATUS_COLOR[status] ?? "var(--t4)";

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.96 }}
      style={{
        background: "var(--bg-surface)",
        border: "1px solid var(--b1)",
        borderRadius: 18, padding: "20px",
        display: "flex", flexDirection: "column", gap: 14,
        cursor: "pointer",
        transition: "box-shadow 0.15s, border-color 0.15s",
        boxShadow: "var(--shadow-xs)",
      }}
      onClick={onOpen}
      onMouseEnter={e => {
        (e.currentTarget as HTMLDivElement).style.boxShadow = "var(--shadow-md)";
        (e.currentTarget as HTMLDivElement).style.borderColor = "var(--accent-border)";
      }}
      onMouseLeave={e => {
        (e.currentTarget as HTMLDivElement).style.boxShadow = "var(--shadow-xs)";
        (e.currentTarget as HTMLDivElement).style.borderColor = "var(--b1)";
      }}
      role="button"
      tabIndex={0}
      aria-label={`Open ${project.name}`}
      onKeyDown={e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onOpen(); } }}
    >
      {/* Header */}
      <div style={{ display: "flex", alignItems: "flex-start", gap: 12 }}>
        <ProjectAvatar name={project.name} size={44} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: "var(--t1)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {project.name}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 4 }}>
            <span style={{ width: 6, height: 6, borderRadius: "50%", background: statusColor, flexShrink: 0 }} />
            <span style={{ fontSize: 11, color: statusColor, fontWeight: 600, textTransform: "capitalize" }}>{status}</span>
          </div>
        </div>
        <button
          onClick={e => { e.stopPropagation(); onDelete(); }}
          style={{ background: "none", border: "none", cursor: "pointer", color: "var(--t5)", padding: 4, borderRadius: 6, flexShrink: 0 }}
          onMouseEnter={e => (e.currentTarget.style.color = "var(--red)")}
          onMouseLeave={e => (e.currentTarget.style.color = "var(--t5)")}
          title="Delete app"
          aria-label={`Delete ${project.name}`}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/>
          </svg>
        </button>
      </div>

      {/* Description */}
      {project.description && (
        <p style={{ fontSize: 12, color: "var(--t4)", margin: 0, lineHeight: 1.5, overflow: "hidden", display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical" }}>
          {project.description}
        </p>
      )}

      {/* Footer */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: "auto" }}>
        <span style={{ fontSize: 11, color: "var(--t5)" }}>Updated {relTime(project.created_at, lang)}</span>
        <button
          onClick={e => { e.stopPropagation(); onOpen(); }}
          style={{
            background: "var(--accent-dim)", border: "1px solid var(--accent-border)",
            borderRadius: 8, padding: "5px 12px", fontSize: 12, fontWeight: 600,
            color: "var(--accent)", cursor: "pointer",
          }}
        >
          Open →
        </button>
      </div>
    </motion.div>
  );
}

/* ── Activity item ─────────────────────────────────────────────────── */
const ACTION_META: Record<string, { label: string; color: string; icon: React.ReactNode }> = {
  agent_run:            { label: "Agent Run",    color: "var(--accent)", icon: <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3"/></svg> },
  message_sent:         { label: "Message",      color: "var(--blue)",   icon: <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg> },
  build:                { label: "Build",        color: "var(--green)",  icon: <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg> },
  project_created:      { label: "App Created",  color: "var(--yellow)", icon: <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg> },
  conversation_created: { label: "Chat",         color: "var(--blue)",   icon: <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg> },
};

/* ══════════════════════════════════════════════════════════════════
   Main HomePage
   ══════════════════════════════════════════════════════════════════ */
export function HomePage() {
  const { t: _t } = useTranslation("home");
  const { setPage } = useAppContext();
  const { lang } = useLangContext();
  const toast = useToast();

  const [prompt, setPrompt] = useState("");
  const [promptIdx, setPromptIdx] = useState(0);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName]   = useState("");
  const [newDesc, setNewDesc]   = useState("");
  const [saving, setSaving]     = useState(false);
  const [search, setSearch]     = useState("");
  const promptRef = useRef<HTMLTextAreaElement>(null);

  // Cycle through example prompts as placeholder
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

  const filteredProjects = projects.filter(p =>
    !search || p.name.toLowerCase().includes(search.toLowerCase()),
  ).sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());

  /* ── Build with AI — launches app builder with prompt ── */
  function handleBuildApp() {
    if (prompt.trim().length > 3) {
      // Store prompt for AppBuilder to pick up
      sessionStorage.setItem("flow_builder_prompt", prompt.trim());
    }
    setPage("app-builder");
  }

  /* ── Quick project creation ─────────────────────────── */
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
      toast("App created successfully", "ok");
    } catch { toast("Failed to create app", "err"); }
    finally { setSaving(false); }
  }

  async function deleteProject(id: string, name: string) {
    if (!confirm(`Delete "${name}"? This cannot be undone.`)) return;
    try {
      const r = await apiFetch(`/api/projects/${id}`, { method: "DELETE" });
      if (!r.ok) throw new Error();
      toast(`"${name}" deleted`, "ok");
    } catch { toast("Failed to delete app", "err"); }
    finally { projectsQuery.refetch(); }
  }

  /* ── Backend status ──────────────────────────────────── */
  const [backendOk, setBackendOk] = useState<boolean | null>(null);
  useEffect(() => {
    apiFetch("/health").then(r => setBackendOk(r.ok)).catch(() => setBackendOk(false));
  }, []);

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      {/* ── Page header ──────────────────────────────────────── */}
      <header style={{
        padding: "0 28px", height: 57, minHeight: 57,
        borderBottom: "1px solid var(--b1)",
        display: "flex", alignItems: "center", justifyContent: "space-between",
        background: "var(--bg-surface)", flexShrink: 0,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontSize: 15, fontWeight: 600, color: "var(--t1)" }}>Dashboard</span>
          <div style={{
            display: "flex", alignItems: "center", gap: 5, padding: "4px 10px",
            borderRadius: 99, fontSize: 11, fontWeight: 600,
            background: backendOk === true ? "var(--green-dim)" : "var(--bg-card)",
            color: backendOk === true ? "var(--green)" : "var(--t4)",
            border: `1px solid ${backendOk === true ? "rgba(22,163,74,0.2)" : "var(--b1)"}`,
          }}>
            <div style={{ width: 5, height: 5, borderRadius: "50%", background: backendOk === true ? "var(--green)" : "var(--t5)" }} />
            {backendOk === true ? "Online" : backendOk === false ? "Offline" : "Checking…"}
          </div>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button
            onClick={() => { setCreating(true); }}
            style={{
              display: "flex", alignItems: "center", gap: 6,
              padding: "7px 14px", borderRadius: 10, border: "1px solid var(--b1)",
              background: "var(--bg-card)", color: "var(--t2)",
              fontSize: 13, fontWeight: 500, cursor: "pointer",
            }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
            New App
          </button>
          <button
            onClick={handleBuildApp}
            style={{
              display: "flex", alignItems: "center", gap: 6,
              padding: "7px 16px", borderRadius: 10, border: "none",
              background: "linear-gradient(135deg, var(--accent) 0%, var(--teal) 100%)",
              color: "white", fontSize: 13, fontWeight: 600, cursor: "pointer",
              boxShadow: "var(--shadow-btn)",
            }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg>
            Build with AI
          </button>
        </div>
      </header>

      <div style={{ flex: 1, overflowY: "auto", padding: "28px 28px 40px" }}>

        {/* ── AI Build prompt ─────────────────────────────── */}
        <div style={{
          background: "linear-gradient(135deg, var(--accent-dim) 0%, var(--teal-dim) 100%)",
          border: "1px solid var(--accent-border)",
          borderRadius: 24, padding: "28px 32px", marginBottom: 28,
        }}>
          <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: "0.08em", color: "var(--accent)", textTransform: "uppercase", marginBottom: 6 }}>
            AI Business OS
          </div>
          <h1 style={{ fontSize: 22, fontWeight: 700, color: "var(--t1)", letterSpacing: "-0.5px", margin: "0 0 16px" }}>
            What do you want to build?
          </h1>
          <div style={{ position: "relative" }}>
            <textarea
              ref={promptRef}
              value={prompt}
              onChange={e => setPrompt(e.target.value)}
              onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleBuildApp(); } }}
              placeholder={EXAMPLE_PROMPTS[promptIdx]}
              rows={2}
              style={{
                width: "100%", padding: "14px 120px 14px 18px",
                fontSize: 14, lineHeight: 1.6,
                background: "var(--bg-surface)",
                border: "1px solid var(--b1)",
                borderRadius: 14, color: "var(--t1)",
                resize: "none", outline: "none",
                fontFamily: "inherit",
                boxSizing: "border-box",
                boxShadow: "var(--shadow-sm)",
                transition: "border-color 0.15s",
              }}
              onFocus={e => (e.target.style.borderColor = "var(--accent)")}
              onBlur={e => (e.target.style.borderColor = "var(--b1)")}
            />
            <button
              onClick={handleBuildApp}
              style={{
                position: "absolute", right: 10, top: "50%", transform: "translateY(-50%)",
                padding: "8px 18px", borderRadius: 10, border: "none",
                background: prompt.trim().length > 2
                  ? "linear-gradient(135deg, var(--accent) 0%, var(--teal) 100%)"
                  : "var(--bg-card)",
                color: prompt.trim().length > 2 ? "white" : "var(--t4)",
                fontSize: 13, fontWeight: 600, cursor: "pointer",
                transition: "all 0.15s",
              }}
            >
              Build App →
            </button>
          </div>
          {/* Quick ideas */}
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 12 }}>
            {["CRM", "Inventory", "HR Portal", "Support Tickets", "Project Tracker"].map(idea => (
              <button
                key={idea}
                onClick={() => {
                  setPrompt(`Build a ${idea.toLowerCase()} system with AI automation`);
                  promptRef.current?.focus();
                }}
                style={{
                  padding: "5px 12px", borderRadius: 99, fontSize: 11, fontWeight: 500,
                  background: "var(--bg-surface)", border: "1px solid var(--b1)",
                  color: "var(--t3)", cursor: "pointer",
                  transition: "all 0.12s",
                }}
                onMouseEnter={e => { (e.currentTarget as HTMLButtonElement).style.borderColor = "var(--accent)"; (e.currentTarget as HTMLButtonElement).style.color = "var(--accent)"; }}
                onMouseLeave={e => { (e.currentTarget as HTMLButtonElement).style.borderColor = "var(--b1)"; (e.currentTarget as HTMLButtonElement).style.color = "var(--t3)"; }}
              >
                {idea}
              </button>
            ))}
          </div>
        </div>

        {/* ── Stats row ───────────────────────────────────── */}
        {stats && (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 12, marginBottom: 28 }}>
            <StatCard
              label="Apps Built"
              value={stats.projects ?? 0}
              accent
              icon={<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/></svg>}
            />
            <StatCard
              label="AI Conversations"
              value={stats.conversations ?? 0}
              icon={<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>}
            />
            <StatCard
              label="Agent Runs"
              value={stats.agent_runs ?? 0}
              icon={<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>}
            />
            <StatCard
              label="Success Rate"
              value={stats.agent_runs ? `${stats.success_rate ?? 0}%` : "—"}
              icon={<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="20 6 9 17 4 12"/></svg>}
            />
          </div>
        )}

        {/* ── Your Apps section ───────────────────────────── */}
        <div style={{ marginBottom: 28 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14 }}>
            <div>
              <h2 style={{ fontSize: 16, fontWeight: 700, color: "var(--t1)", margin: 0 }}>Your Apps</h2>
              <p style={{ fontSize: 12, color: "var(--t4)", margin: "4px 0 0" }}>
                {projects.length > 0 ? `${projects.length} app${projects.length !== 1 ? "s" : ""}` : "No apps yet"}
              </p>
            </div>
            {projects.length > 0 && (
              <div style={{ position: "relative", display: "flex", alignItems: "center" }}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ position: "absolute", left: 10, color: "var(--t4)", pointerEvents: "none" }}>
                  <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
                </svg>
                <input
                  value={search}
                  onChange={e => setSearch(e.target.value)}
                  placeholder="Search apps…"
                  style={{
                    paddingLeft: 32, paddingRight: 12, paddingTop: 7, paddingBottom: 7,
                    fontSize: 12, borderRadius: 9, border: "1px solid var(--b1)",
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
                initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }}
                style={{
                  background: "var(--bg-surface)", border: "1px solid var(--accent-border)",
                  borderRadius: 18, padding: "20px", marginBottom: 16,
                  boxShadow: "var(--shadow-glow)",
                }}
              >
                <div style={{ fontSize: 13, fontWeight: 600, color: "var(--t1)", marginBottom: 12 }}>Create New App</div>
                <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                  <input
                    value={newName} onChange={e => setNewName(e.target.value)}
                    placeholder="App name (e.g. Sales CRM)"
                    style={{
                      padding: "10px 14px", fontSize: 13, borderRadius: 10,
                      border: "1px solid var(--b1)", background: "var(--bg-card)", color: "var(--t1)", outline: "none",
                    }}
                    onKeyDown={e => e.key === "Enter" && createProject()}
                    autoFocus
                  />
                  <textarea
                    value={newDesc} onChange={e => setNewDesc(e.target.value)}
                    placeholder="Brief description (optional)"
                    style={{
                      padding: "10px 14px", fontSize: 12, borderRadius: 10,
                      border: "1px solid var(--b1)", background: "var(--bg-card)", color: "var(--t1)", outline: "none",
                      resize: "vertical", minHeight: 64, fontFamily: "inherit",
                    }}
                  />
                  <div style={{ display: "flex", gap: 8 }}>
                    <button
                      onClick={createProject}
                      disabled={saving || newName.trim().length < 2}
                      style={{
                        padding: "8px 18px", borderRadius: 10, border: "none", cursor: "pointer",
                        background: "linear-gradient(135deg, var(--accent) 0%, var(--teal) 100%)",
                        color: "white", fontSize: 13, fontWeight: 600,
                        opacity: saving || newName.trim().length < 2 ? 0.5 : 1,
                      }}
                    >
                      {saving ? "Creating…" : "Create App"}
                    </button>
                    <button
                      onClick={() => { setCreating(false); setNewName(""); setNewDesc(""); }}
                      style={{
                        padding: "8px 16px", borderRadius: 10, border: "1px solid var(--b1)",
                        background: "transparent", color: "var(--t3)", fontSize: 13, cursor: "pointer",
                      }}
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              </motion.div>
            )}
          </AnimatePresence>

          {/* Apps grid */}
          {loadingProj ? (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: 14 }}>
              {[1, 2, 3].map(i => <div key={i} className="skeleton" style={{ height: 160, borderRadius: 18 }} />)}
            </div>
          ) : projectsQuery.status === "error" ? (
            <ErrorState message="Failed to load apps" onRetry={projectsQuery.refetch} />
          ) : filteredProjects.length === 0 && !creating ? (
            <div style={{
              display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
              padding: "48px 24px", gap: 14,
              background: "var(--bg-card)", borderRadius: 18, border: "1px dashed var(--b2)",
            }}>
              <div style={{
                width: 56, height: 56, borderRadius: 16,
                background: "var(--accent-dim)", display: "flex", alignItems: "center", justifyContent: "center",
                color: "var(--accent)",
              }}>
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/><path d="M7 8l2 2-2 2M11 12h4"/></svg>
              </div>
              <div style={{ textAlign: "center" }}>
                <div style={{ fontSize: 15, fontWeight: 700, color: "var(--t1)", marginBottom: 6 }}>No apps yet</div>
                <div style={{ fontSize: 13, color: "var(--t4)", maxWidth: 280 }}>
                  Describe what you want to build and let AI create it in seconds.
                </div>
              </div>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", justifyContent: "center" }}>
                <button
                  onClick={handleBuildApp}
                  style={{
                    padding: "9px 20px", borderRadius: 10, border: "none",
                    background: "linear-gradient(135deg, var(--accent) 0%, var(--teal) 100%)",
                    color: "white", fontSize: 13, fontWeight: 600, cursor: "pointer",
                  }}
                >
                  Build with AI
                </button>
                <button
                  onClick={() => setCreating(true)}
                  style={{
                    padding: "9px 18px", borderRadius: 10, border: "1px solid var(--b1)",
                    background: "transparent", color: "var(--t2)", fontSize: 13, cursor: "pointer",
                  }}
                >
                  Create Manually
                </button>
              </div>
            </div>
          ) : (
            <motion.div
              style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: 14 }}
              layout
            >
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

        {/* ── Bottom row: Activity + Quick Links ──────────── */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 320px", gap: 16 }}>
          {/* Recent Activity */}
          <div style={{
            background: "var(--bg-surface)", border: "1px solid var(--b1)",
            borderRadius: 18, padding: "20px 22px",
          }}>
            <div style={{ fontSize: 14, fontWeight: 600, color: "var(--t1)", marginBottom: 14 }}>Recent Activity</div>
            {activity.length === 0 ? (
              <div style={{ display: "flex", flexDirection: "column", alignItems: "center", padding: "24px 0", gap: 8, color: "var(--t4)" }}>
                <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M12 20V10"/><path d="M18 20V4"/><path d="M6 20v-6"/></svg>
                <span style={{ fontSize: 13 }}>No activity yet</span>
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column" }}>
                {activity.slice(0, 8).map((a, i) => {
                  const meta = ACTION_META[a.action] ?? { label: a.action, color: "var(--t4)", icon: null };
                  return (
                    <div key={i} style={{
                      display: "flex", alignItems: "center", gap: 10, padding: "9px 0",
                      borderBottom: i < Math.min(activity.length, 8) - 1 ? "1px solid var(--b1)" : "none",
                    }}>
                      <div style={{
                        width: 28, height: 28, borderRadius: 8, flexShrink: 0,
                        background: meta.color + "18",
                        color: meta.color,
                        display: "flex", alignItems: "center", justifyContent: "center",
                      }}>
                        {meta.icon}
                      </div>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: 12, fontWeight: 600, color: "var(--t2)" }}>{meta.label}</div>
                        {a.details.prompt_preview && (
                          <div style={{ fontSize: 11, color: "var(--t4)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                            "{a.details.prompt_preview}"
                          </div>
                        )}
                      </div>
                      <span style={{ fontSize: 11, color: "var(--t5)", flexShrink: 0 }}>{relTime(a.time, lang)}</span>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Quick navigation panel */}
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {[
              { label: "Agents", desc: "Manage AI agents", page: "agentos" as const, color: "#6E32E0", icon: <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M4.22 4.22l2.12 2.12M17.66 17.66l2.12 2.12M2 12h3M19 12h3"/></svg> },
              { label: "Automations", desc: "Workflows & triggers", page: "automation" as const, color: "#2563EB", icon: <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="9 11 12 14 22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg> },
              { label: "Runs", desc: "Monitor executions", page: "runs" as const, color: "#0B7A70", icon: <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg> },
              { label: "Integrations", desc: "Connect your tools", page: "integrations" as const, color: "#A16207", icon: <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg> },
            ].map(item => (
              <button
                key={item.label}
                onClick={() => setPage(item.page)}
                style={{
                  display: "flex", alignItems: "center", gap: 12, padding: "14px 16px",
                  borderRadius: 14, border: "1px solid var(--b1)", cursor: "pointer",
                  background: "var(--bg-surface)", textAlign: "start",
                  transition: "all 0.12s",
                }}
                onMouseEnter={e => { (e.currentTarget as HTMLButtonElement).style.borderColor = item.color + "50"; (e.currentTarget as HTMLButtonElement).style.background = item.color + "08"; }}
                onMouseLeave={e => { (e.currentTarget as HTMLButtonElement).style.borderColor = "var(--b1)"; (e.currentTarget as HTMLButtonElement).style.background = "var(--bg-surface)"; }}
              >
                <div style={{
                  width: 36, height: 36, borderRadius: 10, flexShrink: 0,
                  background: item.color + "18", color: item.color,
                  display: "flex", alignItems: "center", justifyContent: "center",
                }}>
                  {item.icon}
                </div>
                <div>
                  <div style={{ fontSize: 13, fontWeight: 600, color: "var(--t1)" }}>{item.label}</div>
                  <div style={{ fontSize: 11, color: "var(--t4)" }}>{item.desc}</div>
                </div>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ marginLeft: "auto", color: "var(--t5)", flexShrink: 0 }}><polyline points="9 18 15 12 9 6"/></svg>
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
