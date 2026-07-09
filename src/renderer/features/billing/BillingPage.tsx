/**
 * BillingPage — current plan, usage meters, and upgrade flow.
 * Data: GET /api/plans, GET /api/orgs/{id}/billing, POST .../billing/checkout
 */
import { useState, useEffect, useCallback } from "react";
import { apiFetch, parseJSON } from "../../shared/utils/api";
import { useToast } from "../../contexts/ToastContext";
import { useOrg } from "../../contexts/OrgContext";
import { S } from "../../styles/theme";

interface PlanDTO {
  id: string; name: string; price_monthly_usd: number;
  limits: Record<string, number>; features: string[]; trial_days: number;
}

interface UsageMetric { used: number; limit: number; pct: number | null }

interface BillingDTO {
  plan: string; status: string; current_period_end: string | null;
  purchasable_plans: string[];
  usage: { period: string; metrics: Record<string, UsageMetric> };
}

const METRIC_LABEL: Record<string, string> = {
  tokens: "AI Tokens", workflow_executions: "Workflow Runs", api_requests: "API Requests",
  storage_mb: "Storage (MB)", embeddings: "Embeddings", marketplace_purchases: "Marketplace Purchases",
  seats: "Seats",
};

function fmt(n: number): string {
  if (n < 0) return "∞";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function UsageBar({ metric, data }: { metric: string; data: UsageMetric }) {
  const pct = data.pct ?? 0;
  const color = pct >= 90 ? "#ef4444" : pct >= 70 ? "#f59e0b" : "#34d399";
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 5 }}>
        <span style={{ fontSize: 12, color: "var(--t2)", fontWeight: 500 }}>{METRIC_LABEL[metric] ?? metric}</span>
        <span style={{ fontSize: 11, color: "var(--t4)" }}>{fmt(data.used)} / {fmt(data.limit)}</span>
      </div>
      <div style={{ height: 6, background: "rgba(255,255,255,.05)", borderRadius: 99, overflow: "hidden" }}>
        <div style={{ height: "100%", width: `${Math.min(pct, 100)}%`, background: color, borderRadius: 99, transition: "width .4s" }} />
      </div>
    </div>
  );
}

export function BillingPage() {
  const toast = useToast();
  const { currentOrgId, currentOrg, orgs } = useOrg();
  const [billing, setBilling] = useState<BillingDTO | null>(null);
  const [plans, setPlans] = useState<PlanDTO[]>([]);
  const [loading, setLoading] = useState(true);
  const [upgrading, setUpgrading] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!currentOrgId) { setLoading(false); return; }
    setLoading(true);
    try {
      const [br, pr] = await Promise.all([
        apiFetch(`/api/orgs/${currentOrgId}/billing`),
        apiFetch("/api/plans"),
      ]);
      if (br.ok) setBilling(await parseJSON<BillingDTO>(br, "/api/orgs/{id}/billing"));
      if (pr.ok) setPlans((await parseJSON<{ plans: PlanDTO[] }>(pr, "/api/plans")).plans);
    } catch {
      toast("Could not load billing info", "err");
    } finally { setLoading(false); }
  }, [currentOrgId, toast]);

  useEffect(() => { void load(); }, [load]);

  const upgrade = async (planId: string) => {
    if (!currentOrgId) return;
    setUpgrading(planId);
    try {
      const r = await apiFetch(`/api/orgs/${currentOrgId}/billing/checkout`, {
        method: "POST", body: JSON.stringify({ plan: planId }),
      });
      if (!r.ok) {
        const e = await parseJSON<{ detail?: string }>(r, "checkout").catch(() => ({ detail: undefined }));
        throw new Error(e.detail || "Checkout failed");
      }
      const d = await parseJSON<{ url: string }>(r, "checkout");
      window.location.href = d.url;
    } catch (e) {
      toast((e as Error).message, "err");
      setUpgrading(null);
    }
  };

  if (!currentOrgId) {
    return (
      <div className="empty-state" style={{ margin: "auto" }}>
        <div style={{ fontSize: 40 }}>💳</div>
        <h3>No organization selected</h3>
        <p>{orgs.length === 0 ? "Create an organization first." : "Pick one from the Organizations page."}</p>
      </div>
    );
  }

  return (
    <>
      <header style={S.header}>
        <span style={S.headerTitle}>Billing — {currentOrg?.name ?? "…"}</span>
        {billing && (
          <span style={{
            fontSize: 11, fontWeight: 700, padding: "3px 10px", borderRadius: 99,
            color: billing.status === "active" ? "#34d399" : "#f59e0b",
            background: billing.status === "active" ? "rgba(52,211,153,.12)" : "rgba(245,158,11,.12)",
            border: `1px solid ${billing.status === "active" ? "rgba(52,211,153,.3)" : "rgba(245,158,11,.3)"}`,
          }}>
            {billing.plan.toUpperCase()} · {billing.status}
          </span>
        )}
      </header>

      <div style={{ flex: 1, overflowY: "auto", padding: 24, display: "flex", flexDirection: "column", gap: 20 }}>
        {loading ? (
          <div className="skeleton" style={{ height: 200, borderRadius: 16 }} />
        ) : (
          <>
            {billing && (
              <div style={S.card}>
                <div style={{ ...S.cardTitle, marginBottom: 14 }}>Usage this period ({billing.usage.period})</div>
                {Object.entries(billing.usage.metrics).map(([metric, data]) => (
                  <UsageBar key={metric} metric={metric} data={data} />
                ))}
              </div>
            )}

            <div>
              <div className="section-label" style={{ marginBottom: 12 }}>PLANS</div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(220px,1fr))", gap: 12 }}>
                {plans.map(p => {
                  const isCurrent = p.id === billing?.plan;
                  const purchasable = billing?.purchasable_plans.includes(p.id);
                  return (
                    <div key={p.id} style={{
                      ...S.card, padding: "18px 20px",
                      border: isCurrent ? "1px solid var(--accent)" : S.card.border as string,
                    }}>
                      <div style={{ fontSize: 14, fontWeight: 700, color: "var(--t1)", marginBottom: 4 }}>{p.name}</div>
                      <div style={{ fontSize: 20, fontWeight: 700, color: "var(--t1)", marginBottom: 10 }}>
                        {p.price_monthly_usd > 0 ? `$${p.price_monthly_usd}` : p.id === "enterprise" ? "Custom" : "Free"}
                        {p.price_monthly_usd > 0 && <span style={{ fontSize: 11, fontWeight: 400, color: "var(--t4)" }}>/mo</span>}
                      </div>
                      <div style={{ fontSize: 11, color: "var(--t4)", marginBottom: 14, lineHeight: 1.6 }}>
                        {fmt(p.limits.tokens)} tokens · {fmt(p.limits.seats)} seats
                      </div>
                      {isCurrent ? (
                        <div style={{ ...S.btnSecondary, textAlign: "center", opacity: 0.6, cursor: "default" }}>Current Plan</div>
                      ) : purchasable ? (
                        <button
                          onClick={() => void upgrade(p.id)} disabled={!!upgrading}
                          style={{ ...S.btnPrimary, width: "100%" }}
                        >
                          {upgrading === p.id ? "Redirecting…" : "Upgrade"}
                        </button>
                      ) : p.id === "enterprise" ? (
                        <div style={{ ...S.btnSecondary, textAlign: "center" }}>Contact Sales</div>
                      ) : (
                        <div style={{ ...S.btnSecondary, textAlign: "center", opacity: 0.4, cursor: "not-allowed" }} title="Stripe price not configured">
                          Unavailable
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          </>
        )}
      </div>
    </>
  );
}
