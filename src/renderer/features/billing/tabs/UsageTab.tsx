/**
 * UsageTab — usage meters for the current billing period.
 * Data comes from the parent BillingPage's already-fetched `billing.usage`.
 */
import { S } from "../../../styles/theme";

interface UsageMetric { used: number; limit: number; pct: number | null }

export interface BillingUsage { period: string; metrics: Record<string, UsageMetric> }

const METRIC_LABEL: Record<string, string> = {
  tokens: "AI Tokens", workflow_executions: "Workflow Runs", api_requests: "API Requests",
  storage_mb: "Storage (MB)", embeddings: "Embeddings", marketplace_purchases: "Marketplace Purchases",
  seats: "Seats", active_users: "Active Users", running_agents: "Running Agents",
};

function fmt(n: number): string {
  if (n < 0) return "∞";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function UsageBar({ metric, data }: { metric: string; data: UsageMetric }) {
  const pct = data.pct ?? 0;
  const color = pct >= 90 ? "#FF5252" : pct >= 70 ? "#FFB300" : "#00C853";
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 5 }}>
        <span style={{ fontSize: 12, color: "var(--t2)", fontWeight: 500 }}>{METRIC_LABEL[metric] ?? metric}</span>
        <span style={{ fontSize: 11, color: "var(--t4)" }}>{fmt(data.used)} / {fmt(data.limit)}</span>
      </div>
      <div style={{ height: 6, background: "rgba(255,255,255,.05)", borderRadius: 99, overflow: "hidden" }}>
        <div style={{ height: "100%", width: `${Math.min(pct, 100)}%`, background: color, borderRadius: 99, transition: "width .4s" }} />
      </div>
    </div>
  );
}

export function UsageTab({ usage }: { usage: BillingUsage | null }) {
  if (!usage) {
    return <div className="skeleton" style={{ height: 200, borderRadius: 16 }} />;
  }
  return (
    <div style={S.card}>
      <div style={{ ...S.cardTitle, marginBottom: 14 }}>Usage this period ({usage.period})</div>
      {Object.entries(usage.metrics).map(([metric, data]) => (
        <UsageBar key={metric} metric={metric} data={data} />
      ))}
    </div>
  );
}
