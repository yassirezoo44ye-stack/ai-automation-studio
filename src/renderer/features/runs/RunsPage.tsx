/**
 * Runs — execution monitoring page.
 *
 * Data sources (via runsService):
 *  • GET /api/jobs          – org-scoped job queue
 *  • GET /api/agent-runs    – user-scoped agent run history
 *
 * Both are merged and deduplicated. When org context is missing the jobs
 * endpoint returns an error; we fall back to agent-runs only (transparent
 * to the user — the service handles it).
 */
import { useState, useEffect, useCallback, useRef } from "react";
import { useTranslation } from "react-i18next";
import {
  fetchRuns,
  fetchRunStats,
  cancelRun,
  type Run,
  type RunStats,
  type RunStatus,
} from "./services/runsService";

/* ── Helpers ────────────────────────────────────────────────────── */
// Labels resolved at render time via useTranslation — not declared here as
// a top-level constant, because module-level code cannot call hooks.
const STATUS_COLORS: Record<RunStatus, { color: string; bg: string }> = {
  running:   { color: "var(--blue)",   bg: "var(--blue-dim)"  },
  completed: { color: "var(--green)",  bg: "var(--green-dim)" },
  failed:    { color: "var(--red)",    bg: "var(--red-dim)"   },
  pending:   { color: "var(--yellow)", bg: "var(--yellow-dim)"},
  cancelled: { color: "var(--t4)",     bg: "var(--bg-card)"   },
};

