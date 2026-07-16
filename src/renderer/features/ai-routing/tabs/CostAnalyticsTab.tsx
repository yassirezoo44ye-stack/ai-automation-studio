/**
 * CostAnalyticsTab — reuses the already-built costClient
 * (core/ai/platform/CostClient.ts) rather than a fresh fetch. Its
 * /api/ai/cost/summary backend now reads real numbers from ai_usage_log
 * (AI Routing consolidation) instead of always returning zeros.
 */
import { useEffect, useState } from "react";
import { costClient, type CostSummary } from "../../../core/ai/platform";
import { S } from "../../../styles/theme";

export function CostAnalyticsTab() {
  const [summary, setSummary] = useState<CostSummary | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const s = await costClient.summary();
        if (alive) setSummary(s);
      } catch {
        if (alive) setError(true);
      }
    })();
    return () => { alive = false; };
  }, []);

  if (error) {
    return <div style={{ fontSize: 12, color: "var(--t4)" }}>Could not load cost summary.</div>;
  }
  if (!summary) {
    return <div className="skeleton" style={{ height: 260, borderRadius: 16 }} />;
  }

  const providers = Object.entries(summary.by_provider);

  return (
    <div style={{ display: "grid", gap: 16 }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 14 }}>
        <div style={S.card}>
          <div style={S.muted}>Total spend</div>
          <div style={{ fontSize: 26, fontWeight: 700, color: "var(--t1)", marginTop: 4 }}>${summary.total_usd.toFixed(4)}</div>
        </div>
        <div style={S.card}>
          <div style={S.muted}>Recorded calls</div>
          <div style={{ fontSize: 26, fontWeight: 700, color: "var(--t1)", marginTop: 4 }}>{summary.record_count}</div>
        </div>
      </div>

      <div style={S.card}>
        <div style={{ ...S.cardTitle, marginBottom: 14 }}>Spend by provider</div>
        {providers.length === 0 ? (
          <div style={S.muted}>No AI calls recorded yet.</div>
        ) : (
          providers.map(([provider, usd]) => {
            const pct = summary.total_usd > 0 ? (usd / summary.total_usd) * 100 : 0;
            return (
              <div key={provider} style={{ marginBottom: 12 }}>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 5 }}>
                  <span style={{ fontSize: 12, color: "var(--t2)" }}>{provider}</span>
                  <span style={{ fontSize: 11, color: "var(--t4)" }}>${usd.toFixed(4)}</span>
                </div>
                <div style={{ height: 6, background: "rgba(255,255,255,.05)", borderRadius: 99, overflow: "hidden" }}>
                  <div style={{ height: "100%", width: `${Math.min(pct, 100)}%`, background: "#E8C87D", borderRadius: 99 }} />
                </div>
              </div>
            );
          })
        )}
      </div>

      {summary.limits.length > 0 && (
        <div style={S.card}>
          <div style={{ ...S.cardTitle, marginBottom: 10 }}>Spending limits</div>
          {summary.limits.map((l, i) => (
            <div key={i} style={{ fontSize: 12, color: "var(--t3)" }}>{l.scope}: ${l.limit_usd}</div>
          ))}
        </div>
      )}
    </div>
  );
}
