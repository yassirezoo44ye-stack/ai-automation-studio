/**
 * AutomationPage — task management and workflow automation hub.
 * Merges Tasks + Automation views into a single workspace.
 * Data: /api/tasks, /api/agents
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
  pending:     "#6b7280",
  in_progress: "#6c8ef7",
  done:        "#34d399",
};

const PRIORITY_DOT: Record<TaskPriority, string> = {
  low:    "#6b7280",
  medium: "#f59e0b",
  high:   "#ef4444",
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
        style={{ background: "none", border: "none", cursor: "pointer", padding: 0, marginTop: 2, color: task.status === "done" ? "#34d399" : "rgba(255,255,255,0.2)", flexShrink: 0 }}
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
            <span style={{ fontSize: 11, color: "var(--ta)", background: "rgba(108,142,247,.08)", padding: "1px 7px", borderRadius: 99 }}>{task.category}</span>
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
        <button onClick={() => onDelete(task.id)} className="btn-icon" title="Delete" style={{ width: 28, height: 28, color: "#f87171" }}>
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

  const loadTasks = useCallback(async () => {
    setLoading(true);
    try {
      const r = await apiFetch("/api/tasks?sort=created_at&limit=100");
      const d = await parseJSON<{ tasks?: Task[] }>(r, "/api/tasks");
      setTasks(d.tasks ?? []);
    } catch { toast("Could not load tasks", "err"); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => {
    loadTasks();
    apiFetch("/api/agents")
      .then(r => parseJSON<Agent[]>(r, "/api/agents"))
      .then(setAgents)
      .catch(() => {});
  }, [loadTasks]);

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
                background: tab === id ? "linear-gradient(135deg,#8b5cf6,#6366f1)" : "transparent",
                color:      tab === id ? "#fff" : "rgba(148,163,184,.6)",
                boxShadow:  tab === id ? "0 2px 12px rgba(139,92,246,.35)" : "none",
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
                  background: filter === id ? "rgba(108,142,247,0.2)" : "rgba(255,255,255,0.04)",
                  color: filter === id ? "#6c8ef7" : "var(--t4)",
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
        <div style={{ flex: 1, overflowY: "auto", padding: 24 }}>
          {agents.length === 0 ? (
            <div className="empty-state">
              <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.2" style={{ color: "var(--ta)" }}>
                <rect x="2" y="3" width="6" height="6" rx="1"/><rect x="9" y="3" width="6" height="6" rx="1"/><rect x="16" y="3" width="6" height="6" rx="1"/>
                <line x1="5" y1="9" x2="5" y2="12"/><line x1="12" y1="9" x2="12" y2="12"/><line x1="19" y1="9" x2="19" y2="12"/>
                <rect x="8" y="12" width="8" height="6" rx="1"/><line x1="12" y1="18" x2="12" y2="21"/>
              </svg>
              <h3>No agents for workflows</h3>
              <p>Create agents in the AI Workspace to build automated workflows.</p>
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <div className="section-label" style={{ marginBottom: 4 }}>AVAILABLE AGENTS</div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(260px,1fr))", gap: 12 }}>
                {agents.map(a => (
                  <div key={a.id} style={{ ...S.card, padding: "16px 18px" }}>
                    <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
                      <div style={{ width: 40, height: 40, borderRadius: 10, background: "rgba(139,92,246,.12)", border: "1px solid rgba(139,92,246,.2)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 20, flexShrink: 0 }}>{a.avatar}</div>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: 13, fontWeight: 600, color: "var(--t1)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{a.name}</div>
                        <div style={{ fontSize: 11, color: "var(--t4)", marginTop: 2 }}>{a.message_count ?? 0} conversations</div>
                      </div>
                      <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                        <div style={{ width: 6, height: 6, borderRadius: "50%", background: "#34d399" }} />
                        <span style={{ fontSize: 10, color: "#34d399" }}>Active</span>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
              <div style={{ marginTop: 8 }}>
                <div className="section-label" style={{ marginBottom: 12 }}>WORKFLOW TEMPLATES</div>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(260px,1fr))", gap: 12 }}>
                  {[
                    { name: "Daily Briefing",     desc: "Summarize tasks and send a daily report",       icon: "📋", trigger: "Scheduled · 9:00 AM",  task: "Set up daily briefing: review all pending tasks and prepare a summary report" },
                    { name: "Task from Chat",      desc: "Extract action items from AI conversations",    icon: "💬", trigger: "On conversation end",    task: "Extract tasks from AI conversations: review recent chat history and create tasks from action items" },
                    { name: "Research Pipeline",   desc: "Chain search → summarize → store to project",  icon: "🔬", trigger: "On demand",               task: "Research pipeline: define research topic, gather sources, summarize findings, and store results" },
                    { name: "Code Review Bot",     desc: "Review code files and generate feedback",       icon: "🤖", trigger: "On file change",           task: "Code review workflow: specify files to review, run through the Code Reviewer agent, and log feedback" },
                  ].map(wf => (
                    <div
                      key={wf.name}
                      role="button"
                      tabIndex={0}
                      style={{ ...S.card, padding: "16px 18px", cursor: "pointer" }}
                      className="card-hover"
                      onClick={async () => {
                        try {
                          const r = await apiFetch("/api/tasks", {
                            method: "POST",
                            body: JSON.stringify({ title: wf.task, priority: "medium" }),
                          });
                          if (!r.ok) throw new Error();
                          toast(`"${wf.name}" task created — check Tasks tab`, "ok");
                          loadTasks();
                          setTab("tasks");
                        } catch { toast("Failed to create workflow task", "err"); }
                      }}
                      onKeyDown={e => e.key === "Enter" && e.currentTarget.click()}
                    >
                      <div style={{ display: "flex", gap: 12, alignItems: "flex-start", marginBottom: 10 }}>
                        <div style={{ fontSize: 24, lineHeight: 1 }}>{wf.icon}</div>
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ fontSize: 13, fontWeight: 600, color: "var(--t1)" }}>{wf.name}</div>
                          <div style={{ fontSize: 11, color: "var(--t4)", marginTop: 3, lineHeight: 1.5 }}>{wf.desc}</div>
                        </div>
                      </div>
                      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                        <span style={{ fontSize: 10, color: "var(--ta)", fontWeight: 500, background: "rgba(139,92,246,0.1)", border: "1px solid rgba(139,92,246,0.2)", borderRadius: 20, padding: "2px 8px" }}>{wf.trigger}</span>
                        <span style={{ fontSize: 11, color: "var(--ta)", fontWeight: 500 }}>+ Create task →</span>
                      </div>
                    </div>
                  ))}
                </div>
                <div style={{ ...S.card, padding: "14px 18px", marginTop: 12, display: "flex", alignItems: "center", gap: 12 }}>
                  <div style={{ width: 32, height: 32, borderRadius: 8, background: "rgba(139,92,246,0.1)", border: "1px solid rgba(139,92,246,0.2)", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 13, fontWeight: 600, color: "var(--t1)" }}>Custom Workflow</div>
                    <div style={{ fontSize: 12, color: "var(--t4)" }}>Visual workflow builder — drag, connect, and configure agent steps</div>
                  </div>
                  <span style={{ fontSize: 11, color: "var(--ta)", fontWeight: 600, background: "rgba(139,92,246,0.1)", border: "1px solid rgba(139,92,246,0.2)", borderRadius: 20, padding: "3px 10px", flexShrink: 0 }}>Coming Q3</span>
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </>
  );
}
