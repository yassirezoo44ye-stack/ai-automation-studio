/**
 * BillingHistoryTab — combined chronological feed of payments + credits.
 * Data: GET /api/orgs/{id}/billing/payments, GET .../billing/credits
 */
import { useState, useEffect, useCallback } from "react";
import { apiFetch, parseJSON } from "../../../shared/utils/api";
import { useToast } from "../../../contexts/ToastContext";
import { S } from "../../../styles/theme";

interface Payment {
  id: string; status: string; amount_cents: number; currency: string;
  failure_message: string | null; created_at: string;
}
interface CreditEntry { id: string; amount_usd: number; reason: string; created_at: string }

type HistoryRow =
  | { kind: "payment"; at: string; data: Payment }
  | { kind: "credit"; at: string; data: CreditEntry };

const STATUS_COLOR: Record<string, string> = {
  succeeded: "#34d399", pending: "#f59e0b", failed: "#ef4444", refunded: "#6b7280",
};

export function BillingHistoryTab({ currentOrgId }: { currentOrgId: string }) {
  const toast = useToast();
  const [balance, setBalance] = useState<number | null>(null);
  const [rows, setRows] = useState<HistoryRow[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [pr, cr] = await Promise.all([
        apiFetch(`/api/orgs/${currentOrgId}/billing/payments`),
        apiFetch(`/api/orgs/${currentOrgId}/billing/credits`),
      ]);
      const payments = pr.ok
        ? (await parseJSON<{ payments: Payment[] }>(pr, "/billing/payments")).payments : [];
      const credits = cr.ok
        ? await parseJSON<{ balance_usd: number; ledger: CreditEntry[] }>(cr, "/billing/credits") : null;
      setBalance(credits?.balance_usd ?? null);
      const combined: HistoryRow[] = [
        ...payments.map(p => ({ kind: "payment" as const, at: p.created_at, data: p })),
        ...(credits?.ledger ?? []).map(c => ({ kind: "credit" as const, at: c.created_at, data: c })),
      ].sort((a, b) => new Date(b.at).getTime() - new Date(a.at).getTime());
      setRows(combined);
    } catch {
      toast("Could not load billing history", "err");
      setRows([]);
    } finally { setLoading(false); }
  }, [currentOrgId, toast]);

  useEffect(() => { void load(); }, [load]);

  if (loading) {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {[1, 2, 3].map(i => <div key={i} className="skeleton" style={{ height: 48, borderRadius: 12 }} />)}
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {balance !== null && balance > 0 && (
        <div style={{ ...S.card, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span style={{ fontSize: 13, color: "var(--t2)" }}>Account credit balance</span>
          <span style={{ fontSize: 16, fontWeight: 700, color: "#34d399" }}>${balance.toFixed(2)}</span>
        </div>
      )}

      {rows.length === 0 ? (
        <div className="empty-state">
          <div style={{ fontSize: 40 }}>📜</div>
          <h3>No billing history yet</h3>
        </div>
      ) : (
        <div style={S.card}>
          {rows.map((row, i) => (
            <div key={`${row.kind}-${row.data.id}`} style={{
              padding: "12px 4px", borderTop: i > 0 ? "1px solid var(--border)" : "none",
              display: "flex", alignItems: "center", gap: 12,
            }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: "var(--t1)" }}>
                  {row.kind === "payment"
                    ? `Payment — $${(row.data.amount_cents / 100).toFixed(2)} ${row.data.currency.toUpperCase()}`
                    : `Credit — $${row.data.amount_usd.toFixed(2)} (${row.data.reason})`}
                </div>
                <div style={{ fontSize: 11, color: "var(--t4)" }}>
                  {new Date(row.at).toLocaleString()}
                  {row.kind === "payment" && row.data.failure_message ? ` · ${row.data.failure_message}` : ""}
                </div>
              </div>
              {row.kind === "payment" && (
                <span style={{
                  fontSize: 11, fontWeight: 700, padding: "2px 10px", borderRadius: 99,
                  color: STATUS_COLOR[row.data.status] ?? "#6b7280",
                  background: (STATUS_COLOR[row.data.status] ?? "#6b7280") + "18",
                  border: `1px solid ${STATUS_COLOR[row.data.status] ?? "#6b7280"}33`,
                }}>{row.data.status}</span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
