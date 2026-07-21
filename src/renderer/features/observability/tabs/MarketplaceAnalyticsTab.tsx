/**
 * MarketplaceAnalyticsTab — install/publish counts fed by
 * app/core/observability/bridges.py's wire_marketplace_metrics(), plus the
 * marketplace health probe (JSON-fallback vs Postgres-backed store).
 * Data: GET /api/diagnostics/metrics, GET /api/diagnostics/health.
 */
import { useEffect, useState, useCallback } from "react";
import { apiFetch, parseJSON } from "../../../shared/utils/api";
import { CardGrid, ErrorNote, MetricCard, Skeletons, StatusBadge } from "../components";
import type { HealthReport, MetricsSnapshot } from "../types";

export function MarketplaceAnalyticsTab() {
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

  if (error && !metrics) return <ErrorNote onRetry={() => void load()}>Could not load marketplace metrics.</ErrorNote>;
  if (!metrics || !health) return <Skeletons n={2} />;

  const probe = health.probes.find(p => p.name === "marketplace");

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {probe && (
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontSize: 14, fontWeight: 600, color: "var(--t1)", letterSpacing: "-0.1px" }}>Store backend</span>
          <StatusBadge status={probe.status} />
          <span style={{ fontSize: 12, color: "var(--t4)" }}>{probe.message}</span>
        </div>
      )}
      <CardGrid>
        <MetricCard label="Installs" value={metrics.counters.marketplace_installs_total ?? 0} />
        <MetricCard label="Publishes" value={metrics.counters.marketplace_publishes_total ?? 0} />
      </CardGrid>
    </div>
  );
}
