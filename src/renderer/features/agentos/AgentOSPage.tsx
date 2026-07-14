import { useState, useEffect, useCallback, useRef } from "react";
import { agentOsApi } from "./api";
import { apiFetch } from "../../utils/api";
import type { AgentResult, AgentInfo, MemoryRecord, SystemStatus, Suggestion, DeliberationBid } from "./api";

// ── Styles ────────────────────────────────────────────────────────────────────
const S = {
  page: {
    display: "flex", flexDirection: "column" as const,
    height: "100%", overflow: "hidden",
    background: "var(--bg-base)", color: "var(--t1)",
  },
  header: {
    padding: "20px 24px 0",
    borderBottom: "1px solid var(--border)",
    background: "var(--bg-surface)",
    flexShrink: 0,
  },
  headerTop: {
    display: "flex", alignItems: "center", gap: 12, marginBottom: 16,
  },
  title: {
    fontSize: 20, fontWeight: 700, letterSpacing: "-0.3px",
    background: "linear-gradient(135deg, var(--accent), #a78bfa)",
    WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent",
  },
  badge: {
    fontSize: 11, fontWeight: 600, padding: "2px 8px",
    borderRadius: 99, background: "var(--accent)", color: "#fff",
    letterSpacing: "0.5px",
  },
  tabs: {
    display: "flex", gap: 0, marginBottom: -1,
  },
  tab: (active: boolean) => ({
    padding: "8px 16px", fontSize: 13, fontWeight: 500,
    cursor: "pointer", border: "none", background: "transparent",
    color: active ? "var(--accent)" : "var(--t3)",
    borderBottom: active ? "2px solid var(--accent)" : "2px solid transparent",
    transition: "color .15s",
  }),
  body: {
    flex: 1, overflow: "auto", padding: 24,
    display: "grid", gridTemplateColumns: "1fr", gap: 20,
  },
  card: {
    background: "var(--bg-surface)", border: "1px solid var(--border)",
    borderRadius: 12, overflow: "hidden",
  },
  cardHeader: {
    padding: "12px 16px", borderBottom: "1px solid var(--border)",
    fontSize: 13, fontWeight: 600, color: "var(--t2)",
    display: "flex", alignItems: "center", justifyContent: "space-between",
  },
  cardBody: { padding: 16 },
  input: {
    width: "100%", padding: "10px 14px", fontSize: 14,
    background: "var(--bg-base)", border: "1px solid var(--border)",
    borderRadius: 8, color: "var(--t1)", outline: "none",
    boxSizing: "border-box" as const,
    fontFamily: "inherit",
  },
  btn: (variant: "primary" | "ghost" | "danger" = "primary") => ({
    padding: "8px 16px", fontSize: 13, fontWeight: 500,
    borderRadius: 8,
    border: variant === "ghost" ? "1px solid var(--border)" : "none",
    cursor: "pointer",
    background: variant === "primary" ? "var(--accent)"
              : variant === "danger"  ? "#ef4444"
              : "var(--bg-base)",
    color: variant === "ghost" ? "var(--t2)" : "#fff",
    transition: "opacity .15s",
    whiteSpace: "nowrap" as const,
    flexShrink: 0,
  }),
  row: {
    display: "flex", gap: 8, alignItems: "center",
  },
  tag: (color: string) => ({
    fontSize: 11, fontWeight: 600, padding: "2px 7px",
    borderRadius: 99, background: color + "22", color,
    letterSpacing: "0.3px",
  }),
  mono: {
    fontFamily: "ui-monospace, monospace", fontSize: 12,
    color: "var(--t2)",
  },
};

// ── Sub-components ────────────────────────────────────────────────────────────

function StatPill({ label, value, color = "var(--accent)" }: { label: string; value: string | number; color?: string }) {
  return (
    <div style={{ textAlign: "center" }}>
      <div style={{ fontSize: 22, fontWeight: 700, color }}>{value}</div>
      <div style={{ fontSize: 11, color: "var(--t3)", marginTop: 2 }}>{label}</div>
    </div>
  );
}

