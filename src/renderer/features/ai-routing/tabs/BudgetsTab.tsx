/**
 * BudgetsTab — usage vs. limit per metric, at org level or a finer
 * project/workflow/agent scope (app/billing/usage.py's budget granularity).
 * Data: GET /api/ai/budgets?project_id=&workflow_id=&agent_id=
 * Set:  PUT /api/orgs/{org_id}/usage/limits/{metric} (existing endpoint,
 *       extended with the same scope params — app/routers/usage_api.py).
 */
import { useEffect, useState, useCallback } from "react";
import { useTranslation } from "react-i18next";
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
  const { t } = useTranslation("aiRouting");
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
      toast(t("budgetsTab.limitInvalid"), "err");
      return;
    }
    setSaving(true);
    try {
      const r = await apiFetch(`/api/orgs/${orgId}/usage/limits/${metric}`, {
        method: "PUT",
        body: JSON.stringify({ limit, ...scope }),
      });
      if (!r.ok) throw new Error();
      toast(t("budgetsTab.limitUpdated"), "ok");
      setEditing(false);
      onSaved();
    } catch {
      toast(t("budgetsTab.limitUpdateFailed"), "err");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 5 }}>
        <span style={{ fontSize: 12, color: "var(--t2)", fontWeight: 500 }}>{t(`budgetsTab.metrics.${metric}`, { defaultValue: metric })}</span>
        {editing ? (
          <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
            <input
              value={value} onChange={e => setValue(e.target.value)}
              className="g-input" style={{ width: 90, padding: "4px 8px", fontSize: 11 }}
            />
            <GoldButton onClick={() => void save()} disabled={saving} style={{ padding: "4px 10px", fontSize: 11 }}>
              {saving ? t("budgetsTab.saving") : t("budgetsTab.save")}
            </GoldButton>
            <GoldButton variant="ghost" onClick={() => setEditing(false)} style={{ padding: "4px 10px", fontSize: 11 }}>
              {t("budgetsTab.cancel")}
            </GoldButton>
          </div>
        ) : (
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <span style={{ fontSize: 11, color: "var(--t4)" }}>{fmt(data.used)} / {fmt(data.limit)}</span>
            <GoldButton variant="ghost" onClick={() => { setValue(String(data.limit)); setEditing(true); }} style={{ padding: "3px 9px", fontSize: 10 }}>
              {t("budgetsTab.edit")}
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
  const { t } = useTranslation("aiRouting");
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
      toast(t("budgetsTab.loadFailed"), "err");
      setError(true);
    }
  }, [projectId, workflowId, agentId, toast, t]);

  useEffect(() => { void Promise.resolve().then(load); }, [load]);

  return (
    <div>
      <GlassCard lift={false} style={{ marginBottom: 16, display: "flex", gap: 10, alignItems: "flex-end", flexWrap: "wrap" }}>
        <div>
          <label className="g-label" htmlFor="budgets-project-id">{t("budgetsTab.filters.projectId")}</label>
          <input id="budgets-project-id" value={projectId} onChange={e => setProjectId(e.target.value)} placeholder={t("budgetsTab.filters.placeholder")} className="g-input" style={{ width: 160 }} />
        </div>
        <div>
          <label className="g-label" htmlFor="budgets-workflow-id">{t("budgetsTab.filters.workflowId")}</label>
          <input id="budgets-workflow-id" value={workflowId} onChange={e => setWorkflowId(e.target.value)} placeholder={t("budgetsTab.filters.placeholder")} className="g-input" style={{ width: 160 }} />
        </div>
        <div>
          <label className="g-label" htmlFor="budgets-agent-id">{t("budgetsTab.filters.agentId")}</label>
          <input id="budgets-agent-id" value={agentId} onChange={e => setAgentId(e.target.value)} placeholder={t("budgetsTab.filters.placeholder")} className="g-input" style={{ width: 160 }} />
        </div>
        <GoldButton variant="ghost" onClick={() => void load()} style={{ padding: "9px 16px" }}>{t("budgetsTab.filters.view")}</GoldButton>
      </GlassCard>

      {error ? (
        <EmptyState
          icon={<span style={{ fontSize: 40 }}>⚠️</span>}
          title={t("budgetsTab.loadError.title")}
          description={t("budgetsTab.loadError.description")}
          action={<GoldButton variant="ghost" onClick={() => void load()}>{t("budgetsTab.loadError.retry")}</GoldButton>}
        />
      ) : !budgets ? (
        <div className="skeleton" style={{ height: 200, borderRadius: 16 }} />
      ) : (
        <GlassCard lift={false}>
          <div style={{ fontSize: 14, fontWeight: 600, color: "var(--t1)", letterSpacing: "-0.1px", marginBottom: 14 }}>
            {projectId || workflowId || agentId ? t("budgetsTab.scopedBudget") : t("budgetsTab.orgBudget")}
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
