/**
 * BillingPage — tab shell for Subscription/Usage/Invoices/Payment Methods/
 * Billing History. Data: GET /api/plans, GET /api/orgs/{id}/billing (both
 * fetched here and passed down; each tab fetches its own history data).
 */
import { useState, useEffect, useCallback } from "react";
import { apiFetch, parseJSON } from "../../shared/utils/api";
import { useToast } from "../../contexts/toast";
import { useOrg } from "../../contexts/OrgContext";
import { S } from "../../styles/theme";
import { EmptyState } from "../../shared/ui/EmptyState";
import { StatusBadge } from "../../shared/ui/StatusBadge";
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

  useEffect(() => { void Promise.resolve().then(load); }, [load]);
  // Reset the tab when the org changes — during render, per React's
  // "adjusting state when a prop changes" pattern (no extra effect pass).
  const [prevOrgId, setPrevOrgId] = useState(currentOrgId);
  if (prevOrgId !== currentOrgId) { setPrevOrgId(currentOrgId); setTab("subscription"); }

  if (!currentOrgId) {
    return (
      <EmptyState
        icon={<span style={{ fontSize: 40 }}>💳</span>}
        title="No organization selected"
        description={orgs.length === 0 ? "Create an organization first." : "Pick one from the Organizations page."}
      />
    );
  }

  return (
    <>
      <header style={S.header}>
        <span style={S.headerTitle}>Billing — {currentOrg?.name ?? "…"}</span>
        {billing && (
          <StatusBadge
            kind={billing.has_access ? "success" : "warning"}
            label={`${billing.plan.toUpperCase()} · ${billing.status}`}
          />
        )}
      </header>

      <div role="tablist" aria-label="Billing sections" style={{ display: "flex", gap: 6, padding: "12px 24px 0" }}>
        {TABS.map(t => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            onClick={() => setTab(t.id)}
            style={{
              padding: "7px 14px", borderRadius: 8, border: "none", cursor: "pointer", fontSize: 12, fontWeight: 500,
              background: tab === t.id ? "var(--accent-dim)" : "rgba(255,255,255,.04)",
              color: tab === t.id ? "var(--accent-2)" : "var(--t4)",
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
