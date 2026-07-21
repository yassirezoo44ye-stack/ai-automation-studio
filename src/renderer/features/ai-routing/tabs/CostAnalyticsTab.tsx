/**
 * CostAnalyticsTab — reuses the already-built costClient
 * (core/ai/platform/CostClient.ts) rather than a fresh fetch. Its
 * /api/ai/cost/summary backend now reads real numbers from ai_usage_log
 * (AI Routing consolidation) instead of always returning zeros.
 */
import { useEffect, useState, useCallback } from "react";
import { costClient, type CostSummary } from "../../../core/ai/platform";
import { GlassCard, GoldButton, KpiCard } from "../../../shared/ui/gold";
import { EmptyState } from "../../../shared/ui/EmptyState";

export function CostAnalyticsTab() {
  const [summary, setSummary] = useState<CostSummary | null>(null);
  const [error, setError] = useState(false);

  const load = useCallback(async () => {
    setError(false);
    try {
      const s = await costClient.summary();
      setSummary(s);
    } catch {
      setError(true);
    }
  }, []);

  useEffect(() => { void Promise.resolve().then(load); }, [load]);

  if (error) {
    return (
      <EmptyState
        icon={<span style={{ fontSize: 40 }}>⚠️</span>}
        title="Could not load cost summary"
        description="Something went wrong reaching the server."
        action={<GoldButton variant="ghost" onClick={() => void load()}>Retry</GoldButton>}
      />
    );
  }
  if (!summary) {
    return <div className="skeleton" style={{ height: 260, borderRadius: 16 }} />;
  }

  const providers = Object.entries(summary.by_provider);

  return (
    <div style={{ display: "grid", gap: 16 }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 14 }}>
        {/* Precise decimal spend — kept out of KpiCard, whose animated
            counter rounds to the nearest integer and would show "$0"
            for realistic sub-$1 AI spend. */}
        <GlassCard lift={false}>
          <div style={{ fontSize: 13, color: "var(--t3)" }}>Total spend</div>
          <div style={{ fontSize: 26, fontWeight: 700, color: "var(--t1)", marginTop: 4 }}>${summary.total_usd.toFixed(4)}</div>
        </GlassCard>
        <KpiCard label="Recorded calls" value={summary.record_count} />
      </div>

      <GlassCard lift={false}>
        <div style={{ fontSize: 14, fontWeight: 600, color: "var(--t1)", letterSpacing: "-0.1px", marginBottom: 14 }}>Spend by provider</div>
        {providers.length === 0 ? (
          <div style={{ fontSize: 13, color: "var(--t3)" }}>No AI calls recorded yet.</div>
        ) : (
          providers.map(([provider, usd]) => {
            const pct = summary.total_usd > 0 ? (usd / summary.total_usd) * 100 : 0;
            return (
              <div key={provider} style={{ marginBottom: 12 }}>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 5 }}>
                  <span style={{ fontSize: 12, color: "var(--t2)" }}>{provider}</span>
                  <span style={{ fontSize: 11, color: "var(--t4)" }}>${usd.toFixed(4)}</span>
                </div>
                <div style={{ height: 6, background: "var(--bg-hover)", borderRadius: 99, overflow: "hidden" }}>
                  <div style={{ height: "100%", width: `${Math.min(pct, 100)}%`, background: "var(--blue)", borderRadius: 99 }} />
                </div>
              </div>
            );
          })
        )}
      </GlassCard>

      {summary.limits.length > 0 && (
        <GlassCard lift={false}>
          <div style={{ fontSize: 14, fontWeight: 600, color: "var(--t1)", letterSpacing: "-0.1px", marginBottom: 10 }}>Spending limits</div>
          {summary.limits.map((l, i) => (
            <div key={i} style={{ fontSize: 12, color: "var(--t3)" }}>{l.scope}: ${l.limit_usd}</div>
          ))}
        </GlassCard>
      )}
    </div>
  );
}