function SuccessBar({ rate, height = 6 }: { rate: number; height?: number }) {
  const color = rate >= 0.8 ? "#22c55e" : rate >= 0.5 ? "#f59e0b" : "#ef4444";
  return (
    <div style={{ background: "var(--bg-base)", borderRadius: 99, height, overflow: "hidden", flex: 1 }}>
      <div style={{ height: "100%", width: `${rate * 100}%`, background: color, borderRadius: 99, transition: "width .4s" }} />
    </div>
  );
}

function ResultBox({ result }: { result: AgentResult }) {
  const color = result.success ? "#22c55e" : "#ef4444";
  return (
    <div style={{ marginTop: 12, borderRadius: 8, border: `1px solid ${color}33`, background: color + "0a", padding: 12 }}>
      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 6 }}>
        <span style={{ color, fontWeight: 700, fontSize: 13 }}>{result.success ? "✓" : "✗"} {result.agent}</span>
        <span style={{ color: "var(--t3)", fontSize: 11 }}>{result.duration_ms.toFixed(0)}ms</span>
      </div>
      <pre style={{ ...S.mono, whiteSpace: "pre-wrap", margin: 0, color: "var(--t1)" }}>{result.output}</pre>
    </div>
  );
}

// ── Command Terminal ──────────────────────────────────────────────────────────

