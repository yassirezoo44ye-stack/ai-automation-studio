/**
 * AutomationPage — task management and workflow automation hub.
 * Merges Tasks + Automation views into a single workspace.
 * Data: /api/tasks, /api/agents, /workflows/*
 */
import { useState, useEffect, useCallback } from "react";
import { useToast } from "../../contexts/ToastContext";
import { apiFetch, parseJSON, authH } from "../../utils/api";
import { relTime } from "../../utils/time";
import { S } from "../../styles/theme";
import type { Task, Agent } from "../../types";

type AutoTab = "tasks" | "workflows";
type TaskStatus = Task["status"];
type TaskPriority = Task["priority"];

const STATUS_COLOR: Record<TaskStatus, string> = {
  pending:     "#8F8F8F",
  in_progress: "#E8C87D",
  done:        "#00C853",
};

const PRIORITY_DOT: Record<TaskPriority, string> = {
  low:    "#8F8F8F",
  medium: "#FFB300",
  high:   "#FF5252",
};

const STATUS_LABEL: Record<TaskStatus, string> = {
  pending:     "Pending",
  in_progress: "In Progress",
  done:        "Done",
};

function TaskCard({ task, onStatusChange, onDelete }: {
  task: Task;
  onStatusChange: (id: string, status: TaskStatus) => void;
  onDelete: (id: string) => void;
}) {
  return (
    <div style={{ ...S.card, padding: "14px 18px", display: "flex", gap: 12, alignItems: "flex-start" }}>
      <button
        onClick={() => onStatusChange(task.id, task.status === "done" ? "pending" : "done")}
        style={{ background: "none", border: "none", cursor: "pointer", padding: 0, marginTop: 2, color: task.status === "done" ? "#00C853" : "rgba(255,255,255,0.2)", flexShrink: 0 }}
        aria-label={task.status === "done" ? "Mark pending" : "Mark done"}
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
            <span style={{ fontSize: 11, color: "var(--t5)" }}>Due {relTime(task.due_date)}</span>
          )}
          {task.category && (
            <span style={{ fontSize: 11, color: "var(--ta)", background: "rgba(232,200,125,.08)", padding: "1px 7px", borderRadius: 99 }}>{task.category}</span>
          )}
        </div>
      </div>

      <div style={{ display: "flex", gap: 2, flexShrink: 0 }}>
        {task.status !== "in_progress" && task.status !== "done" && (
          <button
            onClick={() => onStatusChange(task.id, "in_progress")}
            className="btn-icon" title="Start" style={{ width: 28, height: 28 }}
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polygon points="5 3 19 12 5 21 5 3"/></svg>
          </button>
        )}
        <button onClick={() => onDelete(task.id)} className="btn-icon" title="Delete" style={{ width: 28, height: 28, color: "#FF5252" }}>
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/></svg>
        </button>
      </div>
    </div>
  );
}

