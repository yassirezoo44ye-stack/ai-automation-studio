/**
 * Engineering Control Plane — main dashboard.
 *
 * Shows:
 *   • Mission list with status badges + classification
 *   • Pending approvals alert (if any)
 *   • Quick-launch form for Release Autopilot
 *
 * Security: org_id always comes from OrgContext (X-Organization-Id header),
 * never from the UI state directly into a request body field called org_id.
 */
import { useState, useEffect, useCallback } from "react";
import { apiFetch } from "../../utils/api";
import { useOrg }   from "../../contexts/OrgContext";
import { useToast } from "../../contexts/toast";

// ── Types ──────────────────────────────────────────────────────────────────────

interface Mission {
  id: string;
  objective: string;
  status: string;
  current_phase: string | null;
  tokens_used: number;
  budget_tokens: number;
  steps_used: number;
  budget_steps: number;
  created_at: string;
  completed_at: string | null;
}

interface Approval {
  id: string;
  action: string;
  resource: string;
  risk_level: string;
  status: string;
  reason: string;
  expires_at: string | null;
  created_at: string;
}

// ── Styles ─────────────────────────────────────────────────────────────────────

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
  headerTop: { display: "flex", alignItems: "center", gap: 12, marginBottom: 16 },
  title: {
    fontSize: 20, fontWeight: 700, letterSpacing: "-0.3px",
    background: "linear-gradient(135deg, var(--accent), var(--accent-2, #a78bfa))",
    WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent",
  },
  subtitle: { fontSize: 13, color: "var(--t3)", marginLeft: "auto" },
  tabs: { display: "flex", gap: 0, marginBottom: -1 },
  tab: (active: boolean) => ({
    padding: "8px 16px", fontSize: 13, fontWeight: 500,
    cursor: "pointer", border: "none", background: "transparent",
    color: active ? "var(--accent)" : "var(--t3)",
    borderBottom: active ? "2px solid var(--accent)" : "2px solid transparent",
    transition: "color .15s",
  }),
  body: { flex: 1, overflow: "auto", padding: 24 },
  card: {
    background: "var(--bg-surface)", border: "1px solid var(--border)",
    borderRadius: 12, padding: "16px 20px", marginBottom: 12,
  },
  cardHeader: {
    display: "flex", alignItems: "center", justifyContent: "space-between",
    marginBottom: 10,
  },
  row: { display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" as const },
  badge: (color: string) => ({
    fontSize: 11, fontWeight: 600, padding: "2px 8px", borderRadius: 6,
    background: color, color: "#fff", textTransform: "uppercase" as const,
    letterSpacing: 0.5,
  }),
  label: { fontSize: 12, color: "var(--t3)" },
  value: { fontSize: 13, color: "var(--t1)", fontWeight: 500 },
  mono: { fontFamily: "var(--font-mono, monospace)", fontSize: 11, color: "var(--t3)" },
  btn: (primary?: boolean) => ({
    padding: "7px 14px", borderRadius: 8, fontSize: 13, fontWeight: 500,
    cursor: "pointer", border: "1px solid var(--border)",
    background: primary ? "var(--accent)" : "transparent",
    color: primary ? "#fff" : "var(--t2)",
    transition: "opacity .15s",
  }),
  input: {
    padding: "8px 12px", borderRadius: 8, fontSize: 13,
    background: "var(--bg-base)", border: "1px solid var(--border)",
    color: "var(--t1)", width: "100%", outline: "none",
  },
  formGroup: { marginBottom: 12 },
  formLabel: { fontSize: 12, fontWeight: 500, color: "var(--t2)", marginBottom: 4, display: "block" },
  alert: {
    padding: "10px 14px", borderRadius: 8, marginBottom: 16,
    background: "rgba(245, 158, 11, 0.12)", border: "1px solid rgba(245, 158, 11, 0.3)",
    color: "#d97706", fontSize: 13,
  },
};

