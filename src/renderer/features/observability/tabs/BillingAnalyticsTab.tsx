/**
 * BillingAnalyticsTab — platform-wide billing event count fed by
 * app/core/observability/bridges.py's wire_billing_metrics(), plus the
 * billing health probe (DB pool + Stripe configuration). Org-specific
 * revenue/invoices/subscriptions already have a dedicated page — the
 * Billing page — linked here rather than duplicated.
 * Data: GET /api/diagnostics/metrics, GET /api/diagnostics/health.
 */
import { useEffect, useState, useCallback } from "react";
import { apiFetch, parseJSON } from "../../../shared/utils/api";
import { CardGrid, ErrorNote, MetricCard, Skeletons, StatusBadge } from "../components";
import type { HealthReport, MetricsSnapshot } from "../types";

export function BillingAnalyticsTab() {
  const [metrics, setMetrics] = useState<MetricsSnapshot | null>(null);
  const [health, setHealth] = useState<HealthReport | null>(null);
  const [error, setError] = useState(false);

  const load = useCallback(async () => {
    try {
      const [m, h] = await Promise.all([
        apiFetch("/api/diagnostics/metrics").then(r => { if (!r.ok) throw new Error(); return parseJSON<MetricsSnapshot>(r, "/api/diagnostics/metrics"); }),
        apiFetch("/api/diagnostics/health").then(r => { if (!r.ok) throw new Error(); return parseJSON<HealthReport>(r, "/api/diagnostics/health"); }),
      ]);
      setMetrics(m);
      setHealth(h);
      setError(false);
    } catch {
      setError(true);
    }
  }, []);

  useEffect(() => {
    void Promise.resolve().then(load);
    const id = setInterval(() => void load(), 15000);
    return () => clearInterval(id);
  }, [load]);

  if (error && !metrics) return <ErrorNote onRetry={() => void load()}>Could not load billing metrics.</ErrorNote>;
  if (!metrics || !health) return <Skeletons n={2} />;

  const probe = health.probes.find(p => p.name === "billing");

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {probe && (
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontSize: 14, fontWeight: 600, color: "var(--t1)", letterSpacing: "-0.1px" }}>Billing subsystem</span>
          <StatusBadge status={probe.status} />
          <span style={{ fontSize: 12, color: "var(--t4)" }}>{probe.message}</span>
        </div>
      )}
      <div style={{ fontSize: 13, color: "var(--t3)", lineHeight: 1.5 }}>
        For org-scoped revenue, invoices, and subscriptions, see the{" "}
        <span style={{ color: "var(--accent-2)" }}>Billing</span> page.
      </div>
      <CardGrid>
        <MetricCard label="Billing events processed" value={metrics.counters.billing_events_total ?? 0} />
      </CardGrid>
    </div>
  );
}
