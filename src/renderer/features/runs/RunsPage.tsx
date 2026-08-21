/**
 * RunsPage — execution history and live run monitoring.
 * Data: typed adapters (no backend endpoint yet — adapters ready for wiring).
 * RTL-first: logical CSS properties throughout.
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";

/* ── Types ──────────────────────────────────────────────────────────────── */
type RunStatus = "success" | "running" | "failed" | "queued" | "cancelled";

interface Run {
  id: string;
  app: string;
  trigger: string;
  status: RunStatus;
  duration: string;
  startedAt: string;
  steps: number;
  stepsOk: number;
}

/* ── Static data (typed adapter — endpoint TBD) ─────────────────────────── */
const MOCK_RUNS: Run[] = [
  { id: "run_01", app: "CRM App",        trigger: "Webhook",   status: "success",   duration: "1.2s",  startedAt: "2m ago",   steps: 8,  stepsOk: 8  },
  { id: "run_02", app: "Lead Scorer",    trigger: "Schedule",  status: "running",   duration: "—",     startedAt: "just now", steps: 5,  stepsOk: 3  },
  { id: "run_03", app: "Email Agent",    trigger: "Manual",    status: "failed",    duration: "0.4s",  startedAt: "15m ago",  steps: 3,  stepsOk: 1  },
  { id: "run_04", app: "Data Enricher",  trigger: "Webhook",   status: "success",   duration: "3.8s",  startedAt: "30m ago",  steps: 12, stepsOk: 12 },
  { id: "run_05", app: "CRM App",        trigger: "API Call",  status: "success",   duration: "0.9s",  startedAt: "1h ago",   steps: 8,  stepsOk: 8  },
  { id: "run_06", app: "Billing Agent",  trigger: "Schedule",  status: "cancelled", duration: "—",     startedAt: "2h ago",   steps: 6,  stepsOk: 0  },
  { id: "run_07", app: "Lead Scorer",    trigger: "Webhook",   status: "success",   duration: "2.1s",  startedAt: "3h ago",   steps: 5,  stepsOk: 5  },
  { id: "run_08", app: "Email Agent",    trigger: "Manual",    status: "queued",    duration: "—",     startedAt: "5h ago",   steps: 3,  stepsOk: 0  },
];

const STATUS_CHIP: Record<RunStatus, { bg: string; color: string; label: string }> = {
  success:   { bg: "var(--green-dim)",   color: "var(--green)",   label: "Success"   },
  running:   { bg: "var(--blue-dim)",    color: "var(--blue)",    label: "Running"   },
  failed:    { bg: "var(--red-dim)",     color: "var(--red)",     label: "Failed"    },
  queued:    { bg: "var(--yellow-dim)",  color: "var(--yellow)",  label: "Queued"    },
  cancelled: { bg: "var(--bg-card)",     color: "var(--t3)",      label: "Cancelled" },
};

const STAT_TILES = [
  { label: "Total Runs",  value: "1,284", sub: "last 30 days",  color: "var(--t1)" },
  { label: "Success Rate",value: "94.2%", sub: "↑ 2.1% vs prev", color: "var(--green)" },
  { label: "Avg Duration",value: "1.8s",  sub: "median latency",  color: "var(--t1)" },
  { label: "Failed",      value: "74",    sub: "last 30 days",    color: "var(--red)"   },
];

const TRIGGERS = ["All", "Webhook", "Schedule", "Manual", "API Call"];
const STATUSES: Array<RunStatus | "all"> = ["all", "success", "running", "failed", "queued", "cancelled"];

