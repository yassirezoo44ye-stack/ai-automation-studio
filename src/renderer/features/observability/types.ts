// Shapes returned by app/routers/diagnostics_api.py, app/routers/health.py,
// app/routers/auth_users.py (audit-log), and app/routers/organizations.py
// (activity). Kept in one file since every tab in this feature reads from
// the same small set of backend endpoints.

export type HealthStatus = "healthy" | "degraded" | "unhealthy" | "unknown";

export interface ProbeResult {
  name: string;
  status: HealthStatus;
  message: string;
  duration_ms: number;
  metadata: Record<string, unknown>;
}

export interface HealthReport {
  status: HealthStatus;
  probes: ProbeResult[];
  ts: number;
}

export interface HistogramSnapshot {
  count: number;
  total: number;
  avg: number;
  p50: number;
  p95: number;
  p99: number;
}

export interface MetricsSnapshot {
  uptime_s: number;
  counters: Record<string, number>;
  gauges: Record<string, number>;
  histograms: Record<string, HistogramSnapshot>;
}

export interface ServiceStatus {
  name: string;
  state: "stopped" | "starting" | "running" | "stopping" | "failed";
  uptime_s: number;
  restarts: number;
  last_tick: number | null;
  error: string | null;
}

export interface TraceSpan {
  trace_id: string;
  span_id: string;
  parent_id: string | null;
  name: string;
  service: string;
  duration_ms: number;
  tags: Record<string, string>;
  events: Array<{ name: string; ts: number } & Record<string, string>>;
  error: string | null;
}

export interface AlertRule {
  id: string;
  organization_id: string | null;
  name: string;
  rule_type: "gauge_above" | "counter_rate_above" | "health_unhealthy";
  target: string;
  threshold: number | null;
  enabled: boolean;
  notify_email: string | null;
  notify_webhook_url: string | null;
  created_at: string;
  updated_at: string;
}

export interface AlertHistoryEntry {
  id: string;
  rule_id: string;
  rule_name: string;
  fired_at: string;
  resolved_at: string | null;
  value: number | null;
  message: string | null;
}

export interface AuditLogEntry {
  id: string;
  action: string;
  resource: string | null;
  resource_id: string | null;
  details: Record<string, unknown> | null;
  ip_address: string | null;
  created_at: string;
}

// Matches GET /api/orgs/{org_id}/activity's trimmed response shape
// (app/routers/organizations.py) — not the full activity_logs row.
export interface ActivityLogEntry {
  action: string;
  resource: string | null;
  resource_id: string | null;
  actor_id: string | null;
  created_at: string;
}
