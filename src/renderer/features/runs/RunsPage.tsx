/**
 * Runs — execution monitoring page.
 * Shows all agent & automation runs with status, duration, and drill-down.
 */
import { useState, useEffect, useCallback } from "react";
import { apiFetch } from "../../utils/api";

/* ── Types ──────────────────────────────────────────────────────── */
type RunStatus = "running" | "completed" | "failed" | "pending" | "cancelled";
type Run = {
  job_id: string; kind: string; status: RunStatus;
  progress: number; error?: string;
  created_at: string; started_at?: string; finished_at?: string;
};
type RunStats = { total: number; active: number; dead: number; counts: Record<string, number> };

/* ── Helpers ────────────────────────────────────────────────────── */
const STATUS_CFG: Record<string, { color: string; bg: string; label: string }> = {
  running:   { color: "var(--blue)",   bg: "var(--blue-dim)",   label: "Running"   },
  completed: { color: "var(--green)",  bg: "var(--green-dim)",  label: "Completed" },
  failed:    { color: "var(--red)",    bg: "var(--red-dim)",    label: "Failed"    },
  pending:   { color: "var(--yellow)", bg: "var(--yellow-dim)", label: "Pending"   },
  cancelled: { color: "var(--t4)",     bg: "var(--bg-card)",    label: "Cancelled" },
};