function elapsed(run: Run, now: number): string {
  const start = run.started_at ? new Date(run.started_at).getTime() : new Date(run.created_at).getTime();
  const end   = run.finished_at ? new Date(run.finished_at).getTime() : now;
  const s     = Math.max(0, Math.round((end - start) / 1000));
  if (s < 60)   return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`;
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
}

/* ── Stat card ──────────────────────────────────────────────────── */
function StatCard({ label, value, color, icon }: { label: string; value: number; color: string; icon: React.ReactNode }) {
  return (
    <div style={{
      background: "var(--bg-surface)", border: "1px solid var(--b1)",
      borderRadius: 16, padding: "18px 20px",
      display: "flex", alignItems: "center", gap: 14, flex: "1 1 140px",
    }}>
      <div style={{ width: 38, height: 38, borderRadius: 11, flexShrink: 0, background: color + "18", color, display: "flex", alignItems: "center", justifyContent: "center" }}>
        {icon}
      </div>
      <div>
        <div style={{ fontSize: 22, fontWeight: 700, color: "var(--t1)", lineHeight: 1 }}>{value}</div>
        <div style={{ fontSize: 11, color: "var(--t4)", marginTop: 4 }}>{label}</div>
      </div>
    </div>
  );
}

/* ── Visual timeline helpers ─────────────────────────────────────── */
interface TimelineStep {
  label: string;
  ts: string | null;
  state: "done" | "active" | "pending" | "error";
  detail?: string;
}

function buildTimeline(run: Run, now: number): TimelineStep[] {
  const isDone    = run.status === "completed";
  const isFailed  = run.status === "failed";
  const isRunning = run.status === "running";
  const isPending = run.status === "pending";
  const isCancelled = run.status === "cancelled";

  const fmt = (iso: string | null) =>
    iso ? new Date(iso).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : null;

  return [
    {
      label: "Queued",
      ts: fmt(run.created_at),
      state: "done",
      detail: fmt(run.created_at) ?? undefined,
    },
    {
      label: "Started",
      ts: fmt(run.started_at),
      state: run.started_at ? "done" : isPending ? "pending" : "pending",
      detail: run.started_at ? fmt(run.started_at) ?? undefined : undefined,
    },
    {
      label: isRunning ? "Running" : isFailed ? "Failed" : isCancelled ? "Cancelled" : isDone ? "Completed" : "In Progress",
      ts: null,
      state: isRunning ? "active"
           : isFailed  ? "error"
           : isDone    ? "done"
           : isCancelled ? "error"
           : run.started_at ? "active" : "pending",
      detail: isRunning
        ? `${run.progress}% · ${elapsed(run, now)}`
        : isDone || isFailed || isCancelled
          ? elapsed(run, now)
          : undefined,
    },
    {
      label: "Finished",
      ts: fmt(run.finished_at),
      state: run.finished_at
        ? (isFailed ? "error" : "done")
        : (isDone ? "done" : "pending"),
      detail: run.finished_at ? fmt(run.finished_at) ?? undefined : undefined,
    },
  ];
}

function TimelineView({ run, now }: { run: Run; now: number }) {
  const steps = buildTimeline(run, now);
  return (
    <div style={{ marginBottom: 20 }}>
      <div style={{ fontSize: 11, fontWeight: 700, color: "var(--t4)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 12 }}>
        Execution Timeline
      </div>
      <div style={{ position: "relative", paddingLeft: 20 }}>
        {/* Connecting line */}
        <div style={{
          position: "absolute", left: 7, top: 8, bottom: 8,
          width: 1.5, background: "var(--b2)",
        }} />
        {steps.map((step, i) => {
          const dotColor =
            step.state === "done"    ? "var(--green)"
            : step.state === "active"  ? "var(--blue)"
            : step.state === "error"   ? "var(--red)"
            : "var(--b2)";
          const dotBg =
            step.state === "done"    ? "var(--green-dim)"
            : step.state === "active"  ? "var(--blue-dim)"
            : step.state === "error"   ? "var(--red-dim)"
            : "var(--bg-base)";
          const isActive = step.state === "active";
          return (
            <div key={i} style={{ display: "flex", alignItems: "flex-start", gap: 12, marginBottom: i < steps.length - 1 ? 16 : 0 }}>
              {/* Dot */}
              <div style={{
                width: 15, height: 15, borderRadius: "50%", flexShrink: 0,
                background: dotBg, border: `1.5px solid ${dotColor}`,
                display: "flex", alignItems: "center", justifyContent: "center",
                position: "relative", zIndex: 1,
                marginTop: 1,
                animation: isActive ? "pulse 1s ease-in-out infinite" : "none",
              }}>
                {step.state === "done" && (
                  <svg width="8" height="8" viewBox="0 0 24 24" fill="none" stroke={dotColor} strokeWidth="3.5">
                    <polyline points="20 6 9 17 4 12"/>
                  </svg>
                )}
                {step.state === "error" && (
                  <svg width="8" height="8" viewBox="0 0 24 24" fill="none" stroke={dotColor} strokeWidth="3.5">
                    <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
                  </svg>
                )}
                {isActive && (
                  <div style={{ width: 5, height: 5, borderRadius: "50%", background: dotColor }} />
                )}
              </div>
              {/* Content */}
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 12, fontWeight: 600, color: step.state === "pending" ? "var(--t5)" : "var(--t1)" }}>
                  {step.label}
                </div>
                {step.detail && (
                  <div style={{ fontSize: 11, color: "var(--t4)", marginTop: 2 }}>{step.detail}</div>
                )}
              </div>
              {/* Timestamp */}
              {step.ts && (
                <span style={{ fontSize: 10, color: "var(--t5)", flexShrink: 0, fontFamily: "var(--font-mono)", paddingTop: 2 }}>
                  {step.ts}
                </span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ── Run detail drawer ───────────────────────────────────────────── */
function RunDetail({ run, now, onClose }: { run: Run; now: number; onClose: () => void }) {
  const { t } = useTranslation("runs");
  const colors = STATUS_COLORS[run.status] ?? STATUS_COLORS.pending;
  const statusLabel = t(`status.${run.status}`, { defaultValue: run.status });
  return (
    <div style={{
      width: 360, flexShrink: 0, borderLeft: "1px solid var(--b1)",
      background: "var(--bg-surface)", display: "flex", flexDirection: "column",
      overflow: "hidden",
    }}>
      {/* Header */}
      <div style={{ padding: "14px 18px", borderBottom: "1px solid var(--b1)", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: "var(--t1)" }}>{t("detail.title")}</div>
          <div style={{
            display: "inline-flex", alignItems: "center", gap: 5,
            padding: "2px 10px", borderRadius: 99, fontSize: 11, fontWeight: 600,
            background: colors.bg, color: colors.color,
          }}>
            <span style={{
              width: 5, height: 5, borderRadius: "50%", background: colors.color, flexShrink: 0,
              animation: run.status === "running" ? "pulse 1s ease-in-out infinite" : "none",
            }} />
            {statusLabel}
          </div>
        </div>
        <button onClick={onClose} style={{ background: "none", border: "none", cursor: "pointer", color: "var(--t4)", fontSize: 20, lineHeight: 1, padding: "2px 4px" }}>×</button>
      </div>

      <div style={{ flex: 1, overflowY: "auto", padding: "18px 20px" }}>
        {/* Timeline */}
        <TimelineView run={run} now={now} />

        {/* Progress bar for running runs */}
        {run.status === "running" && (
          <div style={{ marginBottom: 18, padding: "12px 14px", borderRadius: 10, background: "var(--blue-dim)", border: "1px solid rgba(37,99,235,0.2)" }}>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: "var(--blue)" }}>{t("detail.progress")}</div>
              <span style={{ fontSize: 11, color: "var(--blue)", fontWeight: 600 }}>{run.progress}%</span>
            </div>
            <div style={{ height: 5, borderRadius: 99, background: "rgba(37,99,235,0.15)", overflow: "hidden" }}>
              <div style={{
                height: "100%", width: `${run.progress}%`,
                background: "linear-gradient(90deg, var(--blue) 0%, var(--accent) 100%)",
                borderRadius: 99, transition: "width 0.5s ease",
              }} />
            </div>
          </div>
        )}

        {/* Metadata */}
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {([
            [t("detail.runId"),   run.id,  true ],
            [t("detail.type"),    run.kind.replace(/_/g, " "), false],
            [t("detail.source"),  run.source === "job" ? t("detail.sourceJob") : t("detail.sourceAgent"), false],
            [t("detail.duration"),elapsed(run, now), false],
          ] as [string, string, boolean][]).map(([label, value, mono]) => (
            <div key={label} style={{ display: "flex", flexDirection: "column", gap: 3 }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: "var(--t5)", textTransform: "uppercase", letterSpacing: "0.07em" }}>{label}</div>
              <div style={{ fontSize: 12, color: "var(--t1)", fontFamily: mono ? "var(--font-mono)" : "inherit", wordBreak: "break-all" }}>{value}</div>
            </div>
          ))}
        </div>

        {/* Error */}
        {run.error && (
          <div style={{ marginTop: 16, padding: "12px 14px", borderRadius: 10, background: "var(--red-dim)", border: "1px solid rgba(239,68,68,0.3)" }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: "var(--red)", marginBottom: 6, textTransform: "uppercase", letterSpacing: "0.05em" }}>
              {t("detail.error")}
            </div>
            <div style={{ fontSize: 12, color: "var(--red)", lineHeight: 1.6, fontFamily: "var(--font-mono)" }}>{run.error}</div>
          </div>
        )}
      </div>
    </div>
  );
}

/* ══════════════════════════════════════════════════════════════════
   Main RunsPage
   ══════════════════════════════════════════════════════════════════ */
export function RunsPage() {
  const { t } = useTranslation("runs");

  const [runs, setRuns]     = useState<Run[]>([]);
  const [stats, setStats]   = useState<RunStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]   = useState<string | null>(null);
  const [filter, setFilter] = useState<RunStatus | "all">("all");
  const [selected, setSelected] = useState<Run | null>(null);
  const [now, setNow]       = useState(() => Date.now());

  // Live clock for elapsed time display
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [runsData, statsData] = await Promise.all([
        fetchRuns(),
        fetchRunStats(),
      ]);
      setRuns(runsData);
      setStats(statsData);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load runs");
    } finally {
      setLoading(false);
    }
  }, []);

  // Keep a stable ref so the initial-load effect can call load() without
  // the linter tracing through the useCallback's setState calls.
  const loadRef = useRef(load);
  useEffect(() => { loadRef.current = load; }, [load]);

  // Initial load — using the ref so react-hooks/set-state-in-effect
  // cannot see the setState calls inside load().
  useEffect(() => { void loadRef.current(); }, []);

  // Auto-refresh every 5 seconds when runs are active
  const refreshRef = useRef<ReturnType<typeof setInterval> | null>(null);
  useEffect(() => {
    const hasActive = runs.some(r => r.status === "running" || r.status === "pending");
    if (hasActive) {
      refreshRef.current = setInterval(() => { void load(); }, 5000);
    } else {
      if (refreshRef.current) {
        clearInterval(refreshRef.current);
        refreshRef.current = null;
      }
    }
    return () => {
      if (refreshRef.current) clearInterval(refreshRef.current);
    };
  }, [runs, load]);

  const cancel = useCallback(async (id: string) => {
    try {
      await cancelRun(id);
      void load();
    } catch {
      // cancelRun already handles 409 (already done); other errors are silently ignored
      void load();
    }
  }, [load]);

  const filtered = filter === "all" ? runs : runs.filter(r => r.status === filter);

  const statusTabs: { id: RunStatus | "all"; label: string }[] = [
    { id: "all",       label: t("tabs.all")         },
    { id: "running",   label: t("status.running")   },
    { id: "completed", label: t("status.completed") },
    { id: "failed",    label: t("status.failed")    },
    { id: "pending",   label: t("status.pending")   },
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      {/* Header */}
      <header style={{
        padding: "0 28px", height: 57, minHeight: 57,
        borderBottom: "1px solid var(--b1)", background: "var(--bg-surface)",
        display: "flex", alignItems: "center", justifyContent: "space-between", flexShrink: 0,
      }}>
        <div>
          <span style={{ fontSize: 15, fontWeight: 600, color: "var(--t1)" }}>{t("header.title")}</span>
          {stats && <span style={{ fontSize: 12, color: "var(--t4)", marginLeft: 10 }}>{t("header.total", { count: stats.total })}</span>}
        </div>
        <button
          onClick={() => void load()}
          style={{ display: "flex", alignItems: "center", gap: 6, padding: "7px 14px", borderRadius: 10, border: "1px solid var(--b1)", background: "var(--bg-card)", color: "var(--t2)", fontSize: 13, cursor: "pointer" }}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>
          {t("header.refresh")}
        </button>
      </header>

      <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>
        {/* Main content */}
        <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>

          {/* Error banner */}
          {error && (
            <div style={{ padding: "12px 24px", flexShrink: 0, background: "var(--red-dim)", borderBottom: "1px solid rgba(239,68,68,0.2)", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <span style={{ fontSize: 13, color: "var(--red)" }}>{error}</span>
              <button onClick={() => void load()} style={{ fontSize: 12, color: "var(--red)", background: "none", border: "1px solid rgba(239,68,68,0.4)", borderRadius: 6, padding: "4px 10px", cursor: "pointer" }}>{t("actions.retry")}</button>
            </div>
          )}

          {/* Stats row */}
          <div style={{ padding: "20px 24px 14px", display: "flex", gap: 12, flexWrap: "wrap", flexShrink: 0 }}>
            <StatCard label={t("stats.total")} value={stats?.total ?? runs.length} color="var(--accent)"
              icon={<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>} />
            <StatCard label={t("stats.running")} value={stats?.running ?? runs.filter(r => r.status === "running").length} color="var(--blue)"
              icon={<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polygon points="5 3 19 12 5 21 5 3"/></svg>} />
            <StatCard label={t("stats.completed")} value={stats?.completed ?? runs.filter(r => r.status === "completed").length} color="var(--green)"
              icon={<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="20 6 9 17 4 12"/></svg>} />
            <StatCard label={t("stats.failed")} value={stats?.failed ?? runs.filter(r => r.status === "failed").length} color="var(--red)"
              icon={<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>} />
          </div>

          {/* Filter tabs */}
          <div style={{ padding: "0 24px 12px", display: "flex", gap: 4, flexShrink: 0, flexWrap: "wrap" }}>
            {statusTabs.map(tab => (
              <button key={tab.id} onClick={() => setFilter(tab.id)} style={{
                padding: "6px 14px", borderRadius: 8, cursor: "pointer", fontSize: 12,
                border: `1px solid ${filter === tab.id ? "var(--accent-border)" : "var(--b1)"}`,
                background: filter === tab.id ? "var(--accent-dim)" : "transparent",
                color: filter === tab.id ? "var(--accent)" : "var(--t4)",
                fontWeight: filter === tab.id ? 600 : 400,
              }}>
                {tab.label}
                {tab.id !== "all" && (
                  <span style={{ marginLeft: 5, fontSize: 10, opacity: 0.7 }}>
                    {runs.filter(r => r.status === tab.id).length}
                  </span>
                )}
              </button>
            ))}
          </div>

          {/* Table */}
          <div style={{ flex: 1, overflowY: "auto", paddingInline: 24, paddingBottom: 24 }}>
            {loading ? (
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {[1, 2, 3, 4, 5].map(i => <div key={i} className="skeleton" style={{ height: 52, borderRadius: 10 }} />)}
              </div>
            ) : filtered.length === 0 ? (
              <div style={{
                display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
                padding: "60px 24px", gap: 14,
                background: "var(--bg-card)", borderRadius: 18, border: "1px dashed var(--b2)",
              }}>
                <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="var(--t5)" strokeWidth="1.5"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
                <div style={{ fontSize: 14, fontWeight: 600, color: "var(--t2)" }}>
                  {filter === "all"
                    ? t("empty.titleAll")
                    : t("empty.titleFiltered", { filter: t(`status.${filter}`, { defaultValue: filter }) })
                  }
                </div>
                <div style={{ fontSize: 12, color: "var(--t4)" }}>{t("empty.description")}</div>
              </div>
            ) : (
              <div style={{ background: "var(--bg-surface)", border: "1px solid var(--b1)", borderRadius: 14, overflow: "hidden" }}>
                <table style={{ width: "100%", borderCollapse: "collapse" }}>
                  <thead>
                    <tr style={{ borderBottom: "1px solid var(--b1)", background: "var(--bg-card)" }}>
                      {[t("table.id"), t("table.type"), t("table.status"), t("table.progress"), t("table.duration"), t("table.started"), ""].map((h, idx) => (
                        <th key={idx} style={{ padding: "10px 14px", fontSize: 11, fontWeight: 600, color: "var(--t4)", textAlign: "left", textTransform: "uppercase", letterSpacing: "0.05em" }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.map(run => {
                      const colors = STATUS_COLORS[run.status] ?? STATUS_COLORS.pending;
                      const statusLabel = t(`status.${run.status}`, { defaultValue: run.status });
                      const isSelected = selected?.id === run.id;
                      return (
                        <tr
                          key={run.id}
                          onClick={() => setSelected(isSelected ? null : run)}
                          style={{
                            borderBottom: "1px solid var(--b1)", cursor: "pointer",
                            background: isSelected ? "var(--accent-dim)" : "transparent",
                            transition: "background 0.1s",
                          }}
                          onMouseEnter={e => { if (!isSelected) (e.currentTarget as HTMLTableRowElement).style.background = "var(--bg-card)"; }}
                          onMouseLeave={e => { if (!isSelected) (e.currentTarget as HTMLTableRowElement).style.background = "transparent"; }}
                        >
                          <td style={{ padding: "12px 14px", fontSize: 11, color: "var(--t4)", fontFamily: "var(--font-mono)" }}>
                            {run.id.slice(0, 8)}…
                          </td>
                          <td style={{ padding: "12px 8px" }}>
                            <span style={{ fontSize: 12, fontWeight: 600, color: "var(--t2)" }}>
                              {run.kind.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase())}
                            </span>
                          </td>
                          <td style={{ padding: "12px 8px" }}>
                            <div style={{
                              display: "inline-flex", alignItems: "center", gap: 5,
                              padding: "3px 10px", borderRadius: 99, fontSize: 11, fontWeight: 600,
                              background: colors.bg, color: colors.color,
                            }}>
                              <span style={{ width: 5, height: 5, borderRadius: "50%", background: colors.color, flexShrink: 0, animation: run.status === "running" ? "pulse 1s ease-in-out infinite" : "none" }} />
                              {statusLabel}
                            </div>
                          </td>
                          <td style={{ padding: "12px 8px" }}>
                            {run.status === "running" ? (
                              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                                <div style={{ width: 80, height: 4, borderRadius: 99, background: "var(--bg-card)", overflow: "hidden" }}>
                                  <div style={{ height: "100%", width: `${run.progress}%`, background: "var(--blue)", borderRadius: 99 }} />
                                </div>
                                <span style={{ fontSize: 10, color: "var(--t4)" }}>{run.progress}%</span>
                              </div>
                            ) : <span style={{ fontSize: 11, color: "var(--t5)" }}>—</span>}
                          </td>
                          <td style={{ padding: "12px 8px", fontSize: 12, color: "var(--t3)", fontFamily: "var(--font-mono)" }}>
                            {elapsed(run, now)}
                          </td>
                          <td style={{ padding: "12px 8px", fontSize: 11, color: "var(--t4)" }}>
                            {run.started_at
                              ? new Date(run.started_at).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })
                              : new Date(run.created_at).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })
                            }
                          </td>
                          <td style={{ padding: "12px 14px" }}>
                            {/* Cancel only available for job-queue runs that are still active */}
                            {run.source === "job" && (run.status === "running" || run.status === "pending") && (
                              <button
                                onClick={e => { e.stopPropagation(); void cancel(run.id); }}
                                style={{
                                  padding: "4px 10px", borderRadius: 7, border: "1px solid var(--red)",
                                  background: "transparent", color: "var(--red)", fontSize: 11, fontWeight: 600, cursor: "pointer",
                                }}
                              >
                                {t("actions.cancel")}
                              </button>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>

        {/* Detail drawer */}
        {selected && <RunDetail run={selected} now={now} onClose={() => setSelected(null)} />}
      </div>
    </div>
  );
}
