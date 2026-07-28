/**
 * AutomationPage — task management and workflow automation hub.
 * Merges Tasks + Automation views into a single workspace.
 * Data: /api/tasks, /api/agents, /workflows/*
 */
import { useState, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { motion } from "framer-motion";
import { useToast } from "../../contexts/toast";
import { apiFetch, parseJSON, authH } from "../../utils/api";
import { relTime } from "../../utils/time";
import { S, C } from "../../styles/theme";
import { GoldButton, GlassCard } from "../../shared/ui/gold";
import type { Task, Agent } from "../../types";

type AutoTab = "tasks" | "workflows";
type TaskStatus = Task["status"];
type TaskPriority = Task["priority"];

const STATUS_COLOR: Record<TaskStatus, string> = {
  pending:     C.gray,
  in_progress: C.blue,
  done:        C.green,
};

const PRIORITY_DOT: Record<TaskPriority, string> = {
  low:    C.gray,
  medium: C.amber,
  high:   C.red,
};

function TaskCard({ task, onStatusChange, onDelete }: {
  task: Task;
  onStatusChange: (id: string, status: TaskStatus) => void;
  onDelete: (id: string) => void;
}) {
  const { t } = useTranslation("automation");
  const STATUS_LABEL: Record<TaskStatus, string> = {
    pending:     t("status.pending"),
    in_progress: t("status.in_progress"),
    done:        t("status.done"),
  };
  return (
    <GlassCard style={{ padding: "14px 18px", display: "flex", gap: 12, alignItems: "flex-start" }}>
      <button
        onClick={() => onStatusChange(task.id, task.status === "done" ? "pending" : "done")}
        style={{ background: "none", border: "none", cursor: "pointer", padding: 0, marginTop: 2, color: task.status === "done" ? C.green : "rgba(255,255,255,0.2)", flexShrink: 0 }}
        aria-label={task.status === "done" ? t("taskCard.markPending") : t("taskCard.markDone")}
      >
        {task.status === "done"
          ? <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="20 6 9 17 4 12"/></svg>
          : <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="9"/></svg>}
      </button>

      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
          <span style={{ fontSize: 13, fontWeight: 500, color: task.status === "done" ? "var(--t4)" : "var(--t1)", textDecoration: task.status === "done" ? "line-through" : "none", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {task.title}
          </span>
          <span style={{ width: 6, height: 6, borderRadius: "50%", background: PRIORITY_DOT[task.priority], flexShrink: 0 }} title={task.priority} />
        </div>
        {task.notes && (
          <p style={{ fontSize: 12, color: "var(--t4)", margin: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{task.notes}</p>
        )}
        <div style={{ display: "flex", gap: 10, marginTop: 6, alignItems: "center" }}>
          <span style={{ fontSize: 10, fontWeight: 600, padding: "2px 8px", borderRadius: 20, background: STATUS_COLOR[task.status] + "1a", color: STATUS_COLOR[task.status], border: `1px solid ${STATUS_COLOR[task.status]}33` }}>
            {STATUS_LABEL[task.status]}
          </span>
          {task.due_date && (
            <span style={{ fontSize: 11, color: "var(--t5)" }}>{t("taskCard.due", { date: relTime(task.due_date) })}</span>
          )}
          {task.category && (
            <span style={{ fontSize: 11, color: "var(--accent-2)", background: "var(--accent-dim)", padding: "1px 7px", borderRadius: 99 }}>{task.category}</span>
          )}
        </div>
      </div>

      <div style={{ display: "flex", gap: 2, flexShrink: 0 }}>
        {task.status !== "in_progress" && task.status !== "done" && (
          <button
            onClick={() => onStatusChange(task.id, "in_progress")}
            className="btn-icon" title={t("taskCard.start")} style={{ width: 28, height: 28 }}
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polygon points="5 3 19 12 5 21 5 3"/></svg>
          </button>
        )}
        <button onClick={() => onDelete(task.id)} className="btn-icon" title={t("taskCard.delete")} style={{ width: 28, height: 28, color: C.redSoft }}>
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/></svg>
        </button>
      </div>
    </GlassCard>
  );
}

export function AutomationPage() {
  const { t } = useTranslation("automation");
  const toast = useToast();
  const [tab, setTab]         = useState<AutoTab>("tasks");
  const [tasks, setTasks]     = useState<Task[]>([]);
  const [, setAgents]         = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter]   = useState<TaskStatus | "all">("all");
  const [search, setSearch]   = useState("");
  const [creating, setCreating] = useState(false);
  const [newTitle, setNewTitle]   = useState("");
  const [newPriority, setNewPriority] = useState<TaskPriority>("medium");
  const [saving, setSaving]   = useState(false);

  // ── Workflow state ──────────────────────────────────────────────────────────
  type WfRun = { run_id: string; workflow_id: string; status: string; start_time: number; steps_total: number; steps_done: number; error?: string };
  const [wfRuns, setWfRuns]         = useState<WfRun[]>([]);
  const [wfLoading, setWfLoading]   = useState(false);
  const [runningDemo, setRunningDemo] = useState<string | null>(null);

  const loadTasks = useCallback(async () => {
    setLoading(true);
    try {
      const r = await apiFetch("/api/tasks?sort=created_at&limit=100");
      const d = await parseJSON<{ tasks?: Task[] }>(r, "/api/tasks");
      setTasks(d.tasks ?? []);
    } catch { toast(t("toast.loadTasksFailed"), "err"); }
    finally { setLoading(false); }
  }, [toast, t]);

  const loadWorkflows = useCallback(async () => {
    setWfLoading(true);
    try {
      const r = await apiFetch("/api/workflows/active");
      if (r.ok) { const d = await r.json(); setWfRuns(d.runs ?? []); }
    } catch {}
    finally { setWfLoading(false); }
  }, []);

  const runDemoWorkflow = async (kind: string) => {
    setRunningDemo(kind);
    try {
      const r = await apiFetch("/api/workflows/demo", { method: "POST", body: JSON.stringify({ kind }) });
      if (!r.ok) throw new Error();
      const d = await r.json();
      toast(t("toast.workflowStarted", { runId: d.run_id }), "ok");
      setTimeout(loadWorkflows, 800);
    } catch { toast(t("toast.workflowStartFailed"), "err"); }
    finally { setRunningDemo(null); }
  };

  useEffect(() => {
    void Promise.resolve().then(loadTasks);
    void Promise.resolve().then(loadWorkflows);
    apiFetch("/api/agents")
      .then(r => parseJSON<Agent[]>(r, "/api/agents"))
      .then(setAgents)
      .catch(() => {});
  }, [loadTasks, loadWorkflows]);

  async function createTask() {
    if (!newTitle.trim()) return;
    setSaving(true);
    try {
      const r = await apiFetch("/api/tasks", {
        method: "POST", headers: authH(),
        body: JSON.stringify({ title: newTitle.trim(), priority: newPriority }),
      });
      if (!r.ok) throw new Error();
      setNewTitle(""); setCreating(false); loadTasks(); toast(t("toast.taskCreated"));
    } catch { toast(t("toast.createTaskFailed"), "err"); }
    finally { setSaving(false); }
  }

  async function updateStatus(id: string, status: TaskStatus) {
    setTasks(prev => prev.map(t => t.id === id ? { ...t, status } : t));
    try {
      await apiFetch(`/api/tasks/${id}`, {
        method: "PUT", headers: authH(),
        body: JSON.stringify({ status }),
      });
    } catch { loadTasks(); }
  }

  async function deleteTask(id: string) {
    setTasks(prev => prev.filter(t => t.id !== id));
    try { await apiFetch(`/api/tasks/${id}`, { method: "DELETE" }); }
    catch { loadTasks(); }
  }

  const filtered = tasks
    .filter(t => filter === "all" || t.status === filter)
    .filter(t => !search || t.title.toLowerCase().includes(search.toLowerCase()));

  const counts: Record<string, number> = {
    all:         tasks.length,
    pending:     tasks.filter(t => t.status === "pending").length,
    in_progress: tasks.filter(t => t.status === "in_progress").length,
    done:        tasks.filter(t => t.status === "done").length,
  };

  const TABS: [AutoTab, string][] = [["tasks", t("tabs.tasks")], ["workflows", t("tabs.workflows")]];
  const FILTERS: [TaskStatus | "all", string][] = [
    ["all", t("filters.all", { count: counts.all })],
    ["pending", t("filters.pending", { count: counts.pending })],
    ["in_progress", t("filters.active", { count: counts.in_progress })],
    ["done", t("filters.done", { count: counts.done })],
  ];

  return (
    <>
      <header style={S.header}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <span style={S.headerTitle}>{t("header.title")}</span>
          <div style={{ display: "flex", gap: 4, background: "var(--bg-card)", borderRadius: 12, padding: 4 }}>
            {TABS.map(([id, label]) => (
              <button key={id} onClick={() => setTab(id)} role="tab" aria-selected={tab === id} style={{
                padding: "6px 16px", borderRadius: 9, border: "none", cursor: "pointer",
                fontSize: 13, fontWeight: 500, transition: "all .18s",
                background: tab === id ? "linear-gradient(135deg,var(--accent),var(--teal))" : "transparent",
                color:      tab === id ? "#fff" : "var(--t4)",
                boxShadow:  tab === id ? "0 2px 12px rgba(110,50,224,.35)" : "none",
              }}>{label}</button>
            ))}
          </div>
        </div>
        {tab === "tasks" && (
          <GoldButton onClick={() => setCreating(c => !c)}>{t("header.newTask")}</GoldButton>
        )}
      </header>

      {/* ── Tasks tab ─────────────────────────────────────────────────────────── */}
      {tab === "tasks" && (
        <div style={{ flex: 1, overflowY: "auto", padding: 24 }}>
          {/* New task form */}
          {creating && (
            <GlassCard style={{ marginBottom: 20, animation: "slideUp .2s ease" }}>
              <div style={{ ...S.cardTitle, marginBottom: 12 }}>{t("newTaskForm.title")}</div>
              <div style={{ display: "flex", gap: 10, marginBottom: 10 }}>
                <input
                  value={newTitle} onChange={e => setNewTitle(e.target.value)}
                  onKeyDown={e => e.key === "Enter" && void createTask()}
                  placeholder={t("newTaskForm.titlePlaceholder")} style={{ ...S.textInput, flex: 1 }} autoFocus
                />
                <select value={newPriority} onChange={e => setNewPriority(e.target.value as TaskPriority)} style={{ ...S.textInput, width: "auto" }}>
                  <option value="low">{t("newTaskForm.priorityLow")}</option>
                  <option value="medium">{t("newTaskForm.priorityMedium")}</option>
                  <option value="high">{t("newTaskForm.priorityHigh")}</option>
                </select>
              </div>
              <div style={{ display: "flex", gap: 8 }}>
                <GoldButton onClick={() => void createTask()} disabled={saving || !newTitle.trim()}>{saving ? t("newTaskForm.creating") : t("newTaskForm.create")}</GoldButton>
                <GoldButton variant="ghost" onClick={() => { setCreating(false); setNewTitle(""); }}>{t("common:actions.cancel")}</GoldButton>
              </div>
            </GlassCard>
          )}

          {/* Filter bar */}
          <div style={{ display: "flex", gap: 8, marginBottom: 16, flexWrap: "wrap", alignItems: "center" }}>
            <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
              {FILTERS.map(([id, label]) => (
                <button key={id} onClick={() => setFilter(id)} style={{
                  padding: "6px 14px", borderRadius: 20, border: "none", cursor: "pointer", fontSize: 12, fontWeight: 500,
                  background: filter === id ? "var(--accent-dim)" : "var(--bg-card)",
                  color: filter === id ? "var(--accent-2)" : "var(--t4)",
                  transition: "all .15s",
                }}>{label}</button>
              ))}
            </div>
            <div style={{ position: "relative", display: "flex", alignItems: "center", flex: 1, maxWidth: 220, marginLeft: "auto" }}>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ position: "absolute", left: 10, color: "var(--t4)", pointerEvents: "none" }}><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
              <input value={search} onChange={e => setSearch(e.target.value)} placeholder={t("toolbar.searchPlaceholder")} style={{ ...S.textInput, paddingLeft: 30, fontSize: 12 }} />
            </div>
          </div>

          {/* Task list */}
          {loading ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {[1,2,3,4].map(i => <div key={i} className="skeleton" style={{ height: 72, borderRadius: 12 }} />)}
            </div>
          ) : filtered.length === 0 ? (
            <div className="empty-state">
              <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.2" style={{ color: "var(--ta)" }}>
                <polyline points="9 11 12 14 22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>
              </svg>
              <h3>{filter !== "all" ? t("emptyTasks.titleFiltered", { status: filter }) : t("emptyTasks.titleDefault")}</h3>
              <p>{t("emptyTasks.description")}</p>
              <GoldButton onClick={() => setCreating(true)}>{t("header.newTask")}</GoldButton>
            </div>
          ) : (
            <motion.div
              style={{ display: "flex", flexDirection: "column", gap: 8 }}
              initial="hidden" animate="show"
              variants={{ show: { transition: { staggerChildren: 0.03 } } }}
            >
              {filtered.map(t => (
                <motion.div key={t.id} variants={{ hidden: { opacity: 0, y: 8 }, show: { opacity: 1, y: 0 } }}>
                  <TaskCard task={t} onStatusChange={updateStatus} onDelete={deleteTask} />
                </motion.div>
              ))}
            </motion.div>
          )}
        </div>
      )}

      {/* ── Workflows tab ─────────────────────────────────────────────────────── */}
      {tab === "workflows" && (
        <div style={{ flex: 1, overflowY: "auto", padding: 24, display: "flex", flexDirection: "column", gap: 20 }}>

          {/* Active runs */}
          <GlassCard lift={false}>
            <div style={{ ...S.cardTitle, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <span>{t("workflows.activeRuns")}</span>
              <GoldButton variant="ghost" onClick={loadWorkflows} disabled={wfLoading}>
                {wfLoading ? "…" : t("workflows.refresh")}
              </GoldButton>
            </div>
            <div style={{ padding: "0 0 4px" }}>
              {wfLoading ? (
                <div style={{ padding: "16px 18px" }}><div className="skeleton" style={{ height: 40, borderRadius: 8 }} /></div>
              ) : wfRuns.length === 0 ? (
                <div style={{ padding: "16px 18px", color: "var(--t4)", fontSize: 13 }}>{t("workflows.empty")}</div>
              ) : wfRuns.map(run => {
                const pct = run.steps_total > 0 ? Math.round((run.steps_done / run.steps_total) * 100) : 0;
                const running = run.status === "running";
                const statusColor: Record<string, string> = { running: "var(--accent-2)", completed: C.green, failed: C.red, pending: C.amber };
                const color = statusColor[run.status] ?? "var(--t4)";
                const statusLabel = t(`workflows.status.${run.status}`, { defaultValue: run.status });
                return (
                  <div key={run.run_id} style={{ padding: "12px 18px", borderTop: "1px solid var(--border)", display: "flex", flexDirection: "column", gap: 8 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                      <span style={{ fontSize: 12, fontWeight: 600, color: "var(--t1)", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {run.workflow_id}
                      </span>
                      <span style={{ display: "inline-flex", alignItems: "center", gap: 5, fontSize: 11, fontWeight: 700, color, background: color + "18", border: `1px solid ${color}33`, padding: "2px 8px", borderRadius: 99 }}>
                        {running && (
                          <motion.span
                            style={{ width: 6, height: 6, borderRadius: "50%", background: color, display: "inline-block" }}
                            animate={{ opacity: [1, 0.3, 1] }}
                            transition={{ duration: 1.2, repeat: Infinity, ease: "easeInOut" }}
                          />
                        )}
                        {statusLabel}
                      </span>
                      <span style={{ fontSize: 11, color: "var(--t4)" }}>
                        {t("workflows.stepsProgress", { done: run.steps_done, total: run.steps_total })}
                      </span>
                    </div>
                    <div style={{ height: 4, background: "var(--bg-base)", borderRadius: 99, overflow: "hidden" }}>
                      <div style={{ height: "100%", width: `${pct}%`, background: color, borderRadius: 99, transition: "width .4s" }} />
                    </div>
                    {run.error && <div style={{ fontSize: 11, color: C.red }}>{run.error}</div>}
                  </div>
                );
              })}
            </div>
          </GlassCard>

          {/* Workflow templates → run via real API */}
          <div>
            <div className="section-label" style={{ marginBottom: 12 }}>{t("workflows.templatesLabel")}</div>
            <motion.div
              style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(260px,1fr))", gap: 12 }}
              initial="hidden" animate="show"
              variants={{ show: { transition: { staggerChildren: 0.05 } } }}
            >
              {([
                { kind: "sequential", name: t("workflows.templates.sequential.name"), desc: t("workflows.templates.sequential.desc"), icon: "📋" },
                { kind: "parallel",   name: t("workflows.templates.parallel.name"),   desc: t("workflows.templates.parallel.desc"),   icon: "⚡" },
                { kind: "approval",   name: t("workflows.templates.approval.name"),   desc: t("workflows.templates.approval.desc"),   icon: "👤" },
                { kind: "saga",       name: t("workflows.templates.saga.name"),       desc: t("workflows.templates.saga.desc"),       icon: "🔄" },
              ] as const).map(wf => (
                <motion.div key={wf.kind} variants={{ hidden: { opacity: 0, y: 10 }, show: { opacity: 1, y: 0 } }}>
                  <GlassCard style={{ cursor: runningDemo ? "wait" : "default" }}>
                    <div style={{ display: "flex", gap: 12, alignItems: "flex-start", marginBottom: 10 }}>
                      <div style={{ fontSize: 24, lineHeight: 1 }}>{wf.icon}</div>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: 13, fontWeight: 600, color: "var(--t1)" }}>{wf.name}</div>
                        <div style={{ fontSize: 11, color: "var(--t4)", marginTop: 3, lineHeight: 1.5 }}>{wf.desc}</div>
                      </div>
                    </div>
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                      <span style={{ fontSize: 10, color: "var(--accent-2)", fontWeight: 500, background: "var(--accent-dim)", border: "1px solid var(--accent-border)", borderRadius: 20, padding: "2px 8px" }}>
                        {t("workflows.trigger")}
                      </span>
                      <GoldButton onClick={() => runDemoWorkflow(wf.kind)} disabled={!!runningDemo}>
                        {runningDemo === wf.kind ? t("workflows.starting") : t("workflows.run")}
                      </GoldButton>
                    </div>
                  </GlassCard>
                </motion.div>
              ))}
            </motion.div>
          </div>

          {/* Pending approvals */}
          <GlassCard lift={false}>
            <div style={S.cardTitle}>{t("approvals.title")}</div>
            <ApprovalsList />
          </GlassCard>
        </div>
      )}
    </>
  );
}

function ApprovalsList() {
  type Approval = { run_id: string; step_id: string; step_name: string; requested_at: number };
  const { t } = useTranslation("automation");
  const toast = useToast();
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await apiFetch("/api/workflows/approvals/pending");
      if (r.ok) { const d = await r.json(); setApprovals(d.approvals ?? []); }
    } catch {}
  }, []);

  useEffect(() => { void Promise.resolve().then(load); }, [load]);

  const decide = async (run_id: string, step_id: string, action: "approve" | "reject") => {
    setBusy(`${run_id}:${step_id}`);
    try {
      const r = await apiFetch(`/api/workflows/approvals/${run_id}/${step_id}/${action}`, { method: "POST" });
      if (!r.ok) throw new Error();
      toast(action === "approve" ? t("approvals.toast.approved") : t("approvals.toast.rejected"), "ok");
      setApprovals(p => p.filter(a => !(a.run_id === run_id && a.step_id === step_id)));
    } catch { toast(action === "approve" ? t("approvals.toast.approveFailed") : t("approvals.toast.rejectFailed"), "err"); }
    finally { setBusy(null); }
  };

  if (approvals.length === 0) return (
    <div style={{ padding: "12px 18px", color: "var(--t4)", fontSize: 13 }}>{t("approvals.empty")}</div>
  );

  return (
    <div>
      {approvals.map(a => (
        <div key={`${a.run_id}:${a.step_id}`} style={{ padding: "12px 18px", borderTop: "1px solid var(--border)", display: "flex", alignItems: "center", gap: 12 }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: "var(--t1)" }}>{a.step_name}</div>
            <div style={{ fontSize: 11, color: "var(--t4)" }}>{t("approvals.runId", { id: a.run_id.slice(0, 8) })}</div>
          </div>
          <button
            onClick={() => decide(a.run_id, a.step_id, "approve")}
            disabled={!!busy}
            style={{ padding: "5px 14px", borderRadius: 8, border: "none", cursor: "pointer", fontSize: 12, fontWeight: 600, background: C.greenBright, color: "#fff" }}
          >{t("approvals.approve")}</button>
          <button
            onClick={() => decide(a.run_id, a.step_id, "reject")}
            disabled={!!busy}
            style={{ padding: "5px 14px", borderRadius: 8, border: "none", cursor: "pointer", fontSize: 12, fontWeight: 600, background: C.red, color: "#fff" }}
          >{t("approvals.reject")}</button>
        </div>
      ))}
    </div>
  );
}
