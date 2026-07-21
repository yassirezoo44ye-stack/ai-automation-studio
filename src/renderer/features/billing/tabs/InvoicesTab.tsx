/**
 * InvoicesTab — billing history: invoices.
 * Data: GET /api/orgs/{id}/billing/invoices
 */
import { useState, useEffect, useCallback } from "react";
import { apiFetch, parseJSON } from "../../../shared/utils/api";
import { useToast } from "../../../contexts/toast";
import { GoldButton, GlassCard } from "../../../shared/ui/gold";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { StatusBadge } from "../../../shared/ui/StatusBadge";
import { type StatusBadgeKind } from "../../../styles/theme";

interface Invoice {
  id: string; status: string; amount_due_cents: number; amount_paid_cents: number;
  currency: string; hosted_invoice_url: string | null; invoice_pdf_url: string | null;
  created_at: string;
}

const STATUS_KIND: Record<string, StatusBadgeKind> = {
  paid: "success", open: "warning", draft: "neutral",
  uncollectible: "error", void: "neutral",
};

function money(cents: number, currency: string): string {
  return `${(cents / 100).toFixed(2)} ${currency.toUpperCase()}`;
}

export function InvoicesTab({ currentOrgId }: { currentOrgId: string }) {
  const toast = useToast();
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(false);
    try {
      const r = await apiFetch(`/api/orgs/${currentOrgId}/billing/invoices`);
      if (!r.ok) throw new Error();
      const d = await parseJSON<{ invoices: Invoice[] }>(r, "/billing/invoices");
      setInvoices(d.invoices);
    } catch {
      toast("Could not load invoices", "err");
      setInvoices([]);
      setError(true);
    } finally { setLoading(false); }
  }, [currentOrgId, toast]);

  useEffect(() => { void Promise.resolve().then(load); }, [load]);

  if (loading) {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {[1, 2, 3].map(i => <div key={i} className="skeleton" style={{ height: 48, borderRadius: 12 }} />)}
      </div>
    );
  }

  if (error) {
    return (
      <EmptyState
        icon={<span style={{ fontSize: 40 }}>⚠️</span>}
        title="Could not load invoices"
        description="Something went wrong reaching the server."
        action={<GoldButton variant="ghost" onClick={() => void load()}>Retry</GoldButton>}
      />
    );
  }

  if (invoices.length === 0) {
    return (
      <EmptyState
        icon={<span style={{ fontSize: 40 }}>🧾</span>}
        title="No invoices yet"
        description="Invoices appear here once you're on a paid plan."
      />
    );
  }

  return (
    <GlassCard lift={false}>
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
          <StatusBadge kind={STATUS_KIND[inv.status] ?? "neutral"} label={inv.status} />
          {(inv.hosted_invoice_url || inv.invoice_pdf_url) && (
            <a
              href={inv.hosted_invoice_url ?? inv.invoice_pdf_url ?? "#"} target="_blank" rel="noreferrer"
              className="g-btn g-btn--ghost"
              style={{ padding: "5px 12px", fontSize: 11, textDecoration: "none" }}
            >View</a>
          )}
        </div>
      ))}
    </GlassCard>
  );
}
