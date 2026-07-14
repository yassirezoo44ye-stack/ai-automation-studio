/**
 * SubscriptionTab — plan cards + upgrade flow + Stripe Customer Portal link.
 * Data: GET /api/plans, POST /api/orgs/{id}/billing/checkout, POST .../billing/portal
 */
import { useState } from "react";
import { apiFetch, parseJSON } from "../../../shared/utils/api";
import { useToast } from "../../../contexts/ToastContext";
import { S } from "../../../styles/theme";

interface PlanDTO {
  id: string; name: string; price_monthly_usd: number;
  limits: Record<string, number>; features: string[]; trial_days: number;
}

interface BillingSummary {
  plan: string; status: string; has_access: boolean;
  purchasable_plans: string[];
}

function fmt(n: number): string {
  if (n < 0) return "∞";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

export function SubscriptionTab({
  currentOrgId, billing, plans,
}: {
  currentOrgId: string; billing: BillingSummary | null; plans: PlanDTO[];
}) {
  const toast = useToast();
  const [upgrading, setUpgrading] = useState<string | null>(null);
  const [openingPortal, setOpeningPortal] = useState(false);

  const upgrade = async (planId: string) => {
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
      window.location.assign(d.url);
    } catch (e) {
      toast((e as Error).message, "err");
      setUpgrading(null);
    }
  };

  const openPortal = async () => {
    setOpeningPortal(true);
    try {
      const r = await apiFetch(`/api/orgs/${currentOrgId}/billing/portal`, { method: "POST" });
      if (!r.ok) {
        const e = await parseJSON<{ detail?: string }>(r, "portal").catch(() => ({ detail: undefined }));
        throw new Error(e.detail || "Could not open billing portal");
      }
      const d = await parseJSON<{ url: string }>(r, "portal");
      window.location.href = d.url;
    } catch (e) {
      toast((e as Error).message, "err");
      setOpeningPortal(false);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {billing && billing.plan !== "free" && (
        <div style={{ ...S.card, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div>
            <div style={{ fontSize: 13, fontWeight: 600, color: "var(--t1)" }}>Manage your subscription</div>
            <div style={{ fontSize: 11, color: "var(--t4)", marginTop: 2 }}>
              Change plan, update your payment method, or cancel — handled securely by Stripe.
            </div>
          </div>
          <button onClick={() => void openPortal()} disabled={openingPortal} style={S.btnSecondary}>
            {openingPortal ? "Opening…" : "Manage in Stripe Portal"}
          </button>
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
                  {p.trial_days > 0 && !isCurrent && <> · {p.trial_days}-day trial</>}
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
    </div>
  );
}