export function AutomationPage() {
  const toast = useToast();
  const [tab, setTab]         = useState<AutoTab>("tasks");
  const [tasks, setTasks]     = useState<Task[]>([]);
  const [agents, setAgents]   = useState<Agent[]>([]);
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
    } catch { toast("Could not load tasks", "err"); }
    finally { setLoading(false); }
  }, []);

  const loadWorkflows = useCallback(async () => {
    setWfLoading(true);
    try {
      const r = await apiFetch("/workflows/active");
      if (r.ok) { const d = await r.json(); setWfRuns(d.runs ?? []); }
    } catch {}
    finally { setWfLoading(false); }
  }, []);

  const runDemoWorkflow = async (kind: string) => {
    setRunningDemo(kind);
    try {
      const r = await apiFetch("/workflows/demo", { method: "POST", body: JSON.stringify({ kind }) });
      if (!r.ok) throw new Error();
      const d = await r.json();
      toast(`Workflow started — run_id: ${d.run_id}`, "ok");
      setTimeout(loadWorkflows, 800);
    } catch { toast("Failed to start workflow", "err"); }
    finally { setRunningDemo(null); }
  };

  useEffect(() => {
    loadTasks();
    loadWorkflows();
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
      setNewTitle(""); setCreating(false); loadTasks(); toast("Task created");
    } catch { toast("Failed to create task", "err"); }
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

  const TABS: [AutoTab, string][] = [["tasks", "Tasks"], ["workflows", "Workflows"]];
  const FILTERS: [TaskStatus | "all", string][] = [
    ["all", `All (${counts.all})`],
    ["pending", `Pending (${counts.pending})`],
    ["in_progress", `Active (${counts.in_progress})`],
    ["done", `Done (${counts.done})`],
  ];

  return (
    <>
      <header style={S.header}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <span style={S.headerTitle}>Automation</span>
          <div style={{ display: "flex", gap: 4, background: "rgba(255,255,255,.04)", borderRadius: 12, padding: 4 }}>
            {TABS.map(([id, label]) => (
              <button key={id} onClick={() => setTab(id)} role="tab" aria-selected={tab === id} style={{
                padding: "6px 16px", borderRadius: 9, border: "none", cursor: "pointer",
                fontSize: 13, fontWeight: 500, transition: "all .18s",
                background: tab === id ? "linear-gradient(135deg,#FFD700,#D4AF37)" : "transparent",
                color:      tab === id ? "#fff" : "rgba(189,189,189,.6)",
                boxShadow:  tab === id ? "0 2px 12px rgba(255,215,0,.35)" : "none",
              }}>{label}</button>
            ))}
          </div>
        </div>
        {tab === "tasks" && (
          <button onClick={() => setCreating(c => !c)} style={S.btnPrimary}>+ New Task</button>
        )}
      </header>

      {/* ── Tasks tab ─────────────────────────────────────────────────────────── */}
      {tab === "tasks" && (
        <div style={{ flex: 1, overflowY: "auto", padding: 24 }}>
          {/* New task form */}
          {creating && (
            <div style={{ ...S.card, marginBottom: 20, animation: "slideUp .2s ease" }}>
              <div style={{ ...S.cardTitle, marginBottom: 12 }}>New Task</div>
              <div style={{ display: "flex", gap: 10, marginBottom: 10 }}>
                <input
                  value={newTitle} onChange={e => setNewTitle(e.target.value)}
                  onKeyDown={e => e.key === "Enter" && void createTask()}
                  placeholder="Task title *" style={{ ...S.textInput, flex: 1 }} autoFocus
                />
                <select value={newPriority} onChange={e => setNewPriority(e.target.value as TaskPriority)} style={{ ...S.textInput, width: "auto" }}>
                  <option value="low">Low</option>
                  <option value="medium">Medium</option>
                  <option value="high">High</option>
                </select>
              </div>
              <div style={{ display: "flex", gap: 8 }}>
                <button onClick={() => void createTask()} disabled={saving || !newTitle.trim()} style={S.btnPrimary}>{saving ? "Creating…" : "Create Task"}</button>
                <button onClick={() => { setCreating(false); setNewTitle(""); }} style={S.btnSecondary}>Cancel</button>
              </div>
            </div>
          )}

          {/* Filter bar */}
          <div style={{ display: "flex", gap: 8, marginBottom: 16, flexWrap: "wrap", alignItems: "center" }}>
            <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
              {FILTERS.map(([id, label]) => (
                <button key={id} onClick={() => setFilter(id)} style={{
                  padding: "6px 14px", borderRadius: 20, border: "none", cursor: "pointer", fontSize: 12, fontWeight: 500,
                  background: filter === id ? "rgba(232,200,125,0.2)" : "rgba(255,255,255,0.04)",
                  color: filter === id ? "#E8C87D" : "var(--t4)",
                  transition: "all .15s",
                }}>{label}</button>
              ))}
            </div>
            <div style={{ position: "relative", display: "flex", alignItems: "center", flex: 1, maxWidth: 220, marginLeft: "auto" }}>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ position: "absolute", left: 10, color: "var(--t4)", pointerEvents: "none" }}><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
              <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search tasks…" style={{ ...S.textInput, paddingLeft: 30, fontSize: 12 }} />
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
              <h3>No tasks{filter !== "all" ? ` with status "${filter}"` : ""}</h3>
              <p>Create a task or extract them from an AI conversation.</p>
              <button onClick={() => setCreating(true)} style={S.btnPrimary}>+ New Task</button>
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {filtered.map(t => (
                <TaskCard key={t.id} task={t} onStatusChange={updateStatus} onDelete={deleteTask} />
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── Workflows tab ─────────────────────────────────────────────────────── */}
      {tab === "workflows" && (
        <div style={{ flex: 1, overflowY: "auto", padding: 24, display: "flex", flexDirection: "column", gap: 20 }}>

          {/* Active runs */}
          <div style={S.card}>
            <div style={{ ...S.cardTitle, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <span>Active Workflow Runs</span>
              <button onClick={loadWorkflows} disabled={wfLoading} style={{ ...S.btnSecondary, padding: "4px 12px", fontSize: 12 }}>
                {wfLoading ? "…" : "↻ Refresh"}
              </button>
            </div>
            <div style={{ padding: "0 0 4px" }}>
              {wfLoading ? (
                <div style={{ padding: "16px 18px" }}><div className="skeleton" style={{ height: 40, borderRadius: 8 }} /></div>
              ) : wfRuns.length === 0 ? (
                <div style={{ padding: "16px 18px", color: "var(--t4)", fontSize: 13 }}>No active runs — start a workflow below.</div>
              ) : wfRuns.map(run => {
                const pct = run.steps_total > 0 ? Math.round((run.steps_done / run.steps_total) * 100) : 0;
                const statusColor: Record<string, string> = { running: "#E8C87D", completed: "#00C853", failed: "#FF5252", pending: "#FFB300" };
                const color = statusColor[run.status] ?? "var(--t4)";
                return (
                  <div key={run.run_id} style={{ padding: "12px 18px", borderTop: "1px solid var(--border)", display: "flex", flexDirection: "column", gap: 8 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                      <span style={{ fontSize: 12, fontWeight: 600, color: "var(--t1)", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {run.workflow_id}
                      </span>
                      <span style={{ fontSize: 11, fontWeight: 700, color, background: color + "18", border: `1px solid ${color}33`, padding: "2px 8px", borderRadius: 99 }}>
                        {run.status}
                      </span>
                      <span style={{ fontSize: 11, color: "var(--t4)" }}>
                        {run.steps_done}/{run.steps_total} steps
                      </span>
                    </div>
                    <div style={{ height: 4, background: "var(--bg-base)", borderRadius: 99, overflow: "hidden" }}>
                      <div style={{ height: "100%", width: `${pct}%`, background: color, borderRadius: 99, transition: "width .4s" }} />
                    </div>
                    {run.error && <div style={{ fontSize: 11, color: "#FF5252" }}>{run.error}</div>}
                  </div>
                );
              })}
            </div>
          </div>

          {/* Workflow templates → run via real API */}
          <div>
            <div className="section-label" style={{ marginBottom: 12 }}>WORKFLOW TEMPLATES</div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(260px,1fr))", gap: 12 }}>
              {([
                { kind: "sequential", name: "Sequential Pipeline", desc: "Run steps one after another — fetch → process → store", icon: "📋", trigger: "On demand" },
                { kind: "parallel",   name: "Parallel Fan-out",    desc: "Execute independent steps simultaneously for speed",   icon: "⚡", trigger: "On demand" },
                { kind: "approval",   name: "Human-in-the-Loop",   desc: "Pause at checkpoints for manual review and approval",  icon: "👤", trigger: "On demand" },
                { kind: "saga",       name: "Saga (Compensating)", desc: "Distributed transaction with automatic rollback",      icon: "🔄", trigger: "On demand" },
              ] as const).map(wf => (
                <div
                  key={wf.kind}
                  style={{ ...S.card, padding: "16px 18px", cursor: runningDemo ? "wait" : "pointer" }}
                  className="card-hover"
                >
                  <div style={{ display: "flex", gap: 12, alignItems: "flex-start", marginBottom: 10 }}>
                    <div style={{ fontSize: 24, lineHeight: 1 }}>{wf.icon}</div>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: 13, fontWeight: 600, color: "var(--t1)" }}>{wf.name}</div>
                      <div style={{ fontSize: 11, color: "var(--t4)", marginTop: 3, lineHeight: 1.5 }}>{wf.desc}</div>
                    </div>
                  </div>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                    <span style={{ fontSize: 10, color: "var(--ta)", fontWeight: 500, background: "rgba(255,215,0,0.1)", border: "1px solid rgba(255,215,0,0.2)", borderRadius: 20, padding: "2px 8px" }}>
                      {wf.trigger}
                    </span>
                    <button
                      onClick={() => runDemoWorkflow(wf.kind)}
                      disabled={!!runningDemo}
                      style={{ ...S.btnPrimary, padding: "5px 14px", fontSize: 12 }}
                    >
                      {runningDemo === wf.kind ? "Starting…" : "▶ Run"}
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Pending approvals */}
          <div style={S.card}>
            <div style={S.cardTitle}>Pending Approvals</div>
            <ApprovalsList />
          </div>
        </div>
      )}
    </>
  );
}

function ApprovalsList() {
  type Approval = { run_id: string; step_id: string; step_name: string; requested_at: number };
  const toast = useToast();
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await apiFetch("/workflows/approvals/pending");
      if (r.ok) { const d = await r.json(); setApprovals(d.approvals ?? []); }
    } catch {}
  }, []);

  useEffect(() => { load(); }, [load]);

  const decide = async (run_id: string, step_id: string, action: "approve" | "reject") => {
    setBusy(`${run_id}:${step_id}`);
    try {
      const r = await apiFetch(`/workflows/approvals/${run_id}/${step_id}/${action}`, { method: "POST" });
      if (!r.ok) throw new Error();
      toast(`Step ${action}d`, "ok");
      setApprovals(p => p.filter(a => !(a.run_id === run_id && a.step_id === step_id)));
    } catch { toast(`Failed to ${action}`, "err"); }
    finally { setBusy(null); }
  };

  if (approvals.length === 0) return (
    <div style={{ padding: "12px 18px", color: "var(--t4)", fontSize: 13 }}>No pending approvals.</div>
  );

  return (
    <div>
      {approvals.map(a => (
        <div key={`${a.run_id}:${a.step_id}`} style={{ padding: "12px 18px", borderTop: "1px solid var(--border)", display: "flex", alignItems: "center", gap: 12 }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: "var(--t1)" }}>{a.step_name}</div>
            <div style={{ fontSize: 11, color: "var(--t4)" }}>run {a.run_id.slice(0, 8)}…</div>
          </div>
          <button
            onClick={() => decide(a.run_id, a.step_id, "approve")}
            disabled={!!busy}
            style={{ padding: "5px 14px", borderRadius: 8, border: "none", cursor: "pointer", fontSize: 12, fontWeight: 600, background: "#00C853", color: "#fff" }}
          >Approve</button>
          <button
            onClick={() => decide(a.run_id, a.step_id, "reject")}
            disabled={!!busy}
            style={{ padding: "5px 14px", borderRadius: 8, border: "none", cursor: "pointer", fontSize: 12, fontWeight: 600, background: "#FF5252", color: "#fff" }}
          >Reject</button>
        </div>
      ))}
    </div>
  );
}
