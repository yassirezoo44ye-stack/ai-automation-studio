/**
 * BillingPage — tab shell for Subscription/Usage/Invoices/Payment Methods/
 * Billing History. Data: GET /api/plans, GET /api/orgs/{id}/billing (both
 * fetched here and passed down; each tab fetches its own history data).
 */
import { useState, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
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

const TAB_IDS: Tab[] = ["subscription", "usage", "invoices", "payment_methods", "history"];

export function BillingPage() {
  const { t } = useTranslation("billing");
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
      toast(t("toast.loadFailed"), "err");
    } finally { setLoading(false); }
  }, [currentOrgId, toast, t]);

  useEffect(() => { void Promise.resolve().then(load); }, [load]);
  // Reset the tab when the org changes — during render, per React's
  // "adjusting state when a prop changes" pattern (no extra effect pass).
  const [prevOrgId, setPrevOrgId] = useState(currentOrgId);
  if (prevOrgId !== currentOrgId) { setPrevOrgId(currentOrgId); setTab("subscription"); }

  if (!currentOrgId) {
    return (
      <EmptyState
        icon={<span style={{ fontSize: 40 }}>💳</span>}
        title={t("noOrg.title")}
        description={orgs.length === 0 ? t("noOrg.descriptionNoOrgs") : t("noOrg.descriptionHasOrgs")}
      />
    );
  }

  return (
    <>
      <header style={S.header}>
        <span style={S.headerTitle}>{t("header.title", { orgName: currentOrg?.name ?? "…" })}</span>
        {billing && (
          <StatusBadge
            kind={billing.has_access ? "success" : "warning"}
            label={`${billing.plan.toUpperCase()} · ${billing.status}`}
          />
        )}
      </header>

      <div role="tablist" aria-label={t("tabsAriaLabel")} style={{ display: "flex", gap: 6, padding: "12px 24px 0" }}>
        {TAB_IDS.map(id => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={tab === id}
            onClick={() => setTab(id)}
            style={{
              padding: "7px 14px", borderRadius: 8, border: "none", cursor: "pointer", fontSize: 12, fontWeight: 500,
              background: tab === id ? "var(--accent-dim)" : "var(--bg-card)",
              color: tab === id ? "var(--accent-2)" : "var(--t4)",
            }}
          >
            {t(`tabs.${id}`)}
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
