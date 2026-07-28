/**
 * UsageTab — usage meters for the current billing period.
 * Data comes from the parent BillingPage's already-fetched `billing.usage`.
 */
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import { GlassCard } from "../../../shared/ui/gold";

interface UsageMetric { used: number; limit: number; pct: number | null }

export interface BillingUsage { period: string; metrics: Record<string, UsageMetric> }

function metricLabel(t: TFunction<"billing">, metric: string): string {
  const known = ["tokens", "workflow_executions", "api_requests", "storage_mb", "embeddings", "marketplace_purchases", "seats", "active_users", "running_agents"];
  return known.includes(metric) ? t(`usageTab.metrics.${metric}`) : metric;
}

function fmt(n: number): string {
  if (n < 0) return "∞";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function UsageBar({ metric, data, t }: { metric: string; data: UsageMetric; t: TFunction<"billing"> }) {
  const pct = data.pct ?? 0;
  const color = pct >= 90 ? "var(--red)" : pct >= 70 ? "var(--yellow)" : "var(--green)";
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 5 }}>
        <span style={{ fontSize: 12, color: "var(--t2)", fontWeight: 500 }}>{metricLabel(t, metric)}</span>
        <span style={{ fontSize: 11, color: "var(--t4)" }}>{fmt(data.used)} / {fmt(data.limit)}</span>
      </div>
      <div style={{ height: 6, background: "var(--bg-card)", borderRadius: 99, overflow: "hidden" }}>
        <div style={{ height: "100%", width: `${Math.min(pct, 100)}%`, background: color, borderRadius: 99, transition: "width .4s" }} />
      </div>
    </div>
  );
}

export function UsageTab({ usage }: { usage: BillingUsage | null }) {
  const { t } = useTranslation("billing");
  if (!usage) {
    return <div className="skeleton" style={{ height: 200, borderRadius: 16 }} />;
  }
  return (
    <GlassCard lift={false}>
      <div style={{ fontSize: 14, fontWeight: 600, color: "var(--t1)", letterSpacing: "-0.1px", marginBottom: 14 }}>
        {t("usageTab.title", { period: usage.period })}
      </div>
      {Object.entries(usage.metrics).map(([metric, data]) => (
        <UsageBar key={metric} metric={metric} data={data} t={t} />
      ))}
    </GlassCard>
  );
}
