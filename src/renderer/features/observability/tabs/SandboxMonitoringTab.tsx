/**
 * SandboxMonitoringTab — sandbox worker gauges sampled every 15s by
 * SystemMetricsService. Per-worker logs/permission requests already live
 * on the Sandbox page, linked here rather than duplicated.
 * Data: GET /api/diagnostics/metrics.
 */
import { useEffect, useState, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { apiFetch, parseJSON } from "../../../shared/utils/api";
import { CardGrid, ErrorNote, MetricCard, Skeletons } from "../components";
import type { MetricsSnapshot } from "../types";

export function SandboxMonitoringTab() {
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

  if (error && !metrics) return <ErrorNote onRetry={() => void load()}>{t("sandboxTab.loadError")}</ErrorNote>;
  if (!metrics) return <Skeletons n={2} />;

  const g = metrics.gauges;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ fontSize: 13, color: "var(--t3)", lineHeight: 1.5 }}>
        {t("sandboxTab.descriptionPrefix")}{" "}
        <span style={{ color: "var(--accent-2)" }}>{t("sandboxTab.linkLabel")}</span> {t("sandboxTab.descriptionSuffix")}
      </div>
      <CardGrid>
        <MetricCard label={t("sandboxTab.runningWorkers")} value={g.sandbox_running_workers ?? 0} />
        <MetricCard label={t("sandboxTab.crashedWorkers")} value={g.sandbox_execution_failures ?? 0} />
        <MetricCard label={t("sandboxTab.cpuSecondsRunning")} value={(g.sandbox_cpu_seconds ?? 0).toFixed(1)} />
        <MetricCard label={t("sandboxTab.memoryRunning")} value={g.sandbox_memory_mb ?? 0} suffix=" MB" />
      </CardGrid>
    </div>
  );
}