function elapsed(job: Run, now: number): string {
  const start = job.started_at ? new Date(job.started_at).getTime() : new Date(job.created_at).getTime();
  const end   = job.finished_at ? new Date(job.finished_at).getTime() : now;
  const s     = Math.round((end - start) / 1000);
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

/* ── Run detail drawer ───────────────────────────────────────────── */
function RunDetail({ run, now, onClose }: { run: Run; now: number; onClose: () => void }) {
  const cfg = STATUS_CFG[run.status] ?? STATUS_CFG.pending;
  return (
    <div style={{
      width: 360, flexShrink: 0, borderLeft: "1px solid var(--b1)",
      background: "var(--bg-surface)", display: "flex", flexDirection: "column",
      overflow: "hidden",
    }}>
      <div style={{ padding: "16px 20px", borderBottom: "1px solid var(--b1)", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: "var(--t1)" }}>Run Details</div>
        <button onClick={onClose} style={{ background: "none", border: "none", cursor: "pointer", color: "var(--t4)", fontSize: 22, lineHeight: 1 }}>×</button>
      </div>
      <div style={{ flex: 1, overflowY: "auto", padding: 20 }}>
        <div style={{ marginBottom: 20 }}>
          <div style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "6px 14px", borderRadius: 99, fontSize: 13, fontWeight: 600, background: cfg.bg, color: cfg.color }}>
            <span style={{ width: 6, height: 6, borderRadius: "50%", background: cfg.color }} />
            {cfg.label}
          </div>
        </div>
        {([
          ["Run ID",    run.job_id],
          ["Type",      run.kind.replace(/_/g, " ")],
          ["Duration",  elapsed(run, now)],
          ["Started",   run.started_at ? new Date(run.started_at).toLocaleString() : "—"],
          ["Finished",  run.finished_at ? new Date(run.finished_at).toLocaleString() : "—"],
        ] as [string, string][]).map(([label, value]) => (
          <div key={label} style={{ marginBottom: 14 }}>
            <div style={{ fontSize: 11, fontWeight: 600, color: "var(--t4)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 4 }}>{label}</div>
            <div style={{ fontSize: 13, color: "var(--t1)", fontFamily: label === "Run ID" ? "var(--font-mono)" : "inherit", wordBreak: "break-all" }}>{value}</div>
          </div>
        ))}
        {run.status === "running" && (
          <div style={{ marginBottom: 14 }}>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: "var(--t4)", textTransform: "uppercase", letterSpacing: "0.05em" }}>Progress</div>
              <span style={{ fontSize: 11, color: "var(--t4)" }}>{run.progress}%</span>
            </div>
            <div style={{ height: 6, borderRadius: 99, background: "var(--bg-card)", overflow: "hidden" }}>
              <div style={{ height: "100%", width: `${run.progress}%`, background: "var(--blue)", borderRadius: 99 }} />
            </div>
          </div>
        )}
        {run.error && (
          <div style={{ padding: "12px 14px", borderRadius: 10, background: "var(--red-dim)", border: "1px solid var(--red)" }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: "var(--red)", marginBottom: 4, textTransform: "uppercase" }}>Error</div>
            <div style={{ fontSize: 12, color: "var(--red)", lineHeight: 1.5 }}>{run.error}</div>
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
  const [runs, setRuns]     = useState<Run[]>([]);
  const [stats, setStats]   = useState<RunStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<RunStatus | "all">("all");
  const [selected, setSelected] = useState<Run | null>(null);
  const [now, setNow]       = useState(() => Date.now());

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [jr, sr] = await Promise.all([
        apiFetch("/api/jobs").then(r => r.json()).catch(() => ({ jobs: [] })),
        apiFetch("/api/jobs/stats").then(r => r.json()).catch(() => null) as Promise<RunStats | null>,
      ]);
      setRuns((jr as { jobs?: Run[] }).jobs ?? []);
      setStats(sr);
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const cancel = async (id: string) => {
    await apiFetch(`/api/jobs/${id}`, { method: "DELETE" }).catch(() => {});
    void load();
  };

  const filtered = filter === "all" ? runs : runs.filter(r => r.status === filter);

  const statusTabs: { id: RunStatus | "all"; label: string }[] = [
    { id: "all", label: "All" },
    { id: "running",   label: "Running"   },
    { id: "completed", label: "Completed" },
    { id: "failed",    label: "Failed"    },
    { id: "pending",   label: "Pending"   },
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
          <span style={{ fontSize: 15, fontWeight: 600, color: "var(--t1)" }}>Runs</span>
          {stats && <span style={{ fontSize: 12, color: "var(--t4)", marginLeft: 10 }}>{stats.total} total</span>}
        </div>
        <button
          onClick={load}
          style={{ display: "flex", alignItems: "center", gap: 6, padding: "7px 14px", borderRadius: 10, border: "1px solid var(--b1)", background: "var(--bg-card)", color: "var(--t2)", fontSize: 13, cursor: "pointer" }}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>
          Refresh
        </button>
      </header>

      <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>
        {/* Main content */}
        <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>

          {/* Stats row */}
          <div style={{ padding: "20px 24px 14px", display: "flex", gap: 12, flexWrap: "wrap", flexShrink: 0 }}>
            <StatCard label="Total" value={stats?.total ?? runs.length} color="var(--accent)"
              icon={<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>} />
            <StatCard label="Running" value={stats?.active ?? runs.filter(r => r.status === "running").length} color="var(--blue)"
              icon={<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polygon points="5 3 19 12 5 21 5 3"/></svg>} />
            <StatCard label="Completed" value={stats?.counts?.completed ?? runs.filter(r => r.status === "completed").length} color="var(--green)"
              icon={<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="20 6 9 17 4 12"/></svg>} />
            <StatCard label="Failed" value={stats?.dead ?? runs.filter(r => r.status === "failed").length} color="var(--red)"
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
                <div style={{ fontSize: 14, fontWeight: 600, color: "var(--t2)" }}>No runs {filter !== "all" ? `with status "${filter}"` : "yet"}</div>
                <div style={{ fontSize: 12, color: "var(--t4)" }}>Runs appear here when agents or automations execute.</div>
              </div>
            ) : (
              <div style={{ background: "var(--bg-surface)", border: "1px solid var(--b1)", borderRadius: 14, overflow: "hidden" }}>
                <table style={{ width: "100%", borderCollapse: "collapse" }}>
                  <thead>
                    <tr style={{ borderBottom: "1px solid var(--b1)", background: "var(--bg-card)" }}>
                      {["ID", "Type", "Status", "Progress", "Duration", "Started", ""].map(h => (
                        <th key={h} style={{ padding: "10px 14px", fontSize: 11, fontWeight: 600, color: "var(--t4)", textAlign: "left", textTransform: "uppercase", letterSpacing: "0.05em" }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.map(run => {
                      const cfg = STATUS_CFG[run.status] ?? STATUS_CFG.pending;
                      return (
                        <tr
                          key={run.job_id}
                          onClick={() => setSelected(run === selected ? null : run)}
                          style={{
                            borderBottom: "1px solid var(--b1)", cursor: "pointer",
                            background: selected?.job_id === run.job_id ? "var(--accent-dim)" : "transparent",
                            transition: "background 0.1s",
                          }}
                          onMouseEnter={e => { if (selected?.job_id !== run.job_id) (e.currentTarget as HTMLTableRowElement).style.background = "var(--bg-card)"; }}
                          onMouseLeave={e => { if (selected?.job_id !== run.job_id) (e.currentTarget as HTMLTableRowElement).style.background = "transparent"; }}
                        >
                          <td style={{ padding: "12px 14px", fontSize: 11, color: "var(--t4)", fontFamily: "var(--font-mono)" }}>
                            {run.job_id.slice(0, 8)}…
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
                              background: cfg.bg, color: cfg.color,
                            }}>
                              <span style={{ width: 5, height: 5, borderRadius: "50%", background: cfg.color, flexShrink: 0, animation: run.status === "running" ? "pulse 1s ease-in-out infinite" : "none" }} />
                              {cfg.label}
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
                            {(run.status === "running" || run.status === "pending") && (
                              <button
                                onClick={e => { e.stopPropagation(); void cancel(run.job_id); }}
                                style={{
                                  padding: "4px 10px", borderRadius: 7, border: "1px solid var(--red)",
                                  background: "transparent", color: "var(--red)", fontSize: 11, fontWeight: 600, cursor: "pointer",
                                }}
                              >
                                Cancel
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