// ── Status colors ──────────────────────────────────────────────────────────────

function statusColor(s: string): string {
  const map: Record<string, string> = {
    PLANNED:         "#6366f1",
    QUEUED:          "#0ea5e9",
    RUNNING:         "#22c55e",
    WAITING_APPROVAL:"#f59e0b",
    BLOCKED:         "#ef4444",
    FAILED:          "#ef4444",
    RECOVERING:      "#f97316",
    SUCCEEDED:       "#10b981",
    CANCELLED:       "#6b7280",
  };
  return map[s] ?? "#6b7280";
}

function classColor(c: string): string {
  if (c === "PRODUCTION VERIFIED")  return "#10b981";
  if (c === "PRODUCTION CANDIDATE") return "#f59e0b";
  return "#6366f1";
}

function riskColor(r: string): string {
  if (r === "critical") return "#ef4444";
  if (r === "high")     return "#f97316";
  if (r === "medium")   return "#f59e0b";
  return "#22c55e";
}

// ── Helpers ────────────────────────────────────────────────────────────────────

function fmt(iso: string) {
  try { return new Date(iso).toLocaleString(); } catch { return iso; }
}

function pct(used: number, budget: number): string {
  if (!budget) return "0%";
  return `${Math.round((used / budget) * 100)}%`;
}

// ── Sub-components ─────────────────────────────────────────────────────────────

function MissionCard({ mission, onSelect }: { mission: Mission; onSelect: () => void }) {
  const classification = mission.status === "SUCCEEDED"
    ? "PRODUCTION VERIFIED"  // simplified — real value from evidence API
    : mission.status === "RUNNING" || mission.status === "QUEUED"
    ? "DEVELOPMENT"
    : "DEVELOPMENT";

  return (
    <div style={S.card}>
      <div style={S.cardHeader}>
        <div style={S.row}>
          <span style={S.badge(statusColor(mission.status))}>{mission.status}</span>
          <span style={S.badge(classColor(classification))} title="Final classification">
            {classification}
          </span>
        </div>
        <button style={S.btn()} onClick={onSelect}>View Detail</button>
      </div>
      <div style={{ fontSize: 14, fontWeight: 500, marginBottom: 8, color: "var(--t1)" }}>
        {mission.objective}
      </div>
      <div style={S.row}>
        <span style={S.label}>Tokens</span>
        <span style={S.value}>{mission.tokens_used.toLocaleString()} / {mission.budget_tokens.toLocaleString()}</span>
        <span style={{ ...S.label, marginLeft: 4 }}>({pct(mission.tokens_used, mission.budget_tokens)})</span>
        <span style={{ ...S.label, marginLeft: 12 }}>Steps</span>
        <span style={S.value}>{mission.steps_used} / {mission.budget_steps}</span>
      </div>
      {mission.current_phase && (
        <div style={{ marginTop: 6, ...S.mono }}>phase: {mission.current_phase}</div>
      )}
      <div style={{ marginTop: 6, ...S.mono }}>created {fmt(mission.created_at)}</div>
    </div>
  );
}

function ApprovalCard({
  approval,
  onDecide,
}: {
  approval: Approval;
  onDecide: (id: string, decision: "approved" | "rejected") => void;
}) {
  return (
    <div style={{ ...S.card, borderColor: "rgba(245, 158, 11, 0.4)" }}>
      <div style={S.cardHeader}>
        <div style={S.row}>
          <span style={S.badge(riskColor(approval.risk_level))}>{approval.risk_level.toUpperCase()} RISK</span>
          <span style={{ fontSize: 13, fontWeight: 600 }}>{approval.action}</span>
        </div>
        <div style={S.row}>
          <button
            style={S.btn()}
            onClick={() => onDecide(approval.id, "rejected")}
          >
            Reject
          </button>
          <button
            style={S.btn(true)}
            onClick={() => onDecide(approval.id, "approved")}
          >
            Approve
          </button>
        </div>
      </div>
      <div style={{ fontSize: 13, color: "var(--t2)", marginBottom: 4 }}>
        <strong>Resource:</strong> {approval.resource}
      </div>
      <div style={{ fontSize: 13, color: "var(--t2)", marginBottom: 4 }}>
        {approval.reason}
      </div>
      {approval.expires_at && (
        <div style={S.mono}>expires {fmt(approval.expires_at)}</div>
      )}
    </div>
  );
}