/* ── Page ─────────────────────────────────────────────────────────────── */
export function RunsPage() {
  useTranslation("common");
  const [trigger, setTrigger] = useState("All");
  const [status, setStatus]   = useState<RunStatus | "all">("all");
  const [page, setPage]       = useState(1);
  const PER_PAGE = 6;

  const filtered = MOCK_RUNS.filter(r =>
    (trigger === "All" || r.trigger === trigger) &&
    (status  === "all" || r.status === status)
  );
  const paged     = filtered.slice((page - 1) * PER_PAGE, page * PER_PAGE);
  const totalPages = Math.max(1, Math.ceil(filtered.length / PER_PAGE));

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden", background: "var(--bg-base)", color: "var(--t1)" }}>
      {/* Header */}
      <div style={{ padding: "24px 28px 0", borderBlockEnd: "1px solid var(--b1)", background: "var(--bg-surface)", flexShrink: 0 }}>
        <h1 style={{ fontSize: 18, fontWeight: 700, margin: "0 0 4px", color: "var(--t1)" }}>Runs</h1>
        <p style={{ fontSize: 13, color: "var(--t3)", margin: "0 0 20px" }}>Execution history and live monitoring</p>
      </div>

      {/* Body */}
      <div style={{ flex: 1, overflowY: "auto", padding: 28 }}>

        {/* Stat tiles */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: 12, marginBlockEnd: 28 }}>
          {STAT_TILES.map(tile => (
            <div key={tile.label} style={{ background: "var(--bg-surface)", border: "1px solid var(--b1)", borderRadius: 12, padding: "16px 20px" }}>
              <div style={{ fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--t3)", marginBlockEnd: 8 }}>{tile.label}</div>
              <div style={{ fontSize: 26, fontWeight: 700, color: tile.color, letterSpacing: "-0.5px" }}>{tile.value}</div>
              <div style={{ fontSize: 11, color: "var(--t3)", marginBlockStart: 4 }}>{tile.sub}</div>
            </div>
          ))}
        </div>

        {/* Filter bar */}
        <div style={{ display: "flex", gap: 10, marginBlockEnd: 16, flexWrap: "wrap", alignItems: "center" }}>
          <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
            <span style={{ fontSize: 12, color: "var(--t3)", fontWeight: 500 }}>Trigger:</span>
            {TRIGGERS.map(tr => (
              <button key={tr} onClick={() => { setTrigger(tr); setPage(1); }}
                style={{ padding: "4px 10px", fontSize: 12, fontWeight: 500, borderRadius: 20, border: "1px solid", cursor: "pointer", transition: "all .12s",
                  background: trigger === tr ? "var(--accent-dim)" : "transparent",
                  borderColor: trigger === tr ? "var(--accent-border)" : "var(--b1)",
                  color: trigger === tr ? "var(--accent)" : "var(--t3)",
                }}>
                {tr}
              </button>
            ))}
          </div>
          <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
            <span style={{ fontSize: 12, color: "var(--t3)", fontWeight: 500 }}>Status:</span>
            {STATUSES.map(st => (
              <button key={st} onClick={() => { setStatus(st); setPage(1); }}
                style={{ padding: "4px 10px", fontSize: 12, fontWeight: 500, borderRadius: 20, border: "1px solid", cursor: "pointer", transition: "all .12s",
                  background: status === st ? (st === "all" ? "var(--accent-dim)" : STATUS_CHIP[st as RunStatus].bg) : "transparent",
                  borderColor: status === st ? (st === "all" ? "var(--accent-border)" : STATUS_CHIP[st as RunStatus].color + "44") : "var(--b1)",
                  color: status === st ? (st === "all" ? "var(--accent)" : STATUS_CHIP[st as RunStatus].color) : "var(--t3)",
                }}>
                {st === "all" ? "All" : STATUS_CHIP[st].label}
              </button>
            ))}
          </div>
        </div>

        {/* Runs table */}
        <div style={{ background: "var(--bg-surface)", border: "1px solid var(--b1)", borderRadius: 12, overflow: "hidden" }}>
          <div style={{ display: "grid", gridTemplateColumns: "3fr 1fr 1fr 1fr 1fr 1fr", gap: 0, borderBlockEnd: "1px solid var(--b1)", padding: "10px 18px", fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--t3)" }}>
            <span>App / Trigger</span>
            <span>Status</span>
            <span>Duration</span>
            <span>Steps</span>
            <span>Started</span>
            <span style={{ textAlign: "end" }}>Actions</span>
          </div>
          {paged.length === 0 && (
            <div style={{ padding: "40px 0", textAlign: "center", color: "var(--t3)", fontSize: 14 }}>No runs match the selected filters.</div>
          )}
          {paged.map((run, i) => {
            const chip = STATUS_CHIP[run.status];
            return (
              <div key={run.id} style={{ display: "grid", gridTemplateColumns: "3fr 1fr 1fr 1fr 1fr 1fr", gap: 0, padding: "12px 18px", fontSize: 13, borderBlockEnd: i < paged.length - 1 ? "1px solid var(--b1)" : "none", alignItems: "center" }}>
                <div>
                  <div style={{ fontWeight: 600, color: "var(--t1)" }}>{run.app}</div>
                  <div style={{ fontSize: 11, color: "var(--t3)", marginBlockStart: 2 }}>{run.trigger}</div>
                </div>
                <span style={{ display: "inline-flex", alignItems: "center", gap: 5, padding: "3px 9px", borderRadius: 20, fontSize: 11, fontWeight: 600, background: chip.bg, color: chip.color, whiteSpace: "nowrap", width: "fit-content" }}>
                  {run.status === "running" && <span style={{ width: 7, height: 7, borderRadius: "50%", background: chip.color, display: "inline-block", animation: "pulse 1.2s infinite" }} />}
                  {chip.label}
                </span>
                <span style={{ color: "var(--t2)", fontFamily: "var(--font-mono)", fontSize: 12 }}>{run.duration}</span>
                <span style={{ color: "var(--t2)" }}>{run.stepsOk}/{run.steps}</span>
                <span style={{ color: "var(--t3)", fontSize: 12 }}>{run.startedAt}</span>
                <div style={{ display: "flex", gap: 6, justifyContent: "flex-end" }}>
                  <button style={{ padding: "4px 10px", fontSize: 11, fontWeight: 500, background: "var(--bg-card)", border: "1px solid var(--b1)", borderRadius: 6, cursor: "pointer", color: "var(--t2)" }}>Logs</button>
                  {run.status === "failed" && (
                    <button style={{ padding: "4px 10px", fontSize: 11, fontWeight: 500, background: "var(--accent-dim)", border: "1px solid var(--accent-border)", borderRadius: 6, cursor: "pointer", color: "var(--accent)" }}>Retry</button>
                  )}
                </div>
              </div>
            );
          })}
        </div>

        {/* Pagination */}
        {totalPages > 1 && (
          <div style={{ display: "flex", justifyContent: "center", gap: 6, marginBlockStart: 16 }}>
            <button disabled={page === 1} onClick={() => setPage(p => p - 1)}
              style={{ padding: "6px 14px", fontSize: 12, fontWeight: 500, background: "var(--bg-surface)", border: "1px solid var(--b1)", borderRadius: 8, cursor: page === 1 ? "not-allowed" : "pointer", color: page === 1 ? "var(--t4)" : "var(--t2)" }}>
              ← Prev
            </button>
            {Array.from({ length: totalPages }, (_, i) => i + 1).map(p => (
              <button key={p} onClick={() => setPage(p)}
                style={{ width: 32, height: 32, fontSize: 12, fontWeight: 500, background: page === p ? "var(--accent)" : "var(--bg-surface)", border: "1px solid", borderColor: page === p ? "var(--accent)" : "var(--b1)", borderRadius: 8, cursor: "pointer", color: page === p ? "#fff" : "var(--t2)" }}>
                {p}
              </button>
            ))}
            <button disabled={page === totalPages} onClick={() => setPage(p => p + 1)}
              style={{ padding: "6px 14px", fontSize: 12, fontWeight: 500, background: "var(--bg-surface)", border: "1px solid var(--b1)", borderRadius: 8, cursor: page === totalPages ? "not-allowed" : "pointer", color: page === totalPages ? "var(--t4)" : "var(--t2)" }}>
              Next →
            </button>
          </div>
        )}
      </div>

      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50%       { opacity: 0.35; }
        }
      `}</style>
    </div>
  );
}
