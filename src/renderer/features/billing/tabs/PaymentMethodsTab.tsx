/**
 * PaymentMethodsTab — cached payment-method display + Stripe Portal link.
 * Data: GET /api/orgs/{id}/billing/payment-methods, POST .../payment-methods/sync
 * Adding/changing a card happens exclusively through the Stripe Customer
 * Portal — no card form is built here (see SubscriptionTab's portal button).
 */
import { useState, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { apiFetch, parseJSON } from "../../../shared/utils/api";
import { useToast } from "../../../contexts/toast";
import { GoldButton, GlassCard } from "../../../shared/ui/gold";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { StatusBadge } from "../../../shared/ui/StatusBadge";

interface PaymentMethod {
  id: string; brand: string | null; last4: string | null;
  exp_month: number | null; exp_year: number | null; is_default: boolean;
}

export function PaymentMethodsTab({ currentOrgId }: { currentOrgId: string }) {
  const { t } = useTranslation("billing");
  const toast = useToast();
  const [methods, setMethods] = useState<PaymentMethod[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [openingPortal, setOpeningPortal] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(false);
    try {
      const r = await apiFetch(`/api/orgs/${currentOrgId}/billing/payment-methods`);
      if (!r.ok) throw new Error();
      const d = await parseJSON<{ payment_methods: PaymentMethod[] }>(r, "/billing/payment-methods");
      setMethods(d.payment_methods);
    } catch {
      toast(t("paymentMethodsTab.loadFailedToast"), "err");
      setMethods([]);
      setError(true);
    } finally { setLoading(false); }
  }, [currentOrgId, toast, t]);

  useEffect(() => { void Promise.resolve().then(load); }, [load]);

  const sync = async () => {
    setSyncing(true);
    try {
      const r = await apiFetch(`/api/orgs/${currentOrgId}/billing/payment-methods/sync`, { method: "POST" });
      if (!r.ok) throw new Error();
      const d = await parseJSON<{ payment_methods: PaymentMethod[] }>(r, "sync");
      setMethods(d.payment_methods);
      toast(t("paymentMethodsTab.refreshedToast"), "ok");
    } catch {
      toast(t("paymentMethodsTab.refreshFailedToast"), "err");
    } finally { setSyncing(false); }
  };

  const openPortal = async () => {
    setOpeningPortal(true);
    try {
      const r = await apiFetch(`/api/orgs/${currentOrgId}/billing/portal`, { method: "POST" });
      if (!r.ok) {
        const e = await parseJSON<{ detail?: string }>(r, "portal").catch(() => ({ detail: undefined }));
        throw new Error(e.detail || t("paymentMethodsTab.portalOpenFailed"));
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
      <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
        <GoldButton variant="ghost" onClick={() => void sync()} disabled={syncing}>
          {syncing ? t("paymentMethodsTab.refreshing") : t("paymentMethodsTab.refresh")}
        </GoldButton>
        <GoldButton onClick={() => void openPortal()} disabled={openingPortal}>
          {openingPortal ? t("paymentMethodsTab.opening") : t("paymentMethodsTab.manageInStripe")}
        </GoldButton>
      </div>

      {loading ? (
        <div className="skeleton" style={{ height: 100, borderRadius: 16 }} />
      ) : error ? (
        <EmptyState
          icon={<span style={{ fontSize: 40 }}>⚠️</span>}
          title={t("paymentMethodsTab.loadErrorTitle")}
          description={t("paymentMethodsTab.loadErrorDescription")}
          action={<GoldButton variant="ghost" onClick={() => void load()}>{t("paymentMethodsTab.retry")}</GoldButton>}
        />
      ) : methods.length === 0 ? (
        <EmptyState
          icon={<span style={{ fontSize: 40 }}>💳</span>}
          title={t("paymentMethodsTab.emptyTitle")}
          description={t("paymentMethodsTab.emptyDescription")}
        />
      ) : (
        <GlassCard lift={false}>
          {methods.map((m, i) => (
            <div key={m.id} style={{
              padding: "12px 4px", borderTop: i > 0 ? "1px solid var(--border)" : "none",
              display: "flex", alignItems: "center", gap: 12,
            }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: "var(--t1)", textTransform: "capitalize" }}>
                  {m.brand ?? t("paymentMethodsTab.cardFallback")} •••• {m.last4 ?? "----"}
                </div>
                <div style={{ fontSize: 11, color: "var(--t4)" }}>
                  {m.exp_month && m.exp_year ? t("paymentMethodsTab.expires", { month: m.exp_month, year: m.exp_year }) : ""}
                </div>
              </div>
              {m.is_default && <StatusBadge kind="success" label={t("paymentMethodsTab.default")} />}
            </div>
          ))}
        </GlassCard>
      )}
    </div>
  );
}
