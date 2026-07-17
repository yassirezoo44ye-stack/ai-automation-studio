/**
 * PaymentMethodsTab — cached payment-method display + Stripe Portal link.
 * Data: GET /api/orgs/{id}/billing/payment-methods, POST .../payment-methods/sync
 * Adding/changing a card happens exclusively through the Stripe Customer
 * Portal — no card form is built here (see SubscriptionTab's portal button).
 */
import { useState, useEffect, useCallback } from "react";
import { apiFetch, parseJSON } from "../../../shared/utils/api";
import { useToast } from "../../../contexts/toast";
import { S, C } from "../../../styles/theme";

interface PaymentMethod {
  id: string; brand: string | null; last4: string | null;
  exp_month: number | null; exp_year: number | null; is_default: boolean;
}

export function PaymentMethodsTab({ currentOrgId }: { currentOrgId: string }) {
  const toast = useToast();
  const [methods, setMethods] = useState<PaymentMethod[]>([]);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [openingPortal, setOpeningPortal] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await apiFetch(`/api/orgs/${currentOrgId}/billing/payment-methods`);
      if (!r.ok) throw new Error();
      const d = await parseJSON<{ payment_methods: PaymentMethod[] }>(r, "/billing/payment-methods");
      setMethods(d.payment_methods);
    } catch {
      toast("Could not load payment methods", "err");
      setMethods([]);
    } finally { setLoading(false); }
  }, [currentOrgId, toast]);

  useEffect(() => { void Promise.resolve().then(load); }, [load]);

  const sync = async () => {
    setSyncing(true);
    try {
      const r = await apiFetch(`/api/orgs/${currentOrgId}/billing/payment-methods/sync`, { method: "POST" });
      if (!r.ok) throw new Error();
      const d = await parseJSON<{ payment_methods: PaymentMethod[] }>(r, "sync");
      setMethods(d.payment_methods);
      toast("Payment methods refreshed", "ok");
    } catch {
      toast("Failed to refresh payment methods", "err");
    } finally { setSyncing(false); }
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
      <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
        <button onClick={() => void sync()} disabled={syncing} style={S.btnSecondary}>
          {syncing ? "Refreshing…" : "Refresh"}
        </button>
        <button onClick={() => void openPortal()} disabled={openingPortal} style={S.btnPrimary}>
          {openingPortal ? "Opening…" : "Manage in Stripe Portal"}
        </button>
      </div>

      {loading ? (
        <div className="skeleton" style={{ height: 100, borderRadius: 16 }} />
      ) : methods.length === 0 ? (
        <div className="empty-state">
          <div style={{ fontSize: 40 }}>💳</div>
          <h3>No payment method on file</h3>
          <p>Add one from the Stripe Portal above.</p>
        </div>
      ) : (
        <div style={S.card}>
          {methods.map((m, i) => (
            <div key={m.id} style={{
              padding: "12px 4px", borderTop: i > 0 ? "1px solid var(--border)" : "none",
              display: "flex", alignItems: "center", gap: 12,
            }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: "var(--t1)", textTransform: "capitalize" }}>
                  {m.brand ?? "Card"} •••• {m.last4 ?? "----"}
                </div>
                <div style={{ fontSize: 11, color: "var(--t4)" }}>
                  {m.exp_month && m.exp_year ? `Expires ${m.exp_month}/${m.exp_year}` : ""}
                </div>
              </div>
              {m.is_default && (
                <span style={{
                  fontSize: 11, fontWeight: 700, padding: "2px 10px", borderRadius: 99,
                  color: C.green, background: "rgba(52,211,153,.12)", border: "1px solid rgba(52,211,153,.3)",
                }}>Default</span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
