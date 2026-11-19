import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { apiFetch, parseJSON } from "../../utils/api";
import { ErrorState } from "../../shared/ui/StateViews";
import { LoadingSpinner } from "../../shared/ui/LoadingSpinner";
import { GlassCard, GoldButton } from "../../shared/ui/gold";

type Run = {
  run_id: string; name: string; status: string; error?: string | null;
  steps?: { step_id: string; name: string; status: string; error?: string | null; result?: unknown }[];
};

function resultText(result: unknown): string {
  if (result == null) return "";
  if (typeof result === "string") return result;
  return JSON.stringify(result, null, 2);
}

/** Only visible for an explicit notification/deep link; never starts a run. */
export function NotificationRunDetails({ runId, onClose }: { runId: string; onClose: () => void }) {
  const { t } = useTranslation("automation");
  const [run, setRun] = useState<Run | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    void Promise.resolve().then(async () => {
      if (controller.signal.aborted) return;
      setLoading(true); setFailed(false);
      try {
        const path = `/api/automation-runs/${encodeURIComponent(runId)}`;
        const response = await apiFetch(path, { signal: controller.signal });
        const data = await parseJSON<Run>(response, path);
        if (data.run_id !== runId || !data.status) throw new Error("Run response does not match the request");
        if (!controller.signal.aborted) setRun(data);
      } catch { if (!controller.signal.aborted) setFailed(true); }
      finally { if (!controller.signal.aborted) setLoading(false); }
    });
    return () => controller.abort();
  }, [runId, revision]);
  const refresh = () => setRevision(value => value + 1);
  return <GlassCard lift={false}>
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, marginBottom: 12 }}>
      <h2 style={{ fontSize: 15 }}>{t("runDetails.title")}</h2>
      <GoldButton variant="ghost" onClick={onClose}>{t("runDetails.close")}</GoldButton>
    </div>
    {loading ? <LoadingSpinner label={t("runDetails.loading")} /> : failed ?
      <ErrorState compact message={t("runDetails.failed")} onRetry={refresh} /> : run && <>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 12, alignItems: "center" }}>
          <strong>{run.name}</strong>
          <span>{t(`workflows.status.${run.status}`, { defaultValue: run.status })}</span>
          <GoldButton variant="ghost" onClick={refresh}>{t("workflows.refresh")}</GoldButton>
        </div>
        {run.error && <p role="alert" style={{ color: "var(--red)", whiteSpace: "pre-wrap" }}>{run.error}</p>}
        {run.steps?.map(step => <section key={step.step_id} style={{ borderTop: "1px solid var(--b1)", marginTop: 12, paddingTop: 12 }}>
          <strong>{step.name}</strong> · {t(`workflows.status.${step.status}`, { defaultValue: step.status })}
          {step.error && <p style={{ color: "var(--red)", whiteSpace: "pre-wrap" }}>{step.error}</p>}
          {step.result != null && <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", maxHeight: 240, overflowY: "auto", fontSize: 13, marginTop: 8 }}>{resultText(step.result)}</pre>}
        </section>)}
      </>}
  </GlassCard>;
}
