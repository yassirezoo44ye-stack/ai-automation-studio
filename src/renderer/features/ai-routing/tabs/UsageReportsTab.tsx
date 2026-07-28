/**
 * UsageReportsTab — total spend + per-provider breakdown over a time
 * window, reusing costClient.usage()/byProvider() (core/ai/platform/
 * CostClient.ts) against the new /api/ai/usage, /api/ai/usage/providers
 * endpoints.
 */
import { useEffect, useState, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { costClient, type UsageByProvider } from "../../../core/ai/platform";
import { GlassCard, GoldButton } from "../../../shared/ui/gold";
import { EmptyState } from "../../../shared/ui/EmptyState";

const WINDOWS: { key: "days7" | "days30" | "allTime"; days: number | null }[] = [
  { key: "days7", days: 7 },
  { key: "days30", days: 30 },
  { key: "allTime", days: null },
];

export function UsageReportsTab() {
  const { t } = useTranslation("aiRouting");
  const [windowIdx, setWindowIdx] = useState(1);
  const [totalUsd, setTotalUsd] = useState<number | null>(null);
  const [byProvider, setByProvider] = useState<UsageByProvider[] | null>(null);
  const [error, setError] = useState(false);

  const load = useCallback(async () => {
    setError(false);
    const days = WINDOWS[windowIdx].days;
    const since = days ? new Date(Date.now() - days * 86_400_000).toISOString() : undefined;
    try {
      const [u, p] = await Promise.all([
        costClient.usage(since),
        costClient.byProvider(since),
      ]);
      setTotalUsd(u.total_usd);
      setByProvider(p);
    } catch {
      setError(true);
    }
  }, [windowIdx]);

  useEffect(() => { void Promise.resolve().then(load); }, [load]);

  return (
    <div style={{ display: "grid", gap: 16 }}>
      <div style={{ display: "flex", gap: 6 }}>
        {WINDOWS.map((w, i) => (
          <GoldButton
            key={w.key}
            variant={windowIdx === i ? "primary" : "ghost"}
            onClick={() => setWindowIdx(i)}
            style={{ padding: "6px 14px", fontSize: 12 }}
          >
            {t(`usageReportsTab.windows.${w.key}`)}
          </GoldButton>
        ))}
      </div>

      {error ? (
        <EmptyState
          icon={<span style={{ fontSize: 40 }}>⚠️</span>}
          title={t("usageReportsTab.loadError.title")}
          description={t("usageReportsTab.loadError.description")}
          action={<GoldButton variant="ghost" onClick={() => void load()}>{t("usageReportsTab.loadError.retry")}</GoldButton>}
        />
      ) : totalUsd === null || byProvider === null ? (
        <div className="skeleton" style={{ height: 220, borderRadius: 16 }} />
      ) : (
        <>
          <GlassCard lift={false}>
            <div style={{ fontSize: 13, color: "var(--t3)" }}>{t(`usageReportsTab.totalSpendLabel.${WINDOWS[windowIdx].key}`)}</div>
            <div style={{ fontSize: 26, fontWeight: 700, color: "var(--t1)", marginTop: 4 }}>${totalUsd.toFixed(4)}</div>
          </GlassCard>

          <GlassCard lift={false}>
            <div style={{ fontSize: 14, fontWeight: 600, color: "var(--t1)", letterSpacing: "-0.1px", marginBottom: 14 }}>{t("usageReportsTab.byProvider")}</div>
            {byProvider.length === 0 ? (
              <div style={{ fontSize: 13, color: "var(--t3)" }}>{t("usageReportsTab.noCalls")}</div>
            ) : (
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                <thead>
                  <tr style={{ textAlign: "left", color: "var(--t4)", fontSize: 11, textTransform: "uppercase" }}>
                    <th style={{ padding: "0 10px 10px 0" }}>{t("usageReportsTab.columns.provider")}</th>
                    <th style={{ padding: "0 0 10px" }}>{t("usageReportsTab.columns.spend")}</th>
                  </tr>
                </thead>
                <tbody>
                  {byProvider.map(p => (
                    <tr key={p.provider_id} style={{ borderTop: "1px solid var(--border)" }}>
                      <td style={{ padding: "10px 10px 10px 0", color: "var(--t1)", fontWeight: 600 }}>{p.provider_id}</td>
                      <td style={{ padding: "10px 0", color: "var(--t3)" }}>${p.total_usd.toFixed(4)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </GlassCard>
        </>
      )}
    </div>
  );
}
