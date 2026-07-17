/**
 * SystemOverviewTab — every registered HealthRegistry probe + OS resource
 * gauges sampled by SystemMetricsService.
 * Data: GET /api/diagnostics/health, GET /api/diagnostics/metrics.
 */
import { useEffect, useState, useCallback } from "react";
import { apiFetch, parseJSON } from "../../../shared/utils/api";
import { S } from "../../../styles/theme";
import { CardGrid, ErrorNote, MetricCard, ProbeCard, Skeletons, StatusBadge } from "../components";
import type { HealthReport, MetricsSnapshot } from "../types";

export function SystemOverviewTab() {
  const [health, setHealth] = useState<HealthReport | null>(null);
  const [metrics, setMetrics] = useState<MetricsSnapshot | null>(null);
  const [error, setError] = useState(false);

  const load = useCallback(async () => {
    try {
      const [h, m] = await Promise.all([
        apiFetch("/api/diagnostics/health").then(r => { if (!r.ok) throw new Error(); return parseJSON<HealthReport>(r, "/api/diagnostics/health"); }),
        apiFetch("/api/diagnostics/metrics").then(r => { if (!r.ok) throw new Error(); return parseJSON<MetricsSnapshot>(r, "/api/diagnostics/metrics"); }),
      ]);
      setHealth(h);
      setMetrics(m);
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

  if (error && !health) return <ErrorNote>Could not load system health.</ErrorNote>;
  if (!health || !metrics) return <Skeletons n={4} />;

  const g = metrics.gauges;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      <div>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
          <span style={S.cardTitle}>Overall status</span>
          <StatusBadge status={health.status} />
          <span style={{ fontSize: 11, color: "var(--t4)" }}>uptime {(metrics.uptime_s / 3600).toFixed(1)}h</span>
        </div>
        <CardGrid>
          {health.probes.map(p => <ProbeCard key={p.name} probe={p} />)}
        </CardGrid>
      </div>

      <div>
        <div style={{ ...S.cardTitle, marginBottom: 12 }}>Resource usage</div>
        <CardGrid>
          <MetricCard label="CPU" value={g.system_cpu_percent ?? 0} suffix="%" />
          <MetricCard label="Memory (RSS)" value={g.system_memory_rss_mb ?? 0} suffix=" MB" />
          <MetricCard label="Disk used" value={g.system_disk_used_percent ?? 0} suffix="%" />
          <MetricCard label="Open FDs" value={g.system_open_fds ?? 0} />
          <MetricCard label="Network sent" value={((g.system_network_bytes_sent ?? 0) / 1024 ** 2)} suffix=" MB" />
          <MetricCard label="Network received" value={((g.system_network_bytes_recv ?? 0) / 1024 ** 2)} suffix=" MB" />
        </CardGrid>
      </div>

      <div>
        <div style={{ ...S.cardTitle, marginBottom: 12 }}>HTTP traffic</div>
        <CardGrid>
          <MetricCard label="Total requests" value={metrics.counters.http_requests_total ?? 0} />
          <MetricCard label="5xx errors" value={metrics.counters.http_errors_total ?? 0} />
          <MetricCard label="Avg latency" value={metrics.histograms.http_request_duration_ms?.avg ?? 0} suffix=" ms" />
          <MetricCard label="P95 latency" value={metrics.histograms.http_request_duration_ms?.p95 ?? 0} suffix=" ms" />
        </CardGrid>
      </div>
    </div>
  );
}
