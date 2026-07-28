/**
 * EventBusTab — tenancy event bus health + stats (backend, subscription
 * count, replay-buffer size, dead letters) — the event_bus probe's
 * metadata IS EventBus.stats(), not a duplicate read.
 * Data: GET /api/diagnostics/health.
 */
import { useEffect, useState, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { apiFetch, parseJSON } from "../../../shared/utils/api";
import { CardGrid, ErrorNote, MetricCard, Skeletons, StatusBadge } from "../components";
import type { HealthReport } from "../types";

export function EventBusTab() {
  const { t } = useTranslation("observability");
  const [health, setHealth] = useState<HealthReport | null>(null);
  const [error, setError] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await apiFetch("/api/diagnostics/health");
      if (!r.ok) throw new Error();
      setHealth(await parseJSON<HealthReport>(r, "/api/diagnostics/health"));
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

  if (error && !health) return <ErrorNote onRetry={() => void load()}>{t("eventsTab.loadError")}</ErrorNote>;
  if (!health) return <Skeletons n={1} />;

  const probe = health.probes.find(p => p.name === "event_bus");
  if (!probe) return <ErrorNote>{t("eventsTab.probeNotRegistered")}</ErrorNote>;

  const meta = probe.metadata as {
    backend?: string; subscriptions?: Record<string, number>; history_size?: number; dead_letters?: number;
  };
  const subCount = meta.subscriptions ? Object.values(meta.subscriptions).reduce((a, b) => a + b, 0) : 0;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <span style={{ fontSize: 14, fontWeight: 600, color: "var(--t1)", letterSpacing: "-0.1px" }}>{t("eventsTab.backendLabel", { backend: meta.backend ?? t("eventsTab.backendUnknown") })}</span>
        <StatusBadge status={probe.status} />
      </div>
      <CardGrid>
        <MetricCard label={t("eventsTab.activeSubscriptions")} value={subCount} />
        <MetricCard label={t("eventsTab.replayBufferSize")} value={meta.history_size ?? 0} />
        <MetricCard label={t("eventsTab.deadLetters")} value={meta.dead_letters ?? 0} />
      </CardGrid>
      {meta.subscriptions && Object.keys(meta.subscriptions).length > 0 && (
        <div>
          <div style={{ fontSize: 12, fontWeight: 600, color: "var(--t1)", letterSpacing: "-0.1px", marginBottom: 10 }}>{t("eventsTab.subscriptionsByPattern")}</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {Object.entries(meta.subscriptions).map(([pattern, count]) => (
              <div key={pattern} style={{ display: "flex", justifyContent: "space-between", fontSize: 12, color: "var(--t3)" }}>
                <span>{pattern}</span>
                <span>{count}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
