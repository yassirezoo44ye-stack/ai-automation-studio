/**
 * AIAnalyticsTab — aggregate AI request/token/cost/latency/failure metrics
 * from MetricsRegistry (fed by app/core/observability/bridges.py's
 * wire_ai_metrics()). Per-provider/per-model cost breakdown already has a
 * dedicated view — the AI Routing page's Cost Analytics tab — linked here
 * rather than duplicated.
 * Data: GET /api/diagnostics/metrics.
 */
import { useEffect, useState, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { apiFetch, parseJSON } from "../../../shared/utils/api";
import { CardGrid, ErrorNote, MetricCard, Skeletons } from "../components";
import type { MetricsSnapshot } from "../types";

export function AIAnalyticsTab() {
  const { t } = useTranslation("observability");
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

  if (error && !metrics) return <ErrorNote onRetry={() => void load()}>{t("aiTab.loadError")}</ErrorNote>;
  if (!metrics) return <Skeletons n={3} />;

  const c = metrics.counters;
  const g = metrics.gauges;
  const lat = metrics.histograms.ai_request_latency_ms;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ fontSize: 13, color: "var(--t3)", lineHeight: 1.5 }}>
        {t("aiTab.descriptionPrefix")}{" "}
        <span style={{ color: "var(--accent-2)" }}>{t("aiTab.linkLabel")}</span> {t("aiTab.descriptionSuffix")}
      </div>
      <CardGrid>
        <MetricCard label={t("aiTab.totalRequests")} value={c.ai_requests_total ?? 0} />
        <MetricCard label={t("aiTab.inputTokens")} value={c.ai_tokens_input_total ?? 0} />
        <MetricCard label={t("aiTab.outputTokens")} value={c.ai_tokens_output_total ?? 0} />
        <MetricCard label={t("aiTab.totalSpend")} value={(c.ai_cost_usd_total ?? 0).toFixed(4)} suffix=" USD" />
        <MetricCard label={t("aiTab.providerFailures")} value={c.ai_provider_failures_total ?? 0} />
        <MetricCard label={t("aiTab.activeStreams")} value={g.ai_active_streams ?? 0} />
        <MetricCard label={t("aiTab.avgLatency")} value={lat?.avg ?? 0} suffix=" ms" />
        <MetricCard label={t("aiTab.p95Latency")} value={lat?.p95 ?? 0} suffix=" ms" />
        <MetricCard label={t("aiTab.p99Latency")} value={lat?.p99 ?? 0} suffix=" ms" />
      </CardGrid>
    </div>
  );
}
