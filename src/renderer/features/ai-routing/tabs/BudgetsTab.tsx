/**
 * BudgetsTab — usage vs. limit per metric, at org level or a finer
 * project/workflow/agent scope (app/billing/usage.py's budget granularity).
 * Data: GET /api/ai/budgets?project_id=&workflow_id=&agent_id=
 * Set:  PUT /api/orgs/{org_id}/usage/limits/{metric} (existing endpoint,
 *       extended with the same scope params — app/routers/usage_api.py).
 */
import { useEffect, useState, useCallback } from "react";
import { apiFetch, parseJSON } from "../../../shared/utils/api";
import { useToast } from "../../../contexts/toast";
import { GlassCard, GoldButton } from "../../../shared/ui/gold";
import { EmptyState } from "../../../shared/ui/EmptyState";

interface BudgetMetric { used: number; limit: number; pct: number | null }
interface BudgetsResponse {
  organization_id: string;
  scope: { project_id: string | null; workflow_id: string | null; agent_id: string | null };
  metrics: Record<string, BudgetMetric>;
}

const METRIC_LABEL: Record<string, string> = {
  tokens: "AI Tokens", workflow_executions: "Workflow Runs", api_requests: "API Requests",
  storage_mb: "Storage (MB)", embeddings: "Embeddings", marketplace_purchases: "Marketplace Purchases",
  seats: "Seats", active_users: "Active Users", running_agents: "Running Agents",
};

function fmt(n: number): string {
  if (n < 0) return "∞";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function BudgetRow({ orgId, metric, data, scope, onSaved }: {
  orgId: string; metric: string; data: BudgetMetric;
  scope: { project_id: string; workflow_id: string; agent_id: string };
  onSaved: () => void;
}) {
  const toast = useToast();
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(String(data.limit));
  const [saving, setSaving] = useState(false);

  const pct = data.pct ?? 0;
  const color = pct >= 90 ? "var(--red)" : pct >= 70 ? "var(--yellow)" : "var(--green)";

  const save = async () => {
    const trimmed = value.trim();
    const limit = Number(trimmed);
    if (trimmed === "" || !Number.isInteger(limit) || limit < -1) {
      toast("Limit must be -1 (unlimited) or a non-negative whole number", "err");
      return;
    }
    setSaving(true);
    try {
      const r = await apiFetch(`/api/orgs/${orgId}/usage/limits/${metric}`, {
        method: "PUT",
        body: JSON.stringify({ limit, ...scope }),
      });
      if (!r.ok) throw new Error();
      toast("Limit updated", "ok");
      setEditing(false);
      onSaved();
    } catch {
      toast("Could not update limit", "err");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 5 }}>
        <span style={{ fontSize: 12, color: "var(--t2)", fontWeight: 500 }}>{METRIC_LABEL[metric] ?? metric}</span>
        {editing ? (
          <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
            <input
              value={value} onChange={e => setValue(e.target.value)}
              className="g-input" style={{ width: 90, padding: "4px 8px", fontSize: 11 }}
            />
            <GoldButton onClick={() => void save()} disabled={saving} style={{ padding: "4px 10px", fontSize: 11 }}>
              {saving ? "…" : "Save"}
            </GoldButton>
            <GoldButton variant="ghost" onClick={() => setEditing(false)} style={{ padding: "4px 10px", fontSize: 11 }}>
              Cancel
            </GoldButton>
          </div>
        ) : (
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <span style={{ fontSize: 11, color: "var(--t4)" }}>{fmt(data.used)} / {fmt(data.limit)}</span>
            <GoldButton variant="ghost" onClick={() => { setValue(String(data.limit)); setEditing(true); }} style={{ padding: "3px 9px", fontSize: 10 }}>
              Edit
            </GoldButton>
          </div>
        )}
      </div>
      <div style={{ height: 6, background: "var(--bg-hover)", borderRadius: 99, overflow: "hidden" }}>
        <div style={{ height: "100%", width: `${Math.min(pct, 100)}%`, background: color, borderRadius: 99, transition: "width .4s" }} />
      </div>
    </div>
  );
}

export function BudgetsTab({ orgId }: { orgId: string }) {
  const toast = useToast();
  const [budgets, setBudgets] = useState<BudgetsResponse | null>(null);
  const [error, setError] = useState(false);
  const [projectId, setProjectId] = useState("");
  const [workflowId, setWorkflowId] = useState("");
  const [agentId, setAgentId] = useState("");

  const load = useCallback(async () => {
    setError(false);
    try {
      const params = new URLSearchParams();
      if (projectId) params.set("project_id", projectId);
      if (workflowId) params.set("workflow_id", workflowId);
      if (agentId) params.set("agent_id", agentId);
      const qs = params.toString();
      const r = await apiFetch(`/api/ai/budgets${qs ? `?${qs}` : ""}`);
      if (!r.ok) throw new Error();
      setBudgets(await parseJSON<BudgetsResponse>(r, "/api/ai/budgets"));
    } catch {
      toast("Could not load budgets", "err");
      setError(true);
    }
  }, [projectId, workflowId, agentId, toast]);

  useEffect(() => { void Promise.resolve().then(load); }, [load]);

  return (
    <div>
      <GlassCard lift={false} style={{ marginBottom: 16, display: "flex", gap: 10, alignItems: "flex-end", flexWrap: "wrap" }}>
        <div>
          <label className="g-label" htmlFor="budgets-project-id">Project ID</label>
          <input id="budgets-project-id" value={projectId} onChange={e => setProjectId(e.target.value)} placeholder="org-level" className="g-input" style={{ width: 160 }} />
        </div>
        <div>
          <label className="g-label" htmlFor="budgets-workflow-id">Workflow ID</label>
          <input id="budgets-workflow-id" value={workflowId} onChange={e => setWorkflowId(e.target.value)} placeholder="org-level" className="g-input" style={{ width: 160 }} />
        </div>
        <div>
          <label className="g-label" htmlFor="budgets-agent-id">Agent ID</label>
          <input id="budgets-agent-id" value={agentId} onChange={e => setAgentId(e.target.value)} placeholder="org-level" className="g-input" style={{ width: 160 }} />
        </div>
        <GoldButton variant="ghost" onClick={() => void load()} style={{ padding: "9px 16px" }}>View</GoldButton>
      </GlassCard>

      {error ? (
        <EmptyState
          icon={<span style={{ fontSize: 40 }}>⚠️</span>}
          title="Could not load budgets"
          description="Something went wrong reaching the server."
          action={<GoldButton variant="ghost" onClick={() => void load()}>Retry</GoldButton>}
        />
      ) : !budgets ? (
        <div className="skeleton" style={{ height: 200, borderRadius: 16 }} />
      ) : (
        <GlassCard lift={false}>
          <div style={{ fontSize: 14, fontWeight: 600, color: "var(--t1)", letterSpacing: "-0.1px", marginBottom: 14 }}>
            {projectId || workflowId || agentId ? "Scoped budget" : "Organization budget"}
          </div>
          {Object.entries(budgets.metrics).map(([metric, data]) => (
            <BudgetRow
              key={metric} orgId={orgId} metric={metric} data={data}
              scope={{ project_id: projectId, workflow_id: workflowId, agent_id: agentId }}
              onSaved={() => void load()}
            />
          ))}
        </GlassCard>
      )}
    </div>
  );
}
