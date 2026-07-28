/**
 * ModelsTab — the reconciled model/pricing catalog, read-only.
 * Data: GET /api/ai/models (app/ai/cost_router.py's list_models(), which
 * now reads app/core/ai/models/catalog.py — the same catalog ModelRouter
 * uses for live provider selection, not a separate price table).
 */
import { useEffect, useState, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { apiFetch, parseJSON } from "../../../shared/utils/api";
import { GlassCard, GoldButton } from "../../../shared/ui/gold";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { StatusBadge } from "../../../shared/ui/StatusBadge";

interface ModelRow {
  id: string;
  provider: string;
  display_name: string;
  input_per_m: number;
  output_per_m: number;
  quality: number;
  speed: number;
  context_window: number;
  available: boolean;
}

function fmtContext(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${Math.round(n / 1_000)}K`;
  return String(n);
}

export function ModelsTab() {
  const { t } = useTranslation("aiRouting");
  const [models, setModels] = useState<ModelRow[] | null>(null);
  const [error, setError] = useState(false);

  const load = useCallback(async () => {
    setError(false);
    try {
      const r = await apiFetch("/api/ai/models");
      if (!r.ok) throw new Error();
      const d = await parseJSON<{ models: ModelRow[] }>(r, "/api/ai/models");
      setModels(d.models);
    } catch {
      setError(true);
    }
  }, []);

  useEffect(() => { void Promise.resolve().then(load); }, [load]);

  if (error) {
    return (
      <EmptyState
        icon={<span style={{ fontSize: 40 }}>⚠️</span>}
        title={t("modelsTab.loadError.title")}
        description={t("modelsTab.loadError.description")}
        action={<GoldButton variant="ghost" onClick={() => void load()}>{t("modelsTab.loadError.retry")}</GoldButton>}
      />
    );
  }
  if (!models) {
    return <div className="skeleton" style={{ height: 300, borderRadius: 16 }} />;
  }

  return (
    <GlassCard lift={false}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
        <thead>
          <tr style={{ textAlign: "left", color: "var(--t4)", fontSize: 11, textTransform: "uppercase" }}>
            <th style={{ padding: "0 10px 10px 0" }}>{t("modelsTab.columns.model")}</th>
            <th style={{ padding: "0 10px 10px" }}>{t("modelsTab.columns.provider")}</th>
            <th style={{ padding: "0 10px 10px" }}>{t("modelsTab.columns.context")}</th>
            <th style={{ padding: "0 10px 10px" }}>{t("modelsTab.columns.priceIn")}</th>
            <th style={{ padding: "0 10px 10px" }}>{t("modelsTab.columns.priceOut")}</th>
            <th style={{ padding: "0 10px 10px" }}>{t("modelsTab.columns.quality")}</th>
            <th style={{ padding: "0 10px 10px" }}>{t("modelsTab.columns.speed")}</th>
            <th style={{ padding: "0 0 10px" }}>{t("modelsTab.columns.status")}</th>
          </tr>
        </thead>
        <tbody>
          {models.map(m => (
            <tr key={m.id} style={{ borderTop: "1px solid var(--border)" }}>
              <td style={{ padding: "10px 10px 10px 0", color: "var(--t1)", fontWeight: 600 }}>{m.display_name}</td>
              <td style={{ padding: "10px", color: "var(--t3)" }}>{m.provider}</td>
              <td style={{ padding: "10px", color: "var(--t3)" }}>{fmtContext(m.context_window)}</td>
              <td style={{ padding: "10px", color: "var(--t3)" }}>${m.input_per_m.toFixed(2)}</td>
              <td style={{ padding: "10px", color: "var(--t3)" }}>${m.output_per_m.toFixed(2)}</td>
              <td style={{ padding: "10px", color: "var(--t3)" }}>{Math.round(m.quality * 100)}%</td>
              <td style={{ padding: "10px", color: "var(--t3)" }}>{Math.round(m.speed * 100)}%</td>
              <td style={{ padding: "10px 0" }}>
                <StatusBadge kind={m.available ? "success" : "neutral"} label={m.available ? t("modelsTab.available") : t("modelsTab.deferred")} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </GlassCard>
  );
}