function CommandTerminal({ onResult }: { onResult: (r: AgentResult) => void }) {
  const [input, setInput]           = useState("");
  const [loading, setLoading]       = useState(false);
  const [mode, setMode]             = useState<"run" | "deliberate" | "plan">("run");
  const [delib, setDelib]           = useState<{ bids: DeliberationBid[]; winner: string } | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const submit = useCallback(async () => {
    const val = input.trim();
    if (!val || loading) return;
    setLoading(true);
    setDelib(null);
    try {
      if (mode === "deliberate") {
        const res = await agentOsApi.deliberate(val);
        setDelib({ bids: res.deliberation.bids, winner: res.deliberation.winner });
        onResult(res.result);
      } else if (mode === "plan") {
        const res = await agentOsApi.plan(val);
        onResult({
          agent: "plan", success: res.success, output: res.plan.join(" → "),
          data: { results: res.results }, duration_ms: 0,
        });
      } else {
        const res = await agentOsApi.run(val);
        onResult(res);
      }
    } catch (e: unknown) {
      onResult({ agent: "error", success: false, output: String(e), data: {}, duration_ms: 0, error: String(e) });
    }
    setLoading(false);
    setInput("");
  }, [input, mode, loading, onResult]);

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); }
  };

  return (
    <div style={S.card}>
      <div style={S.cardHeader}>
        <span>🧠 Natural Language Terminal</span>
        <div style={S.row}>
          {(["run", "deliberate", "plan"] as const).map(m => (
            <button key={m} onClick={() => setMode(m)} style={{
              ...S.btn(mode === m ? "primary" : "ghost"),
              padding: "5px 12px", fontSize: 12,
            }}>{m}</button>
          ))}
        </div>
      </div>
      <div style={S.cardBody}>
        <div style={S.row}>
          <textarea
            ref={inputRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={onKey}
            placeholder={
              mode === "plan"      ? "Describe your goal: build and deploy a web scraper" :
              mode === "deliberate"? "Describe a task — agents will vote on who handles it" :
              "Natural language: analyze my project / deploy to production / evolve run"
            }
            style={{ ...S.input, minHeight: 60, resize: "vertical" }}
            autoFocus
          />
          <button onClick={submit} disabled={loading} style={S.btn("primary")}>
            {loading ? "…" : "Run"}
          </button>
        </div>
        {mode === "deliberate" && delib && (
          <div style={{ marginTop: 14 }}>
            <div style={{ fontSize: 12, color: "var(--t3)", marginBottom: 8 }}>Agent votes:</div>
            {delib.bids.slice(0, 5).map(b => (
              <div key={b.agent} style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 6 }}>
                <span style={{ width: 90, fontSize: 12, fontWeight: b.agent === delib.winner ? 700 : 400,
                               color: b.agent === delib.winner ? "var(--accent)" : "var(--t2)" }}>
                  {b.agent === delib.winner ? "▶ " : "  "}{b.agent}
                </span>
                <SuccessBar rate={b.score} height={8} />
                <span style={{ fontSize: 11, color: "var(--t3)", width: 36 }}>{(b.score * 100).toFixed(0)}%</span>
              </div>
            ))}
          </div>
        )}

        {/* Quick examples */}
        <div style={{ marginTop: 12, display: "flex", flexWrap: "wrap" as const, gap: 6 }}>
          {["help", "status", "analyze agents", "evolve analyze", "build ."].map(ex => (
            <button key={ex} onClick={() => setInput(ex)} style={{ ...S.btn("ghost"), padding: "4px 10px", fontSize: 11 }}>
              {ex}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── Agent Grid ────────────────────────────────────────────────────────────────

function AgentGrid({ agents }: { agents: AgentInfo[] }) {
  const groups: Record<string, AgentInfo[]> = {};
  for (const a of agents) groups[a.group] = [...(groups[a.group] ?? []), a];

  return (
    <div style={S.card}>
      <div style={S.cardHeader}>
        <span>⚡ Registered Agents ({agents.length})</span>
      </div>
      <div style={S.cardBody}>
        {Object.entries(groups).map(([group, items]) => (
          <div key={group} style={{ marginBottom: 16 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: "var(--t3)", textTransform: "uppercase", letterSpacing: "0.8px", marginBottom: 8 }}>
              {group}
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 8 }}>
              {items.map(a => (
                <div key={a.name} style={{
                  padding: "10px 12px", borderRadius: 8,
                  background: "var(--bg-base)", border: "1px solid var(--border)",
                }}>
                  <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 4 }}>
                    <span style={{ fontWeight: 600, fontSize: 13 }}>{a.name}</span>
                    {a.stats.call_count > 0 && (
                      <span style={S.tag(a.stats.success_rate >= 0.8 ? "#22c55e" : a.stats.success_rate >= 0.5 ? "#f59e0b" : "#ef4444")}>
                        {(a.stats.success_rate * 100).toFixed(0)}%
                      </span>
                    )}
                  </div>
                  <div style={{ fontSize: 11, color: "var(--t3)", marginBottom: a.stats.call_count > 0 ? 6 : 0 }}>
                    {a.description}
                  </div>
                  {a.stats.call_count > 0 && (
                    <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                      <SuccessBar rate={a.stats.success_rate} />
                      <span style={{ fontSize: 10, color: "var(--t3)", whiteSpace: "nowrap" as const }}>
                        {a.stats.call_count} calls · {a.stats.avg_ms.toFixed(0)}ms
                      </span>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Execution Log ─────────────────────────────────────────────────────────────

function ExecutionLog({ records }: { records: MemoryRecord[] }) {
  return (
    <div style={S.card}>
      <div style={S.cardHeader}>
        <span>📋 Execution Memory ({records.length})</span>
      </div>
      <div style={{ ...S.cardBody, maxHeight: 320, overflowY: "auto" }}>
        {records.length === 0 ? (
          <div style={{ color: "var(--t3)", fontSize: 13, textAlign: "center", padding: "20px 0" }}>
            No executions yet — run a command above.
          </div>
        ) : records.map((r, i) => (
          <div key={i} style={{
            display: "flex", gap: 10, alignItems: "flex-start",
            padding: "7px 0", borderBottom: i < records.length - 1 ? "1px solid var(--border)" : "none",
          }}>
            <span style={{ color: r.success ? "#22c55e" : "#ef4444", fontSize: 14, flexShrink: 0, marginTop: 1 }}>
              {r.success ? "✓" : "✗"}
            </span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <span style={{ fontSize: 12, fontWeight: 600, color: "var(--accent)" }}>{r.agent}</span>
                <span style={{ fontSize: 11, color: "var(--t3)" }}>
                  {new Date(r.timestamp * 1000).toLocaleTimeString()}
                </span>
                <span style={{ fontSize: 11, color: "var(--t3)" }}>{r.duration_ms.toFixed(0)}ms</span>
              </div>
              <div style={{ fontSize: 12, color: "var(--t2)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" as const }}>
                {r.input}
              </div>
              {r.error && <div style={{ fontSize: 11, color: "#ef4444" }}>{r.error}</div>}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Evolution Panel ───────────────────────────────────────────────────────────

function EvolutionPanel({
  status, suggestions, onEvolve, onSuggest, onGenerate,
}: {
  status: SystemStatus | null;
  suggestions: Suggestion[];
  onEvolve: () => Promise<void>;
  onSuggest: () => Promise<void>;
  onGenerate: (desc: string) => Promise<void>;
}) {
  const [genDesc, setGenDesc]   = useState("");
  const [loading, setLoading]   = useState<string | null>(null);

  const run = async (key: string, fn: () => Promise<void>) => {
    setLoading(key); try { await fn(); } finally { setLoading(null); }
  };

  return (
    <div style={S.card}>
      <div style={S.cardHeader}>
        <span>🧬 Self-Evolution Engine</span>
        <div style={S.row}>
          <button onClick={() => run("evolve", onEvolve)} disabled={loading === "evolve"} style={S.btn("primary")}>
            {loading === "evolve" ? "Evolving…" : "▶ Evolve"}
          </button>
          <button onClick={() => run("suggest", onSuggest)} disabled={loading === "suggest"} style={S.btn("ghost")}>
            {loading === "suggest" ? "…" : "Suggest"}
          </button>
        </div>
      </div>
      <div style={S.cardBody}>
        {/* Stats row */}
        {status && (
          <div style={{ display: "flex", gap: 24, marginBottom: 16, flexWrap: "wrap" as const }}>
            <StatPill label="Agents"     value={status.agents} />
            <StatPill label="Executions" value={status.memory_count} />
            <StatPill label="Loop ticks" value={status.loop_stats?.tick_count ?? 0} color="#a78bfa" />
            <StatPill label="Evolutions" value={status.loop_stats?.evolution_cycles ?? 0} color="#f59e0b" />
            <StatPill label="LLM" value={status.llm_available ? "✓" : "✗"}
                      color={status.llm_available ? "#22c55e" : "#ef4444"} />
          </div>
        )}

        {/* Suggestions */}
        {suggestions.length > 0 && (
          <div style={{ marginBottom: 14 }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: "var(--t3)", marginBottom: 8 }}>
              Suggested improvements:
            </div>
            {suggestions.map(s => (
              <div key={s.index} style={{
                display: "flex", gap: 10, alignItems: "center",
                padding: "7px 10px", marginBottom: 4,
                background: "var(--bg-base)", borderRadius: 8,
                border: `1px solid ${s.implemented ? "#22c55e33" : "var(--border)"}`,
              }}>
                <span style={{ fontSize: 11, color: s.implemented ? "#22c55e" : "var(--accent)", fontWeight: 700 }}>
                  [{s.index}]
                </span>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 13, fontWeight: 500 }}>{s.title}</div>
                  <div style={{ fontSize: 11, color: "var(--t3)" }}>{s.description}</div>
                </div>
                <span style={S.tag(s.priority >= 0.7 ? "#ef4444" : s.priority >= 0.4 ? "#f59e0b" : "#22c55e")}>
                  {(s.priority * 100).toFixed(0)}%
                </span>
                {!s.implemented && (
                  <span style={{ fontSize: 11, color: "var(--t3)" }}>{s.agent_name}</span>
                )}
              </div>
            ))}
          </div>
        )}

        {/* Generate agent */}
        <div>
          <div style={{ fontSize: 12, fontWeight: 600, color: "var(--t3)", marginBottom: 8 }}>
            Generate new agent:
          </div>
          <div style={S.row}>
            <input
              value={genDesc}
              onChange={e => setGenDesc(e.target.value)}
              onKeyDown={e => e.key === "Enter" && genDesc.trim() && run("gen", () => onGenerate(genDesc))}
              placeholder="a rate-limiting agent that tracks API calls per user"
              style={S.input}
            />
            <button
              onClick={() => genDesc.trim() && run("gen", () => onGenerate(genDesc).then(() => setGenDesc("")))}
              disabled={loading === "gen" || !genDesc.trim()}
              style={S.btn("primary")}
            >
              {loading === "gen" ? "…" : "Generate"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Performance Panel ─────────────────────────────────────────────────────────

function PerformancePanel({ stats }: { stats: { agent_stats: ReturnType<typeof agentOsApi.performance extends Promise<infer T> ? () => T : never> extends null ? never : any } }) {
  const agentStats = (stats as any)?.agent_stats ?? [];
  const errorRate  = (stats as any)?.global_error_rate ?? 0;
  const underperf  = (stats as any)?.underperforming_agents ?? [];

  if (!agentStats.length) return (
    <div style={S.card}>
      <div style={S.cardHeader}><span>📊 Performance</span></div>
      <div style={S.cardBody}>
        <p style={{ color: "var(--t3)", fontSize: 13, textAlign: "center", padding: "16px 0" }}>
          Run some commands to see performance data.
        </p>
      </div>
    </div>
  );

  return (
    <div style={S.card}>
      <div style={S.cardHeader}>
        <span>📊 Performance</span>
        <span style={S.tag(errorRate > 0.3 ? "#ef4444" : errorRate > 0.1 ? "#f59e0b" : "#22c55e")}>
          {(errorRate * 100).toFixed(0)}% error rate
        </span>
      </div>
      <div style={S.cardBody}>
        {underperf.length > 0 && (
          <div style={{ marginBottom: 12, padding: "8px 12px", borderRadius: 8,
                        background: "#ef444411", border: "1px solid #ef444433" }}>
            <span style={{ fontSize: 12, color: "#ef4444", fontWeight: 600 }}>
              ⚠ Underperforming: {underperf.join(", ")} — run "Evolve" to fix
            </span>
          </div>
        )}
        {agentStats.map((s: any) => (
          <div key={s.name} style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 8 }}>
            <span style={{ width: 80, fontSize: 12, fontWeight: 500, flexShrink: 0 }}>{s.name}</span>
            <SuccessBar rate={s.success_rate} />
            <span style={{ fontSize: 11, color: "var(--t3)", width: 32, flexShrink: 0 }}>
              {(s.success_rate * 100).toFixed(0)}%
            </span>
            <span style={{ fontSize: 11, color: "var(--t3)", width: 52, flexShrink: 0 }}>
              {s.call_count} calls
            </span>
            <span style={{ fontSize: 11, color: "var(--t3)", width: 48, flexShrink: 0 }}>
              {s.avg_ms.toFixed(0)}ms
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

type Tab = "terminal" | "agents" | "memory" | "evolution" | "performance" | "jobs";

export function AgentOSPage() {
  const [tab, setTab]               = useState<Tab>("terminal");
  const [results, setResults]       = useState<AgentResult[]>([]);
  const [agents, setAgents]         = useState<AgentInfo[]>([]);
  const [records, setRecords]       = useState<MemoryRecord[]>([]);
  const [status, setStatus]         = useState<SystemStatus | null>(null);
  const [perfData, setPerfData]     = useState<any>(null);
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [toast, setToast]           = useState<{ msg: string; ok: boolean } | null>(null);

  const showToast = (msg: string, ok = true) => {
    setToast({ msg, ok });
    setTimeout(() => setToast(null), 3000);
  };

  const refresh = useCallback(async () => {
    try {
      const [s, a, m, p] = await Promise.all([
        agentOsApi.status(),
        agentOsApi.agents(),
        agentOsApi.memory(50),
        agentOsApi.performance(),
      ]);
      setStatus(s);
      setAgents(a.agents);
      setRecords(m.records);
      setPerfData(p);
      setSuggestions(s.suggestions ?? []);
    } catch { /* backend may be offline */ }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  // Refresh when switching tabs
  useEffect(() => { refresh(); }, [tab, refresh]);

  const handleResult = useCallback((r: AgentResult) => {
    setResults(prev => [r, ...prev].slice(0, 20));
    showToast(r.success ? `✓ ${r.agent}: done` : `✗ ${r.error ?? "failed"}`, r.success);
    setTimeout(refresh, 500);
  }, [refresh]);

  const handleEvolve = async () => {
    const res = await agentOsApi.evolve();
    const evolved = (res as any).evolved ?? [];
    showToast(evolved.length ? `Evolved: ${evolved.join(", ")}` : "All agents stable", true);
    refresh();
  };

  const handleSuggest = async () => {
    const res = await agentOsApi.suggest(3);
    setSuggestions(res.suggestions);
    showToast(`${res.count} suggestion(s) ready`, true);
  };

  const handleGenerate = async (desc: string) => {
    const res = await agentOsApi.generate(desc);
    if (res.status === "created") {
      showToast(`Agent created: ${res.agent_name}`, true);
      refresh();
    } else {
      showToast(res.error ?? "Generate failed", false);
    }
  };

  const TABS: { id: Tab; label: string }[] = [
    { id: "terminal",    label: "Terminal" },
    { id: "agents",      label: `Agents (${agents.length})` },
    { id: "memory",      label: `Memory (${records.length})` },
    { id: "evolution",   label: "Evolution" },
    { id: "performance", label: "Performance" },
    { id: "jobs",        label: "Jobs" },
  ];

  return (
    <div style={S.page}>
      {/* Toast */}
      {toast && (
        <div style={{
          position: "fixed", top: 16, right: 16, zIndex: 9999,
          padding: "10px 16px", borderRadius: 10, fontSize: 13, fontWeight: 500,
          background: toast.ok ? "#22c55e" : "#ef4444", color: "#fff",
          boxShadow: "0 4px 20px rgba(0,0,0,.3)",
          animation: "fadeIn .2s ease",
        }}>{toast.msg}</div>
      )}

      {/* Header */}
      <div style={S.header}>
        <div style={S.headerTop}>
          <div style={S.title}>AgentOS</div>
          <span style={S.badge}>AUTONOMOUS</span>
          {status?.llm_available && <span style={S.badge}>LLM ✓</span>}
          <button onClick={refresh} style={{ ...S.btn("ghost"), marginLeft: "auto", padding: "5px 12px", fontSize: 12 }}>
            ↻ Refresh
          </button>
        </div>
        <div style={S.tabs}>
          {TABS.map(t => (
            <button key={t.id} onClick={() => setTab(t.id)} style={S.tab(tab === t.id)}>
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {/* Body */}
      <div style={S.body}>
        {tab === "terminal" && (
          <>
            <CommandTerminal onResult={handleResult} />
            {results.map((r, i) => <ResultBox key={i} result={r} />)}
          </>
        )}
        {tab === "agents" && <AgentGrid agents={agents} />}
        {tab === "memory" && <ExecutionLog records={records} />}
        {tab === "evolution" && (
          <EvolutionPanel
            status={status}
            suggestions={suggestions}
            onEvolve={handleEvolve}
            onSuggest={handleSuggest}
            onGenerate={handleGenerate}
          />
        )}
        {tab === "performance" && <PerformancePanel stats={perfData} />}
        {tab === "jobs"        && <JobsMonitor />}
      </div>
    </div>
  );
}

// ── Jobs Monitor ──────────────────────────────────────────────────────────────

function JobsMonitor() {
  type Job = {
    job_id: string; kind: string; status: string;
    progress: number; error?: string;
    created_at: string; started_at?: string; finished_at?: string;
  };
  const [jobs, setJobs]       = useState<Job[]>([]);
  const [stats, setStats]     = useState<Record<string, number> | null>(null);
  const [loading, setLoading] = useState(true);
  const [now, setNow]         = useState(() => Date.now());

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [jr, sr] = await Promise.all([
        apiFetch("/jobs").then(r => r.json()).catch(() => ({ jobs: [] })),
        apiFetch("/jobs/stats").then(r => r.json()).catch(() => ({})),
      ]);
      setJobs(jr.jobs ?? []);
      setStats(sr);
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const cancel = async (job_id: string) => {
    await apiFetch(`/jobs/${job_id}`, { method: "DELETE" }).catch(() => {});
    load();
  };

  const STATUS_COLOR: Record<string, string> = {
    pending:   "#f59e0b",
    running:   "#6c8ef7",
    completed: "#34d399",
    failed:    "#ef4444",
    cancelled: "#6b7280",
  };

  const elapsed = (job: Job, now: number) => {
    const start = job.started_at ? new Date(job.started_at).getTime() : new Date(job.created_at).getTime();
    const end   = job.finished_at ? new Date(job.finished_at).getTime() : now;
    const s     = Math.round((end - start) / 1000);
    return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m${s % 60}s`;
  };

  return (
    <div style={S.card}>
      <div style={S.cardHeader}>
        <span>⚙ Background Jobs</span>
        <button onClick={load} disabled={loading} style={{ ...S.btn("ghost"), padding: "4px 10px", fontSize: 11 }}>
          {loading ? "…" : "↻"}
        </button>
      </div>
      <div style={S.cardBody}>
        {/* Stats row */}
        {stats && (
          <div style={{ display: "flex", gap: 20, marginBottom: 16, flexWrap: "wrap" as const }}>
            {Object.entries(stats).map(([k, v]) => (
              <StatPill key={k} label={k} value={v}
                color={k === "failed" ? "#ef4444" : k === "running" ? "#6c8ef7" : k === "completed" ? "#34d399" : "var(--accent)"} />
            ))}
          </div>
        )}

        {loading ? (
          <div style={{ color: "var(--t3)", fontSize: 13 }}>Loading…</div>
        ) : jobs.length === 0 ? (
          <div style={{ color: "var(--t3)", fontSize: 13, textAlign: "center", padding: "20px 0" }}>
            No jobs yet — jobs created via the API appear here.
          </div>
        ) : jobs.map(job => {
          const color = STATUS_COLOR[job.status] ?? "var(--t4)";
          return (
            <div key={job.job_id} style={{ padding: "10px 0", borderBottom: "1px solid var(--border)", display: "flex", gap: 12, alignItems: "center" }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 4 }}>
                  <span style={{ fontSize: 12, fontWeight: 600, color: "var(--accent)" }}>{job.kind}</span>
                  <span style={{ fontSize: 10, fontWeight: 700, color, background: color + "18", border: `1px solid ${color}33`, padding: "1px 7px", borderRadius: 99 }}>
                    {job.status}
                  </span>
                  <span style={{ fontSize: 10, color: "var(--t4)" }}>{elapsed(job, now)}</span>
                </div>
                {job.status === "running" && (
                  <div style={{ height: 3, background: "var(--bg-base)", borderRadius: 99, overflow: "hidden" }}>
                    <div style={{ height: "100%", width: `${job.progress}%`, background: "#6c8ef7", borderRadius: 99, transition: "width .4s" }} />
                  </div>
                )}
                {job.error && <div style={{ fontSize: 11, color: "#ef4444", marginTop: 2 }}>{job.error}</div>}
              </div>
              <span style={{ ...S.mono, fontSize: 10, color: "var(--t5)", flexShrink: 0 }}>{job.job_id.slice(0, 8)}…</span>
              {(job.status === "pending" || job.status === "running") && (
                <button onClick={() => cancel(job.job_id)} style={{ ...S.btn("danger"), padding: "3px 10px", fontSize: 11 }}>
                  Cancel
                </button>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
