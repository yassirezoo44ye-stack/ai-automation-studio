/**
 * WorkflowAnalyticsTab — run counts fed by
 * app/core/observability/bridges.py's wire_workflow_metrics().
 * Data: GET /api/diagnostics/metrics.
 */
import { useEffect, useState, useCallback } from "react";
import { apiFetch, parseJSON } from "../../../shared/utils/api";
import { CardGrid, ErrorNote, MetricCard, Skeletons } from "../components";
import type { MetricsSnapshot } from "../types";

export function WorkflowAnalyticsTab() {
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

  if (error && !metrics) return <ErrorNote>Could not load workflow metrics.</ErrorNote>;
  if (!metrics) return <Skeletons n={2} />;

  const c = metrics.counters;
  const g = metrics.gauges;
  const total = c.workflow_runs_total ?? 0;
  const success = c.workflow_runs_success ?? 0;
  const successRate = total > 0 ? (success / total) * 100 : 0;

  return (
    <CardGrid>
      <MetricCard label="Total runs" value={total} />
      <MetricCard label="Currently active" value={g.workflow_active_runs ?? 0} />
      <MetricCard label="Successful" value={success} />
      <MetricCard label="Failed" value={c.workflow_runs_failed ?? 0} />
      <MetricCard label="Success rate" value={successRate.toFixed(1)} suffix="%" />
    </CardGrid>
  );
}
