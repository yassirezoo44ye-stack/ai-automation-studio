/**
 * BillingPage — tab shell for Subscription/Usage/Invoices/Payment Methods/
 * Billing History. Data: GET /api/plans, GET /api/orgs/{id}/billing (both
 * fetched here and passed down; each tab fetches its own history data).
 */
import { useState, useEffect, useCallback } from "react";
import { apiFetch, parseJSON } from "../../shared/utils/api";
import { useToast } from "../../contexts/ToastContext";
import { useOrg } from "../../contexts/OrgContext";
import { S } from "../../styles/theme";
import { SubscriptionTab } from "./tabs/SubscriptionTab";
import { UsageTab, type BillingUsage } from "./tabs/UsageTab";
import { InvoicesTab } from "./tabs/InvoicesTab";
import { PaymentMethodsTab } from "./tabs/PaymentMethodsTab";
import { BillingHistoryTab } from "./tabs/BillingHistoryTab";

interface PlanDTO {
  id: string; name: string; price_monthly_usd: number;
  limits: Record<string, number>; features: string[]; trial_days: number;
}

interface BillingDTO {
  plan: string; status: string; has_access: boolean; current_period_end: string | null;
  purchasable_plans: string[];
  usage: BillingUsage;
}

type Tab = "subscription" | "usage" | "invoices" | "payment_methods" | "history";

const TABS: { id: Tab; label: string }[] = [
  { id: "subscription", label: "Subscription" },
  { id: "usage", label: "Usage" },
  { id: "invoices", label: "Invoices" },
  { id: "payment_methods", label: "Payment Methods" },
  { id: "history", label: "Billing History" },
];

export function BillingPage() {
  const toast = useToast();
  const { currentOrgId, currentOrg, orgs } = useOrg();
  const [billing, setBilling] = useState<BillingDTO | null>(null);
  const [plans, setPlans] = useState<PlanDTO[]>([]);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<Tab>("subscription");

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
  useEffect(() => { setTab("subscription"); }, [currentOrgId]);

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
            color: billing.has_access ? "#34d399" : "#f59e0b",
            background: billing.has_access ? "rgba(52,211,153,.12)" : "rgba(245,158,11,.12)",
            border: `1px solid ${billing.has_access ? "rgba(52,211,153,.3)" : "rgba(245,158,11,.3)"}`,
          }}>
            {billing.plan.toUpperCase()} · {billing.status}
          </span>
        )}
      </header>

      <div style={{ display: "flex", gap: 6, padding: "12px 24px 0" }}>
        {TABS.map(t => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            style={{
              ...(tab === t.id ? S.btnPrimary : S.btnSecondary),
              padding: "7px 14px", fontSize: 12,
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div style={{ flex: 1, overflowY: "auto", padding: 24 }}>
        {loading ? (
          <div className="skeleton" style={{ height: 200, borderRadius: 16 }} />
        ) : tab === "subscription" ? (
          <SubscriptionTab currentOrgId={currentOrgId} billing={billing} plans={plans} />
        ) : tab === "usage" ? (
          <UsageTab usage={billing?.usage ?? null} />
        ) : tab === "invoices" ? (
          <InvoicesTab currentOrgId={currentOrgId} />
        ) : tab === "payment_methods" ? (
          <PaymentMethodsTab currentOrgId={currentOrgId} />
        ) : (
          <BillingHistoryTab currentOrgId={currentOrgId} />
        )}
      </div>
    </>
  );
}
