/**
 * AIAnalyticsTab — aggregate AI request/token/cost/latency/failure metrics
 * from MetricsRegistry (fed by app/core/observability/bridges.py's
 * wire_ai_metrics()). Per-provider/per-model cost breakdown already has a
 * dedicated view — the AI Routing page's Cost Analytics tab — linked here
 * rather than duplicated.
 * Data: GET /api/diagnostics/metrics.
 */
import { useEffect, useState, useCallback } from "react";
import { apiFetch, parseJSON } from "../../../shared/utils/api";
import { CardGrid, ErrorNote, MetricCard, Skeletons } from "../components";
import type { MetricsSnapshot } from "../types";

export function AIAnalyticsTab() {
  const [metrics, setMetrics] = useState<MetricsSnapshot | null>(null);
  const [error, setError] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await apiFetch("/api/diagnostics/metrics");
      if (!r.ok) throw new Error();
      setMetrics(await parseJSON<MetricsSnapshot>(r, "/api/diagnostics/metrics"));
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

  if (error && !metrics) return <ErrorNote onRetry={() => void load()}>Could not load AI metrics.</ErrorNote>;
  if (!metrics) return <Skeletons n={3} />;

  const c = metrics.counters;
  const g = metrics.gauges;
  const lat = metrics.histograms.ai_request_latency_ms;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ fontSize: 13, color: "var(--t3)", lineHeight: 1.5 }}>
        Aggregate totals across every provider since the process started. For
        per-provider/per-model cost breakdown, see the{" "}
        <span style={{ color: "var(--accent-2)" }}>AI Routing → Cost Analytics</span> tab.
      </div>
      <CardGrid>
        <MetricCard label="Total requests" value={c.ai_requests_total ?? 0} />
        <MetricCard label="Input tokens" value={c.ai_tokens_input_total ?? 0} />
        <MetricCard label="Output tokens" value={c.ai_tokens_output_total ?? 0} />
        <MetricCard label="Total spend" value={(c.ai_cost_usd_total ?? 0).toFixed(4)} suffix=" USD" />
        <MetricCard label="Provider failures" value={c.ai_provider_failures_total ?? 0} />
        <MetricCard label="Active streams" value={g.ai_active_streams ?? 0} />
        <MetricCard label="Avg latency" value={lat?.avg ?? 0} suffix=" ms" />
        <MetricCard label="P95 latency" value={lat?.p95 ?? 0} suffix=" ms" />
        <MetricCard label="P99 latency" value={lat?.p99 ?? 0} suffix=" ms" />
      </CardGrid>
    </div>
  );
}
