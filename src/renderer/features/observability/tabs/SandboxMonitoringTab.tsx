/**
 * SandboxMonitoringTab — sandbox worker gauges sampled every 15s by
 * SystemMetricsService. Per-worker logs/permission requests already live
 * on the Sandbox page, linked here rather than duplicated.
 * Data: GET /api/diagnostics/metrics.
 */
import { useEffect, useState, useCallback } from "react";
import { apiFetch, parseJSON } from "../../../shared/utils/api";
import { S } from "../../../styles/theme";
import { CardGrid, ErrorNote, MetricCard, Skeletons } from "../components";
import type { MetricsSnapshot } from "../types";

export function SandboxMonitoringTab() {
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
    void load();
    const id = setInterval(() => void load(), 15000);
    return () => clearInterval(id);
  }, [load]);

  if (error && !metrics) return <ErrorNote>Could not load sandbox metrics.</ErrorNote>;
  if (!metrics) return <Skeletons n={2} />;

  const g = metrics.gauges;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={S.muted}>
        For per-worker logs and permission requests, see the{" "}
        <span style={{ color: "#FFE58A" }}>Sandbox</span> page.
      </div>
      <CardGrid>
        <MetricCard label="Running workers" value={g.sandbox_running_workers ?? 0} />
        <MetricCard label="Crashed workers" value={g.sandbox_execution_failures ?? 0} />
        <MetricCard label="CPU seconds (running)" value={(g.sandbox_cpu_seconds ?? 0).toFixed(1)} />
        <MetricCard label="Memory (running)" value={g.sandbox_memory_mb ?? 0} suffix=" MB" />
      </CardGrid>
    </div>
  );
}
