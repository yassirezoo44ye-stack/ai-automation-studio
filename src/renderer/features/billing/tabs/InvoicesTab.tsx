/**
 * InvoicesTab — billing history: invoices.
 * Data: GET /api/orgs/{id}/billing/invoices
 */
import { useState, useEffect, useCallback } from "react";
import { apiFetch, parseJSON } from "../../../shared/utils/api";
import { useToast } from "../../../contexts/ToastContext";
import { S } from "../../../styles/theme";

interface Invoice {
  id: string; status: string; amount_due_cents: number; amount_paid_cents: number;
  currency: string; hosted_invoice_url: string | null; invoice_pdf_url: string | null;
  created_at: string;
}

const STATUS_COLOR: Record<string, string> = {
  paid: "#34d399", open: "#f59e0b", draft: "#6b7280",
  uncollectible: "#ef4444", void: "#6b7280",
};

function money(cents: number, currency: string): string {
  return `${(cents / 100).toFixed(2)} ${currency.toUpperCase()}`;
}

export function InvoicesTab({ currentOrgId }: { currentOrgId: string }) {
  const toast = useToast();
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await apiFetch(`/api/orgs/${currentOrgId}/billing/invoices`);
      if (!r.ok) throw new Error();
      const d = await parseJSON<{ invoices: Invoice[] }>(r, "/billing/invoices");
      setInvoices(d.invoices);
    } catch {
      toast("Could not load invoices", "err");
      setInvoices([]);
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

  if (invoices.length === 0) {
    return (
      <div className="empty-state">
        <div style={{ fontSize: 40 }}>🧾</div>
        <h3>No invoices yet</h3>
        <p>Invoices appear here once you're on a paid plan.</p>
      </div>
    );
  }

  return (
    <div style={S.card}>
      {invoices.map((inv, i) => (
        <div key={inv.id} style={{
          padding: "12px 4px", borderTop: i > 0 ? "1px solid var(--border)" : "none",
          display: "flex", alignItems: "center", gap: 12,
        }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: "var(--t1)" }}>
              {money(inv.amount_paid_cents || inv.amount_due_cents, inv.currency)}
            </div>
            <div style={{ fontSize: 11, color: "var(--t4)" }}>
              {new Date(inv.created_at).toLocaleDateString()}
            </div>
          </div>
          <span style={{
            fontSize: 11, fontWeight: 700, padding: "2px 10px", borderRadius: 99,
            color: STATUS_COLOR[inv.status] ?? "#6b7280", background: (STATUS_COLOR[inv.status] ?? "#6b7280") + "18",
            border: `1px solid ${STATUS_COLOR[inv.status] ?? "#6b7280"}33`,
          }}>
            {inv.status}
          </span>
          {(inv.hosted_invoice_url || inv.invoice_pdf_url) && (
            <a
              href={inv.hosted_invoice_url ?? inv.invoice_pdf_url ?? "#"} target="_blank" rel="noreferrer"
              style={{ ...S.btnSecondary, padding: "5px 12px", fontSize: 11, textDecoration: "none" }}
            >View</a>
          )}
        </div>
      ))}
    </div>
  );
}