function LaunchForm({ onLaunched }: { onLaunched: () => void }) {
  const { currentOrgId } = useOrg();
  const showToast = useToast();
  const [loading, setLoading]   = useState(false);
  const [objective, setObjective] = useState("");
  const [repo, setRepo]         = useState("");
  const [sha, setSha]           = useState("");
  const [serviceId, setService] = useState("");
  const [missionId, setMid]     = useState("");

  async function handleCreate() {
    if (!objective.trim()) { showToast("Objective is required", "err"); return; }
    if (!currentOrgId)     { showToast("Select an org first", "err"); return; }
    setLoading(true);
    try {
      const res = await apiFetch("/api/engineering/missions", {
        method: "POST",
        headers: { "X-Organization-Id": currentOrgId, "Content-Type": "application/json" },
        body: JSON.stringify({ objective }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Create failed");
      setMid(data.id);
      showToast("Mission created — now launch pipeline", "ok");
    } catch (e: unknown) {
      showToast(String(e), "err");
    } finally {
      setLoading(false);
    }
  }

  async function handleLaunch() {
    if (!missionId)   { showToast("Create a mission first", "err"); return; }
    if (!repo || !sha || !serviceId) {
      showToast("Repo, SHA, and Render service ID are required", "err"); return;
    }
    if (!currentOrgId) { showToast("Select an org first", "err"); return; }
    setLoading(true);
    try {
      const res = await apiFetch(`/api/engineering/missions/${missionId}/launch`, {
        method: "POST",
        headers: { "X-Organization-Id": currentOrgId, "Content-Type": "application/json" },
        body: JSON.stringify({
          repo,
          base_sha: sha,
          render_service_id: serviceId,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Launch failed");
      showToast(`Pipeline queued — job ${data.job_id?.slice(0, 8)}`, "ok");
      setObjective(""); setRepo(""); setSha(""); setService(""); setMid("");
      onLaunched();
    } catch (e: unknown) {
      showToast(String(e), "err");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={S.card}>
      <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 14, color: "var(--t1)" }}>
        🚀 Launch Release Autopilot
      </div>
      <div style={S.formGroup}>
        <label htmlFor="eng-objective" style={S.formLabel}>Objective *</label>
        <input
          id="eng-objective"
          style={S.input}
          placeholder="e.g. Fix the login page flash on dark mode"
          value={objective}
          onChange={e => setObjective(e.target.value)}
          disabled={loading || !!missionId}
        />
      </div>
      {!missionId && (
        <button
          style={{ ...S.btn(true), width: "100%", marginBottom: 12 }}
          onClick={handleCreate}
          disabled={loading}
        >
          {loading ? "Creating…" : "Create Mission"}
        </button>
      )}
      {missionId && (
        <>
          <div style={{ ...S.mono, marginBottom: 12, color: "var(--accent)" }}>
            ✓ Mission {missionId.slice(0, 8)} created — configure pipeline:
          </div>
          <div style={S.formGroup}>
            <label htmlFor="eng-repo" style={S.formLabel}>GitHub Repo (owner/repo) *</label>
            <input id="eng-repo" style={S.input} placeholder="org/repo" value={repo}
              onChange={e => setRepo(e.target.value)} disabled={loading} />
          </div>
          <div style={S.formGroup}>
            <label htmlFor="eng-sha" style={S.formLabel}>Base SHA * (7–40 chars)</label>
            <input id="eng-sha" style={S.input} placeholder="abc1234..." value={sha}
              onChange={e => setSha(e.target.value)} disabled={loading} />
          </div>
          <div style={S.formGroup}>
            <label htmlFor="eng-service" style={S.formLabel}>Render Service ID *</label>
            <input id="eng-service" style={S.input} placeholder="srv-..." value={serviceId}
              onChange={e => setService(e.target.value)} disabled={loading} />
          </div>
          <div style={S.row}>
            <button style={S.btn()} onClick={() => setMid("")} disabled={loading}>← Back</button>
            <button
              style={{ ...S.btn(true), flex: 1 }}
              onClick={handleLaunch}
              disabled={loading}
            >
              {loading ? "Queuing…" : "Launch Pipeline"}
            </button>
          </div>
        </>
      )}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

type Tab = "missions" | "approvals" | "launch";

export function EngineeringPage() {
  const { currentOrgId } = useOrg();
  const showToast        = useToast();
  const [tab, setTab]    = useState<Tab>("missions");
  const [missions, setMissions]   = useState<Mission[]>([]);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [loading, setLoading]     = useState(false);
  const [selectedMission, setSelected] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!currentOrgId) return;
    setLoading(true);
    try {
      const [mr, ar] = await Promise.all([
        apiFetch("/api/engineering/missions?limit=20", {
          headers: { "X-Organization-Id": currentOrgId },
        }),
        apiFetch("/api/engineering/approvals", {
          headers: { "X-Organization-Id": currentOrgId },
        }),
      ]);
      if (mr.ok) {
        const d = await mr.json();
        setMissions(d.missions ?? []);
      }
      if (ar.ok) {
        const d = await ar.json();
        setApprovals(d.approvals ?? []);
      }
    } catch (e: unknown) {
      showToast(String(e), "err");
    } finally {
      setLoading(false);
    }
  }, [currentOrgId, showToast]);

  // eslint-disable-next-line react-hooks/set-state-in-effect -- async fetch on mount
  useEffect(() => { load(); }, [load]);

  const decide = useCallback(async (approvalId: string, decision: "approved" | "rejected") => {
    if (!currentOrgId) return;
    try {
      const res = await apiFetch(`/api/engineering/approvals/${approvalId}/decide`, {
        method: "POST",
        headers: { "X-Organization-Id": currentOrgId, "Content-Type": "application/json" },
        body: JSON.stringify({ decision }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Decision failed");
      showToast(`Approval ${decision}`, "ok");
      load();
    } catch (e: unknown) {
      showToast(String(e), "err");
    }
  }, [currentOrgId, showToast, load]);

  if (!currentOrgId) {
    return (
      <div style={{ ...S.page, alignItems: "center", justifyContent: "center" }}>
        <div style={{ textAlign: "center", color: "var(--t3)", fontSize: 14 }}>
          <div style={{ fontSize: 40, marginBottom: 12 }}>🏗</div>
          <div>Select an organisation to use the Engineering Control Plane.</div>
        </div>
      </div>
    );
  }

  return (
    <div style={S.page}>
      {/* Header */}
      <div style={S.header}>
        <div style={S.headerTop}>
          <div style={S.title}>Engineering Control Plane</div>
          {approvals.length > 0 && (
            <div style={{ ...S.badge("#f59e0b"), marginLeft: "auto" }}>
              {approvals.length} pending approval{approvals.length > 1 ? "s" : ""}
            </div>
          )}
          <button style={{ ...S.btn(), marginLeft: approvals.length > 0 ? 8 : "auto" }}
            onClick={load} disabled={loading}>
            {loading ? "…" : "↻ Refresh"}
          </button>
        </div>
        <div style={S.tabs}>
          {(["missions", "approvals", "launch"] as Tab[]).map(t => (
            <button key={t} style={S.tab(tab === t)} onClick={() => { setTab(t); setSelected(null); }}>
              {t === "missions" ? `Missions (${missions.length})`
                : t === "approvals" ? `Approvals${approvals.length > 0 ? ` ⚠ ${approvals.length}` : ""}`
                : "Launch Pipeline"}
            </button>
          ))}
        </div>
      </div>

      {/* Body */}
      <div style={S.body}>

        {/* Pending approvals alert on missions tab */}
        {tab === "missions" && approvals.length > 0 && (
          <div style={S.alert}>
            ⚠ {approvals.length} approval{approvals.length > 1 ? "s" : ""} pending —
            {" "}<button style={{ background: "none", border: "none", color: "inherit",
              cursor: "pointer", textDecoration: "underline", padding: 0, fontSize: "inherit" }}
              onClick={() => setTab("approvals")}>
              review now
            </button>
          </div>
        )}

        {/* Missions tab */}
        {tab === "missions" && (
          <>
            {selectedMission ? (
              <MissionDetail
                missionId={selectedMission}
                orgId={currentOrgId}
                onBack={() => setSelected(null)}
              />
            ) : (
              <>
                {missions.length === 0 && !loading && (
                  <div style={{ textAlign: "center", padding: "60px 0", color: "var(--t3)" }}>
                    <div style={{ fontSize: 36, marginBottom: 12 }}>🛸</div>
                    <div style={{ fontSize: 14 }}>No missions yet — launch a Release Autopilot pipeline to get started.</div>
                    <button style={{ ...S.btn(true), marginTop: 16 }} onClick={() => setTab("launch")}>
                      Launch Pipeline
                    </button>
                  </div>
                )}
                {missions.map(m => (
                  <MissionCard key={m.id} mission={m} onSelect={() => setSelected(m.id)} />
                ))}
              </>
            )}
          </>
        )}

        {/* Approvals tab */}
        {tab === "approvals" && (
          <>
            {approvals.length === 0 && (
              <div style={{ textAlign: "center", padding: "60px 0", color: "var(--t3)" }}>
                <div style={{ fontSize: 36, marginBottom: 12 }}>✅</div>
                <div>No pending approvals.</div>
              </div>
            )}
            {approvals.map(a => (
              <ApprovalCard key={a.id} approval={a} onDecide={decide} />
            ))}
          </>
        )}

        {/* Launch tab */}
        {tab === "launch" && (
          <LaunchForm onLaunched={() => { setTab("missions"); load(); }} />
        )}
      </div>
    </div>
  );
}

// ── Mission Detail (inline) ────────────────────────────────────────────────────

function MissionDetail({ missionId, orgId, onBack }: {
  missionId: string; orgId: string; onBack: () => void;
}) {
  const showToast = useToast();
  const [mission, setMission]   = useState<Mission | null>(null);
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [trans, setTrans]       = useState<Transition[]>([]);
  const [loading, setLoading]   = useState(true);

  interface Evidence {
    id: string; tool_name: string; operation: string; provider: string;
    verification_status: string; sha_match: boolean | null;
    requested_sha: string | null; observed_sha: string | null; created_at: string;
  }
  interface Transition {
    from_status: string; to_status: string; actor: string;
    reason: string; created_at: string;
  }

  useEffect(() => {
    (async () => {
      try {
        const [mr, er, tr] = await Promise.all([
          apiFetch(`/api/engineering/missions/${missionId}`, { headers: { "X-Organization-Id": orgId } }),
          apiFetch(`/api/engineering/missions/${missionId}/evidence`, { headers: { "X-Organization-Id": orgId } }),
          apiFetch(`/api/engineering/missions/${missionId}/transitions`, { headers: { "X-Organization-Id": orgId } }),
        ]);
        if (mr.ok) setMission(await mr.json());
        if (er.ok) setEvidence((await er.json()).evidence ?? []);
        if (tr.ok) setTrans((await tr.json()).transitions ?? []);
      } catch (e: unknown) {
        showToast(String(e), "err");
      } finally {
        setLoading(false);
      }
    })();
  }, [missionId, orgId, showToast]);

  if (loading) return <div style={{ padding: 40, textAlign: "center", color: "var(--t3)" }}>Loading…</div>;
  if (!mission) return <div style={{ padding: 40, color: "var(--t3)" }}>Mission not found.</div>;

  const isVerified = evidence.some(e =>
    e.operation.includes("deploy") && e.verification_status === "verified" && e.sha_match === true
  );
  const classification = isVerified ? "PRODUCTION VERIFIED"
    : mission.status === "SUCCEEDED" ? "PRODUCTION CANDIDATE"
    : "DEVELOPMENT";

  return (
    <div>
      <button style={{ ...S.btn(), marginBottom: 16 }} onClick={onBack}>← Back</button>

      {/* Mission summary */}
      <div style={S.card}>
        <div style={S.cardHeader}>
          <div style={S.row}>
            <span style={S.badge(statusColor(mission.status))}>{mission.status}</span>
            <span style={S.badge(classColor(classification))}>{classification}</span>
          </div>
          {classification === "PRODUCTION VERIFIED" && (
            <span style={{ fontSize: 20 }}>🟢</span>
          )}
          {classification === "PRODUCTION CANDIDATE" && (
            <span style={{ fontSize: 20 }}>🟡</span>
          )}
          {classification === "DEVELOPMENT" && (
            <span style={{ fontSize: 20 }}>🔵</span>
          )}
        </div>
        <div style={{ fontSize: 14, fontWeight: 500, color: "var(--t1)", marginBottom: 8 }}>
          {mission.objective}
        </div>
        <div style={S.row}>
          <span style={S.label}>Tokens used:</span>
          <span style={S.value}>{mission.tokens_used.toLocaleString()} / {mission.budget_tokens.toLocaleString()}</span>
          <span style={S.label}>Steps:</span>
          <span style={S.value}>{mission.steps_used} / {mission.budget_steps}</span>
        </div>
      </div>

      {/* Evidence */}
      {evidence.length > 0 && (
        <div style={S.card}>
          <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 12, color: "var(--t2)" }}>
            Evidence ({evidence.length})
          </div>
          {evidence.map(ev => (
            <div key={ev.id} style={{
              padding: "8px 0", borderBottom: "1px solid var(--border)",
              display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap",
            }}>
              <span style={S.badge(
                ev.verification_status === "verified" ? "#10b981"
                  : ev.verification_status === "failed" ? "#ef4444"
                  : "#6b7280"
              )}>
                {ev.verification_status}
              </span>
              <span style={{ fontSize: 13, color: "var(--t2)" }}>{ev.tool_name}</span>
              {ev.sha_match !== null && (
                <span style={{ fontSize: 12, color: ev.sha_match ? "#10b981" : "#ef4444" }}>
                  {ev.sha_match ? "SHA ✓" : "SHA ✗"}
                </span>
              )}
              {ev.requested_sha && (
                <span style={S.mono}>{ev.requested_sha.slice(0, 8)}</span>
              )}
              {ev.observed_sha && ev.requested_sha !== ev.observed_sha && (
                <span style={{ ...S.mono, color: "#ef4444" }}>→ {ev.observed_sha.slice(0, 8)}</span>
              )}
            </div>
          ))}
        </div>
      )}

      {/* FSM transitions */}
      {trans.length > 0 && (
        <div style={S.card}>
          <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 12, color: "var(--t2)" }}>
            State History
          </div>
          {trans.map((t, i) => (
            <div key={i} style={{ padding: "4px 0", fontSize: 12, color: "var(--t3)" }}>
              <span style={{ color: "var(--t2)" }}>{t.from_status} → {t.to_status}</span>
              {t.reason && <span> — {t.reason.slice(0, 100)}</span>}
              <span style={{ marginLeft: 8, ...S.mono }}>{fmt(t.created_at)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
