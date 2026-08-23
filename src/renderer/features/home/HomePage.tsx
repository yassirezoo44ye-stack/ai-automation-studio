/**
 * FLOW Command Center — home page
 *
 * Sections:
 *   1. Command Bar hero (Build with AI prompt)
 *   2. KPI strip — 8 metrics
 *   3. Two-column body:
 *      LEFT  — AI Workforce | Needs Attention | Recent Work
 *      RIGHT — Quick Actions | Active Workflows | Quick Nav
 *
 * Uses only existing backend APIs:
 *   GET /api/stats          → KPIs + failed items + activity
 *   GET /api/agentos/agents → agent list + liveness
 *   GET /api/workflows/active → active workflow runs
 *   GET /api/workflows/approvals/pending → pending approvals count
 *   GET /api/projects        → project list
 */
import { useState, useRef, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { useAppContext } from "../../contexts/app";
import { useLangContext } from "../../contexts/lang";
import type { Lang } from "../../contexts/lang";
import { useToast } from "../../contexts/toast";
import { apiFetch, parseJSON } from "../../utils/api";
import { relTime } from "../../utils/time";
import { motion, AnimatePresence } from "framer-motion";
import { useAsyncData } from "../../shared/hooks/useAsyncData";
import { ErrorState } from "../../shared/ui/StateViews";
import type { Project } from "../../types";

// ── Types ──────────────────────────────────────────────────────────────────

type FailedRunItem = { id: string; agent_type: string; error: string; project_name: string; time: string };
type StatsResponse = {
  projects: number;
  agent_runs: number;
  completed_runs: number;
  failed_runs: number;
  active_runs: number;
  conversations: number;
  messages: number;
  success_rate: number;
  failed_run_items: FailedRunItem[];
  recent_activity: { action: string; details: Record<string, string>; time: string }[];
};

type AgentLive  = { status: "running" | "idle" | "error" | string };
type AgentEntry = {
  name: string; description: string;
  live: AgentLive;
  stats: { run_count: number; fail_count: number; last_run?: string };
};
type AgentsResponse = { count: number; agents: AgentEntry[] };

type WorkflowRun = { id: string; name: string; status: string; started_at?: string };
type WorkflowsResponse = { runs: WorkflowRun[] };
type ApprovalsResponse = { pending: string[] };

const EXAMPLE_PROMPTS = [
  "Build a CRM for my sales team with contacts, deals, and follow-ups",
  "Create an inventory management system with low-stock alerts",
  "Build an HR onboarding portal with task checklists and document storage",
  "Create a customer support ticketing system with AI triage",
  "Build a project tracker with time logging and team collaboration",
];

const ACTION_META: Record<string, { color: string; icon: React.ReactNode }> = {
  agent_run:            { color: "var(--accent)", icon: <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3"/></svg> },
  message_sent:         { color: "var(--blue)",   icon: <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg> },
  build:                { color: "var(--green)",  icon: <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg> },
  project_created:      { color: "var(--yellow)", icon: <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg> },
  conversation_created: { color: "var(--blue)",   icon: <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg> },
  deployment:           { color: "var(--teal)",   icon: <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/></svg> },
};

// ── Small reusable pieces ──────────────────────────────────────────────────

function Dot({ color, pulse }: { color: string; pulse?: boolean }) {
  return (
    <span style={{ position: "relative", display: "inline-flex", width: 7, height: 7, flexShrink: 0 }}>
      <span style={{ width: 7, height: 7, borderRadius: "50%", background: color, display: "block" }} />
      {pulse && (
        <span style={{
          position: "absolute", inset: -2, borderRadius: "50%",
          border: `1.5px solid ${color}`, opacity: 0.4,
          animation: "ping 1.5s cubic-bezier(0,0,0.2,1) infinite",
        }} />
      )}
    </span>
  );
}

function SectionHeader({ title, action, onAction }: { title: string; action?: string; onAction?: () => void }) {
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
      <div style={{ fontSize: 11, fontWeight: 700, color: "var(--t4)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
        {title}
      </div>
      {action && (
        <button onClick={onAction} style={{ fontSize: 11, color: "var(--accent)", background: "none", border: "none", cursor: "pointer", fontWeight: 600, padding: 0 }}>
          {action} →
        </button>
      )}
    </div>
  );
}

function Card({ children, onClick, style }: { children: React.ReactNode; onClick?: () => void; style?: React.CSSProperties }) {
  return (
    <div
      onClick={onClick}
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={onClick ? (e) => { if (e.key === "Enter") onClick(); } : undefined}
      style={{
        background: "var(--bg-card)", borderRadius: 10,
        border: "1px solid var(--b1)", padding: "12px 14px",
        cursor: onClick ? "pointer" : "default",
        transition: onClick ? "border-color 0.12s, box-shadow 0.12s" : undefined,
        ...style,
      }}
      onMouseEnter={onClick ? (e) => { (e.currentTarget as HTMLDivElement).style.borderColor = "var(--ba)"; } : undefined}
      onMouseLeave={onClick ? (e) => { (e.currentTarget as HTMLDivElement).style.borderColor = "var(--b1)"; } : undefined}
    >
      {children}
    </div>
  );
}

// ── KPI stat tile ──────────────────────────────────────────────────────────

function KpiTile({
  icon, label, value, accent, sub, onClick,
}: {
  icon: React.ReactNode; label: string; value: string | number;
  accent?: boolean; sub?: string; onClick?: () => void;
}) {
  return (
    <div
      onClick={onClick}
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={onClick ? (e) => { if (e.key === "Enter") onClick(); } : undefined}
      style={{
        background: accent ? "var(--accent-dim)" : "var(--bg-card)",
        border: `1px solid ${accent ? "var(--accent-border)" : "var(--b1)"}`,
        borderRadius: 10, padding: "14px 16px",
        cursor: onClick ? "pointer" : "default",
        transition: "border-color 0.12s, transform 0.1s",
        display: "flex", flexDirection: "column", gap: 6,
      }}
      onMouseEnter={onClick ? (e) => { (e.currentTarget as HTMLDivElement).style.transform = "translateY(-1px)"; } : undefined}
      onMouseLeave={onClick ? (e) => { (e.currentTarget as HTMLDivElement).style.transform = "none"; } : undefined}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div style={{ color: accent ? "var(--accent)" : "var(--t4)", display: "flex" }}>{icon}</div>
        {sub && <span style={{ fontSize: 9, color: "var(--t5)", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em" }}>{sub}</span>}
      </div>
      <div style={{ fontSize: 22, fontWeight: 800, color: accent ? "var(--accent)" : "var(--t1)", lineHeight: 1, letterSpacing: "-0.5px" }}>
        {value}
      </div>
      <div style={{ fontSize: 11, color: "var(--t4)", fontWeight: 500 }}>{label}</div>
    </div>
  );
}

// ── Agent workforce card ───────────────────────────────────────────────────

function AgentRow({ agent, onNavigate, lang }: { agent: AgentEntry; onNavigate: () => void; lang: Lang }) {
  const liveStatus = agent.live?.status ?? "idle";
  const isRunning  = liveStatus === "running";
  const isError    = liveStatus === "error";
  const dotColor   = isRunning ? "var(--green)" : isError ? "var(--red)" : "var(--t5)";

  return (
    <div
      onClick={onNavigate}
      role="button" tabIndex={0}
      onKeyDown={e => { if (e.key === "Enter") onNavigate(); }}
      style={{
        display: "flex", alignItems: "center", gap: 10,
        padding: "9px 12px", borderRadius: 8,
        background: isRunning ? "var(--accent-dim)" : "transparent",
        border: `1px solid ${isRunning ? "var(--accent-border)" : "var(--b1)"}`,
        cursor: "pointer", transition: "background 0.12s, border-color 0.12s",
        marginBottom: 6,
      }}
      onMouseEnter={e => { (e.currentTarget as HTMLDivElement).style.background = "var(--bg-surface)"; }}
      onMouseLeave={e => { (e.currentTarget as HTMLDivElement).style.background = isRunning ? "var(--accent-dim)" : "transparent"; }}
    >
      {/* Avatar */}
      <div style={{
        width: 28, height: 28, borderRadius: 8, flexShrink: 0,
        background: isRunning ? "var(--accent)" : "var(--bg-base)",
        display: "flex", alignItems: "center", justifyContent: "center",
        color: isRunning ? "white" : "var(--t4)",
      }}>
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M4.22 4.22l2.12 2.12M17.66 17.66l2.12 2.12M2 12h3M19 12h3"/></svg>
      </div>

      {/* Info */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: "var(--t1)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {agent.name}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 5, marginTop: 2 }}>
          <Dot color={dotColor} pulse={isRunning} />
          <span style={{ fontSize: 10, color: dotColor, fontWeight: 600, textTransform: "capitalize" }}>{liveStatus}</span>
          {(agent.stats?.run_count ?? 0) > 0 && (
            <span style={{ fontSize: 10, color: "var(--t5)", marginLeft: 2 }}>· {agent.stats.run_count} runs</span>
          )}
        </div>
      </div>

      {/* Last run */}
      {agent.stats?.last_run && (
        <span style={{ fontSize: 10, color: "var(--t5)", flexShrink: 0 }}>
          {relTime(agent.stats.last_run, lang)}
        </span>
      )}
    </div>
  );
}

// ── Attention item ─────────────────────────────────────────────────────────

function AttentionItem({
  severity, title, detail, action, onAction,
}: {
  severity: "critical" | "warning" | "info";
  title: string; detail?: string;
  action?: string; onAction?: () => void;
}) {
  const colors = {
    critical: { bg: "rgba(239,68,68,0.08)", border: "rgba(239,68,68,0.25)", dot: "var(--red)",    label: "Critical" },
    warning:  { bg: "rgba(234,179,8,0.08)",  border: "rgba(234,179,8,0.25)",  dot: "var(--yellow)", label: "Warning"  },
    info:     { bg: "rgba(59,130,246,0.08)", border: "rgba(59,130,246,0.25)", dot: "var(--blue)",  label: "Info"     },
  }[severity];

  return (
    <div style={{
      display: "flex", alignItems: "flex-start", gap: 10,
      padding: "10px 12px", borderRadius: 8,
      background: colors.bg, border: `1px solid ${colors.border}`,
      marginBottom: 6,
    }}>
      <Dot color={colors.dot} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: "var(--t1)", lineHeight: 1.3 }}>{title}</div>
        {detail && <div style={{ fontSize: 11, color: "var(--t4)", marginTop: 2, lineHeight: 1.4 }}>{detail}</div>}
      </div>
      {action && onAction && (
        <button
          onClick={onAction}
          style={{
            flexShrink: 0, padding: "3px 10px", fontSize: 11, fontWeight: 600,
            border: `1px solid ${colors.border}`, borderRadius: 6,
            background: "transparent", color: colors.dot, cursor: "pointer",
          }}
        >{action}</button>
      )}
    </div>
  );
}

// ── Quick action button ────────────────────────────────────────────────────

function QuickAction({ icon, label, desc, color, onClick }: {
  icon: React.ReactNode; label: string; desc: string;
  color: string; onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      style={{
        display: "flex", alignItems: "center", gap: 10, width: "100%",
        padding: "10px 12px", borderRadius: 9,
        background: "var(--bg-card)", border: "1px solid var(--b1)",
        cursor: "pointer", textAlign: "left", transition: "border-color 0.12s, background 0.12s",
        marginBottom: 6,
      }}
      onMouseEnter={e => {
        (e.currentTarget as HTMLButtonElement).style.borderColor = color;
        (e.currentTarget as HTMLButtonElement).style.background = color + "10";
      }}
      onMouseLeave={e => {
        (e.currentTarget as HTMLButtonElement).style.borderColor = "var(--b1)";
        (e.currentTarget as HTMLButtonElement).style.background = "var(--bg-card)";
      }}
    >
      <div style={{
        width: 32, height: 32, borderRadius: 9, flexShrink: 0,
        background: color + "18", color,
        display: "flex", alignItems: "center", justifyContent: "center",
      }}>
        {icon}
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: "var(--t1)" }}>{label}</div>
        <div style={{ fontSize: 11, color: "var(--t4)", marginTop: 1 }}>{desc}</div>
      </div>
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ color: "var(--t5)", flexShrink: 0 }}>
        <polyline points="9 18 15 12 9 6"/>
      </svg>
    </button>
  );
}

// ══════════════════════════════════════════════════════════════════════════
// HomePage
// ══════════════════════════════════════════════════════════════════════════
export function HomePage() {
  const { setPage } = useAppContext();
  const { lang } = useLangContext();
  const toast = useToast();
  const { t } = useTranslation("home");

  const [prompt, setPrompt]       = useState("");
  const [promptIdx, setPromptIdx] = useState(0);
  const [creating, setCreating]   = useState(false);
  const [newName, setNewName]     = useState("");
  const [newDesc, setNewDesc]     = useState("");
  const [saving, setSaving]       = useState(false);
  const promptRef = useRef<HTMLTextAreaElement>(null);

  // Cycle placeholder
  useEffect(() => {
    const id = setInterval(() => setPromptIdx(i => (i + 1) % EXAMPLE_PROMPTS.length), 4000);
    return () => clearInterval(id);
  }, []);

  // ── Data ────────────────────────────────────────────────────────────────
  const statsQ = useAsyncData<StatsResponse>(
    () => apiFetch("/api/stats").then(r => parseJSON<StatsResponse>(r, "/api/stats")),
    [],
  );
  const stats = statsQ.data;

  const agentsQ = useAsyncData<AgentsResponse>(
    () => apiFetch("/api/agentos/agents").then(r => parseJSON<AgentsResponse>(r, "/api/agentos/agents")),
    [],
  );
  const agents = agentsQ.data?.agents ?? [];

  const workflowsQ = useAsyncData<WorkflowsResponse>(
    () => apiFetch("/api/workflows/active").then(r => parseJSON<WorkflowsResponse>(r, "/api/workflows/active")),
    [],
  );
  const workflowRuns = workflowsQ.data?.runs ?? [];

  const approvalsQ = useAsyncData<ApprovalsResponse>(
    () => apiFetch("/api/workflows/approvals/pending").then(r => parseJSON<ApprovalsResponse>(r, "/api/workflows/approvals/pending")),
    [],
  );
  const pendingApprovals = approvalsQ.data?.pending ?? [];

  const projectsQ = useAsyncData<Project[]>(
    () => apiFetch("/api/projects").then(r => parseJSON<Project[]>(r, "/api/projects")),
    [],
  );
  const projects = projectsQ.data ?? [];

  // ── Handlers ────────────────────────────────────────────────────────────
  function handleBuildApp() {
    if (prompt.trim().length > 3) sessionStorage.setItem("flow_builder_prompt", prompt.trim());
    setPage("app-builder");
  }

  const createProject = useCallback(async () => {
    if (newName.trim().length < 2) return;
    setSaving(true);
    try {
      const r = await apiFetch("/api/projects", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: newName.trim(), description: newDesc.trim() || null }),
      });
      if (!r.ok) throw new Error();
      setNewName(""); setNewDesc(""); setCreating(false);
      projectsQ.refetch();
      toast(t("toast.created"), "ok");
    } catch { toast(t("toast.createFailed"), "err"); }
    finally { setSaving(false); }
  }, [newName, newDesc, projectsQ, toast, t]);

  const deleteProject = useCallback(async (id: string, name: string) => {
    if (!confirm(t("card.deleteConfirm", { name }))) return;
    try {
      const r = await apiFetch(`/api/projects/${id}`, { method: "DELETE" });
      if (!r.ok) throw new Error();
      toast(t("toast.deleted", { name }), "ok");
    } catch { toast(t("toast.deleteFailed"), "err"); }
    finally { projectsQ.refetch(); }
  }, [projectsQ, toast, t]);

  // ── Derived ─────────────────────────────────────────────────────────────
  const runningAgents = agents.filter(a => a.live?.status === "running").length;
  const idleAgents    = agents.filter(a => a.live?.status !== "running").length;

  const kpis = [
    { label: "Projects",          value: stats?.projects ?? "—",       icon: <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/></svg>,                                     accent: true, sub: undefined,       onClick: () => setPage("app-builder") },
    { label: "Active Runs",       value: stats?.active_runs ?? "—",    icon: <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>,                                           accent: false, sub: "live",         onClick: () => setPage("runs") },
    { label: "Success Rate",      value: stats ? `${stats.success_rate}%` : "—", icon: <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><polyline points="20 6 9 17 4 12"/></svg>,                                                                    accent: false, sub: undefined,       onClick: undefined },
    { label: "AI Agents",         value: agents.length || (agentsQ.status === "loading" ? "…" : 0), icon: <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M4.22 4.22l2.12 2.12M17.66 17.66l2.12 2.12M2 12h3M19 12h3"/></svg>, accent: false, sub: `${runningAgents} running`, onClick: () => setPage("agentos") },
    { label: "Workflows",         value: workflowRuns.length || 0,     icon: <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><polyline points="9 11 12 14 22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>,      accent: false, sub: "active",       onClick: () => setPage("automation") },
    { label: "Pending Approvals", value: pendingApprovals.length || 0, icon: <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>,                                                          accent: pendingApprovals.length > 0, sub: undefined, onClick: () => setPage("automation") },
    { label: "Failed Runs",       value: stats?.failed_runs ?? "—",    icon: <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>,    accent: (stats?.failed_runs ?? 0) > 0, sub: undefined, onClick: () => setPage("runs") },
    { label: "Conversations",     value: stats?.conversations ?? "—",  icon: <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>,                                       accent: false, sub: undefined,       onClick: () => setPage("ai") },
  ];

  // ── Attention items ──────────────────────────────────────────────────────
  type AttentionDef = { severity: "critical" | "warning" | "info"; title: string; detail?: string; action?: string; onAction?: () => void };
  const attentionItems: AttentionDef[] = [];

  if ((stats?.failed_runs ?? 0) > 0) {
    const item = stats?.failed_run_items?.[0];
    attentionItems.push({
      severity: "critical",
      title: `${stats!.failed_runs} failed agent run${stats!.failed_runs > 1 ? "s" : ""}`,
      detail: item ? `Last: ${item.agent_type} in "${item.project_name}" — ${item.error.slice(0, 80)}` : undefined,
      action: "View Runs",
      onAction: () => setPage("runs"),
    });
  }
  if (pendingApprovals.length > 0) {
    attentionItems.push({
      severity: "warning",
      title: `${pendingApprovals.length} workflow${pendingApprovals.length > 1 ? "s" : ""} waiting for approval`,
      detail: "Human approval required to continue execution",
      action: "Review",
      onAction: () => setPage("automation"),
    });
  }

  const activity = stats?.recent_activity ?? [];
  const ideaChips = t("buildSection.ideas", { returnObjects: true }) as string[];

  // ── Quick Actions ────────────────────────────────────────────────────────
  const quickActions = [
    { label: "New Conversation",  desc: "Chat with AI assistants",               color: "#6E32E0", onClick: () => setPage("ai"),          icon: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg> },
    { label: "Build App with AI", desc: "AI Software Factory",                   color: "#2563EB", onClick: handleBuildApp,               icon: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg> },
    { label: "New Agent",         desc: "Deploy an AI agent",                    color: "#0B7A70", onClick: () => setPage("agentos"),     icon: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3"/></svg> },
    { label: "New Workflow",      desc: "Automate a business process",           color: "#A16207", onClick: () => setPage("automation"),  icon: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="9 11 12 14 22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg> },
    { label: "Design Studio",     desc: "Visual UI design canvas",               color: "#DC2626", onClick: () => setPage("design"),      icon: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="13.5" cy="6.5" r=".5" fill="currentColor"/><circle cx="17.5" cy="10.5" r=".5" fill="currentColor"/><circle cx="8.5" cy="7.5" r=".5" fill="currentColor"/><circle cx="6.5" cy="12.5" r=".5" fill="currentColor"/><path d="M12 2C6.5 2 2 6.5 2 12s4.5 10 10 10c.926 0 1.648-.746 1.648-1.688 0-.437-.18-.835-.437-1.125-.29-.289-.438-.652-.438-1.125a1.64 1.64 0 0 1 1.668-1.668h1.996c3.051 0 5.555-2.503 5.555-5.554C21.965 6.012 17.461 2 12 2z"/></svg> },
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      {/* ── Sub-header ─────────────────────────────────────────────── */}
      <div style={{
        padding: "0 24px", height: 48, minHeight: 48,
        borderBottom: "1px solid var(--b1)",
        display: "flex", alignItems: "center", justifyContent: "space-between",
        background: "var(--bg-surface)", flexShrink: 0,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: "var(--t1)" }}>Command Center</div>
          <span style={{ fontSize: 9, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--accent)", background: "var(--accent-dim)", padding: "2px 6px", borderRadius: 4 }}>
            LIVE
          </span>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button
            onClick={() => setCreating(true)}
            style={{ display: "flex", alignItems: "center", gap: 5, padding: "5px 12px", borderRadius: 7, border: "1px solid var(--b2)", background: "transparent", color: "var(--t2)", fontSize: 12, fontWeight: 500, cursor: "pointer" }}
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
            New Project
          </button>
          <button
            onClick={handleBuildApp}
            style={{ display: "flex", alignItems: "center", gap: 5, padding: "5px 14px", borderRadius: 7, border: "none", background: "linear-gradient(135deg, var(--accent) 0%, var(--teal) 100%)", color: "white", fontSize: 12, fontWeight: 600, cursor: "pointer", boxShadow: "0 2px 8px rgba(110,50,224,0.28)" }}
          >
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg>
            Build with AI
          </button>
        </div>
      </div>

      {/* ── Scrollable body ─────────────────────────────────────────── */}
      <div style={{ flex: 1, overflowY: "auto", padding: "20px 24px 40px" }}>

        {/* ── AI Build Hero ──────────────────────────────────────── */}
        <div className="dash-hero" style={{ marginBottom: 18 }}>
          <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: "0.12em", color: "var(--accent)", textTransform: "uppercase", marginBottom: 6 }}>
            ✦ AI SOFTWARE FACTORY
          </div>
          <div style={{ position: "relative" }}>
            <textarea
              ref={promptRef}
              value={prompt}
              onChange={e => setPrompt(e.target.value)}
              onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleBuildApp(); } }}
              placeholder={EXAMPLE_PROMPTS[promptIdx]}
              rows={2}
              style={{
                width: "100%", padding: "12px 110px 12px 14px",
                fontSize: 13, lineHeight: 1.6,
                background: "var(--bg-base)", border: "1px solid var(--b1)",
                borderRadius: 10, color: "var(--t1)", resize: "none", outline: "none",
                fontFamily: "inherit", boxSizing: "border-box", transition: "border-color 0.15s",
              }}
              onFocus={e => { e.target.style.borderColor = "var(--accent)"; e.target.style.boxShadow = "0 0 0 3px var(--accent-dim)"; }}
              onBlur={e => { e.target.style.borderColor = "var(--b1)"; e.target.style.boxShadow = "none"; }}
            />
            <button
              onClick={handleBuildApp}
              style={{
                position: "absolute", insetInlineEnd: 8, top: "50%", transform: "translateY(-50%)",
                padding: "6px 14px", borderRadius: 7, border: "none",
                background: prompt.trim().length > 2 ? "linear-gradient(135deg, var(--accent) 0%, var(--teal) 100%)" : "var(--bg-card)",
                color: prompt.trim().length > 2 ? "white" : "var(--t4)",
                fontSize: 12, fontWeight: 600, cursor: "pointer", transition: "all 0.15s",
              }}
            >
              Build →
            </button>
          </div>

          {/* Idea chips */}
          <div style={{ display: "flex", flexWrap: "wrap", gap: 5, marginTop: 8 }}>
            {(Array.isArray(ideaChips) ? ideaChips : []).map(idea => (
              <button
                key={idea}
                onClick={() => { setPrompt(idea); promptRef.current?.focus(); }}
                style={{ padding: "3px 10px", borderRadius: 99, fontSize: 11, fontWeight: 500, background: "var(--bg-card)", border: "1px solid var(--b1)", color: "var(--t3)", cursor: "pointer", transition: "all 0.12s" }}
                onMouseEnter={e => { const el = e.currentTarget as HTMLButtonElement; el.style.borderColor = "var(--ba)"; el.style.color = "var(--accent)"; el.style.background = "var(--accent-dim)"; }}
                onMouseLeave={e => { const el = e.currentTarget as HTMLButtonElement; el.style.borderColor = "var(--b1)"; el.style.color = "var(--t3)"; el.style.background = "var(--bg-card)"; }}
              >
                {idea}
              </button>
            ))}
          </div>
        </div>

        {/* ── KPI Strip — 8 metrics ──────────────────────────────── */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 10, marginBottom: 20 }}>
          {kpis.map((k, i) => (
            <KpiTile key={i} icon={k.icon} label={k.label} value={k.value} accent={k.accent} sub={k.sub} onClick={k.onClick} />
          ))}
        </div>

        {/* ── Main two-column layout ─────────────────────────────── */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 280px", gap: 16 }}>

          {/* ── LEFT COLUMN ─────────────────────────────────────── */}
          <div>

            {/* AI Workforce */}
            <div style={{ marginBottom: 20 }}>
              <SectionHeader
                title={`AI Workforce — ${runningAgents} running · ${idleAgents} idle`}
                action="Manage Agents"
                onAction={() => setPage("agentos")}
              />
              {agentsQ.status === "loading" ? (
                <div>{[1, 2, 3].map(i => <div key={i} className="skeleton" style={{ height: 46, borderRadius: 8, marginBottom: 6 }} />)}</div>
              ) : agents.length === 0 ? (
                <Card style={{ textAlign: "center", padding: "24px 16px" }}>
                  <div style={{ fontSize: 12, fontWeight: 600, color: "var(--t3)", marginBottom: 4 }}>No agents deployed</div>
                  <div style={{ fontSize: 11, color: "var(--t5)", marginBottom: 12 }}>Create your first AI agent to automate work</div>
                  <button
                    onClick={() => setPage("agentos")}
                    style={{ padding: "6px 14px", borderRadius: 7, border: "none", background: "var(--accent-dim)", color: "var(--accent)", fontSize: 12, fontWeight: 600, cursor: "pointer" }}
                  >
                    + New Agent
                  </button>
                </Card>
              ) : (
                agents.slice(0, 6).map(ag => (
                  <AgentRow key={ag.name} agent={ag} lang={lang} onNavigate={() => setPage("agentos")} />
                ))
              )}
            </div>

            {/* Needs Your Attention */}
            <div style={{ marginBottom: 20 }}>
              <SectionHeader title="Needs Your Attention" />
              {attentionItems.length === 0 && (statsQ.status !== "loading") ? (
                <Card>
                  <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "4px 0" }}>
                    <span style={{ fontSize: 18 }}>✓</span>
                    <div>
                      <div style={{ fontSize: 12, fontWeight: 700, color: "var(--t2)" }}>All systems operational</div>
                      <div style={{ fontSize: 11, color: "var(--t5)", marginTop: 2 }}>No issues requiring attention</div>
                    </div>
                  </div>
                </Card>
              ) : (
                <>
                  {attentionItems.map((item, i) => (
                    <AttentionItem key={i} {...item} />
                  ))}
                  {statsQ.status === "loading" && (
                    <div className="skeleton" style={{ height: 52, borderRadius: 8 }} />
                  )}
                </>
              )}
            </div>

            {/* Recent Work — unified activity timeline */}
            <div style={{ marginBottom: 20 }}>
              <SectionHeader title="Recent Work" />
              {statsQ.status === "loading" ? (
                <div>{[1, 2, 3, 4].map(i => <div key={i} className="skeleton" style={{ height: 38, borderRadius: 8, marginBottom: 6 }} />)}</div>
              ) : statsQ.status === "error" ? (
                <ErrorState message="Could not load activity" onRetry={statsQ.refetch} />
              ) : activity.length === 0 ? (
                <Card style={{ textAlign: "center", padding: "24px 16px" }}>
                  <div style={{ fontSize: 12, color: "var(--t4)" }}>No activity yet — start by building an app or running an agent</div>
                </Card>
              ) : (
                <Card style={{ padding: "4px 0" }}>
                  {activity.slice(0, 10).map((a, i) => {
                    const meta = ACTION_META[a.action] ?? { color: "var(--t4)", icon: null };
                    return (
                      <div
                        key={i}
                        className="dash-activity-item"
                        style={{ borderBottom: i < Math.min(activity.length, 10) - 1 ? "1px solid var(--b1)" : "none", padding: "8px 14px" }}
                      >
                        <div className="dash-activity-icon" style={{ background: meta.color + "1a", color: meta.color, width: 22, height: 22, borderRadius: 6, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                          {meta.icon}
                        </div>
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ fontSize: 12, fontWeight: 600, color: "var(--t2)", textTransform: "capitalize" }}>
                            {a.action.replace(/_/g, " ")}
                          </div>
                          {a.details.prompt_preview && (
                            <div style={{ fontSize: 11, color: "var(--t4)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                              "{a.details.prompt_preview}"
                            </div>
                          )}
                        </div>
                        <span style={{ fontSize: 10, color: "var(--t5)", flexShrink: 0 }}>{relTime(a.time, lang)}</span>
                      </div>
                    );
                  })}
                </Card>
              )}
            </div>

            {/* Projects grid */}
            <div>
              <SectionHeader
                title={`Projects — ${projects.length}`}
                action="App Builder"
                onAction={() => setPage("app-builder")}
              />
              <AnimatePresence>
                {creating && (
                  <motion.div
                    initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }}
                    style={{ background: "var(--bg-surface)", border: "1px solid var(--accent-border)", borderRadius: 10, padding: 16, marginBottom: 12, boxShadow: "0 0 0 3px var(--accent-dim)" }}
                  >
                    <div style={{ fontSize: 12, fontWeight: 700, color: "var(--t1)", marginBottom: 10 }}>Create Project</div>
                    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                      <input value={newName} onChange={e => setNewName(e.target.value)} placeholder="Project name" autoFocus
                        style={{ padding: "8px 12px", fontSize: 13, borderRadius: 7, border: "1px solid var(--b1)", background: "var(--bg-card)", color: "var(--t1)", outline: "none" }}
                        onKeyDown={e => e.key === "Enter" && createProject()}
                      />
                      <textarea value={newDesc} onChange={e => setNewDesc(e.target.value)} placeholder="Description (optional)"
                        style={{ padding: "8px 12px", fontSize: 12, borderRadius: 7, border: "1px solid var(--b1)", background: "var(--bg-card)", color: "var(--t1)", outline: "none", resize: "vertical", minHeight: 48, fontFamily: "inherit" }}
                      />
                      <div style={{ display: "flex", gap: 8 }}>
                        <button onClick={createProject} disabled={saving || newName.trim().length < 2}
                          style={{ padding: "6px 14px", borderRadius: 7, border: "none", background: "var(--accent)", color: "white", fontSize: 12, fontWeight: 600, cursor: "pointer", opacity: (saving || newName.trim().length < 2) ? 0.5 : 1 }}>
                          {saving ? "Creating…" : "Create"}
                        </button>
                        <button onClick={() => { setCreating(false); setNewName(""); setNewDesc(""); }}
                          style={{ padding: "6px 12px", borderRadius: 7, border: "1px solid var(--b1)", background: "transparent", color: "var(--t3)", fontSize: 12, cursor: "pointer" }}>
                          Cancel
                        </button>
                      </div>
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>

              {projectsQ.status === "loading" ? (
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: 10 }}>
                  {[1, 2, 3].map(i => <div key={i} className="skeleton" style={{ height: 90, borderRadius: 10 }} />)}
                </div>
              ) : projects.length === 0 ? (
                <Card style={{ textAlign: "center", padding: "28px 16px" }}>
                  <div style={{ fontSize: 12, fontWeight: 600, color: "var(--t3)", marginBottom: 4 }}>No projects yet</div>
                  <div style={{ fontSize: 11, color: "var(--t5)", marginBottom: 12 }}>Use AI to generate a full-stack app in seconds</div>
                  <button onClick={handleBuildApp}
                    style={{ padding: "6px 16px", borderRadius: 7, border: "none", background: "linear-gradient(135deg, var(--accent) 0%, var(--teal) 100%)", color: "white", fontSize: 12, fontWeight: 600, cursor: "pointer" }}>
                    Build with AI
                  </button>
                </Card>
              ) : (
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: 10 }}>
                  {projects.slice(0, 6).map(p => (
                    <Card
                      key={p.id}
                      onClick={() => { sessionStorage.setItem("flow_active_project", p.id); setPage("app-builder"); }}
                      style={{ display: "flex", flexDirection: "column", gap: 8 }}
                    >
                      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                        <div style={{ width: 28, height: 28, borderRadius: 8, background: "var(--accent-dim)", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--accent)", fontSize: 13, fontWeight: 800 }}>
                          {p.name.charAt(0).toUpperCase()}
                        </div>
                        <button
                          onClick={e => { e.stopPropagation(); void deleteProject(p.id, p.name); }}
                          style={{ background: "none", border: "none", cursor: "pointer", color: "var(--t5)", padding: 3, borderRadius: 5, display: "flex", transition: "color 0.12s" }}
                          onMouseEnter={e => (e.currentTarget.style.color = "var(--red)")}
                          onMouseLeave={e => (e.currentTarget.style.color = "var(--t5)")}
                        >
                          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/></svg>
                        </button>
                      </div>
                      <div style={{ fontSize: 12, fontWeight: 700, color: "var(--t1)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{p.name}</div>
                      <div style={{ fontSize: 10, color: "var(--t5)" }}>{relTime(p.created_at, lang)}</div>
                    </Card>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* ── RIGHT COLUMN ────────────────────────────────────── */}
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>

            {/* Quick Actions */}
            <div>
              <SectionHeader title="Quick Actions" />
              {quickActions.map(a => (
                <QuickAction key={a.label} {...a} />
              ))}
            </div>

            {/* Active Workflows */}
            <div>
              <SectionHeader title="Active Workflows" action="View All" onAction={() => setPage("automation")} />
              {workflowsQ.status === "loading" ? (
                <div>{[1, 2].map(i => <div key={i} className="skeleton" style={{ height: 38, borderRadius: 8, marginBottom: 6 }} />)}</div>
              ) : workflowRuns.length === 0 ? (
                <Card style={{ textAlign: "center", padding: "16px" }}>
                  <div style={{ fontSize: 11, color: "var(--t5)" }}>No active workflows</div>
                </Card>
              ) : (
                workflowRuns.slice(0, 4).map(run => {
                  const c = run.status === "completed" ? "var(--green)" : run.status === "running" ? "var(--accent)" : run.status === "failed" ? "var(--red)" : "var(--t5)";
                  return (
                    <Card key={run.id} style={{ padding: "9px 12px", marginBottom: 6, display: "flex", alignItems: "center", gap: 8 }}>
                      <Dot color={c} pulse={run.status === "running"} />
                      <span style={{ fontSize: 12, fontWeight: 600, color: "var(--t1)", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{run.name}</span>
                      <span style={{ fontSize: 10, color: c, fontWeight: 600, flexShrink: 0 }}>{run.status}</span>
                    </Card>
                  );
                })
              )}
            </div>

            {/* Platform Nav */}
            <div>
              <SectionHeader title="Platform" />
              {[
                { label: "AI Gateway",   sub: "Models · Budgets · Usage",   page: "ai-routing" as const,    color: "#6E32E0" },
                { label: "Observability",sub: "Metrics · Alerts · Logs",     page: "observability" as const, color: "#0B7A70" },
                { label: "Integrations", sub: "Connect external services",   page: "integrations" as const,  color: "#2563EB" },
                { label: "Marketplace",  sub: "Templates & packages",        page: "marketplace" as const,   color: "#A16207" },
              ].map(item => (
                <button
                  key={item.label}
                  onClick={() => setPage(item.page)}
                  className="dash-qnav"
                  style={{ display: "flex", alignItems: "center", gap: 10, width: "100%", padding: "8px 10px", borderRadius: 8, background: "var(--bg-card)", border: "1px solid var(--b1)", cursor: "pointer", textAlign: "left", marginBottom: 5, transition: "border-color 0.12s" }}
                  onMouseEnter={e => (e.currentTarget.style.borderColor = item.color)}
                  onMouseLeave={e => (e.currentTarget.style.borderColor = "var(--b1)")}
                >
                  <div style={{ width: 28, height: 28, borderRadius: 8, background: item.color + "15", color: item.color, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="9 18 15 12 9 6"/></svg>
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 12, fontWeight: 700, color: "var(--t1)" }}>{item.label}</div>
                    <div style={{ fontSize: 10, color: "var(--t4)", marginTop: 1 }}>{item.sub}</div>
                  </div>
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* ping animation */}
      <style>{`@keyframes ping { 75%, 100% { transform: scale(1.8); opacity: 0; } }`}</style>
    </div>
  );
}
