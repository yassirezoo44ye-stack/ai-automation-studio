/**
 * AlertsTracesTab — alert rules (toggle enable/disable) + fired alert
 * history, plus recent distributed traces.
 * Data: GET/POST /api/diagnostics/alerts/rules, POST .../toggle,
 *       GET /api/diagnostics/alerts/history, GET /api/diagnostics/traces.
 */
import { useEffect, useState, useCallback } from "react";
import { apiFetch, parseJSON } from "../../../shared/utils/api";
import { useToast } from "../../../contexts/ToastContext";
import { S } from "../../../styles/theme";
import { EmptyNote, ErrorNote, Skeletons } from "../components";
import type { AlertHistoryEntry, AlertRule, TraceSpan } from "../types";

type SubTab = "rules" | "history" | "traces";

export function AlertsTracesTab() {
  const toast = useToast();
  const [sub, setSub] = useState<SubTab>("rules");
  const [rules, setRules] = useState<AlertRule[] | null>(null);
  const [history, setHistory] = useState<AlertHistoryEntry[] | null>(null);
  const [traces, setTraces] = useState<TraceSpan[] | null>(null);
  const [error, setError] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [r, h, t] = await Promise.all([
        apiFetch("/api/diagnostics/alerts/rules").then(res => { if (!res.ok) throw new Error(); return parseJSON<{ rules: AlertRule[] }>(res, "/api/diagnostics/alerts/rules"); }),
        apiFetch("/api/diagnostics/alerts/history?limit=50").then(res => { if (!res.ok) throw new Error(); return parseJSON<{ history: AlertHistoryEntry[] }>(res, "/api/diagnostics/alerts/history"); }),
        apiFetch("/api/diagnostics/traces?n=50").then(res => { if (!res.ok) throw new Error(); return parseJSON<{ traces: TraceSpan[] }>(res, "/api/diagnostics/traces"); }),
      ]);
      setRules(r.rules);
      setHistory(h.history);
      setTraces(t.traces);
      setError(false);
    } catch {
      setError(true);
    }
  }, []);

  useEffect(() => {
    void load();
    const id = setInterval(() => void load(), 20000);
    return () => clearInterval(id);
  }, [load]);

  const toggleRule = async (rule: AlertRule) => {
    setBusy(rule.id);
    try {
      const r = await apiFetch(`/api/diagnostics/alerts/rules/${rule.id}/toggle?enabled=${!rule.enabled}`, { method: "POST" });
      if (!r.ok) throw new Error();
      toast(rule.enabled ? "Rule disabled" : "Rule enabled", "ok");
      await load();
    } catch {
      toast("Could not toggle rule", "err");
    } finally {
      setBusy(null);
    }
  };

  if (error && !rules) return <ErrorNote>Could not load alerting/tracing data.</ErrorNote>;
  if (!rules || !history || !traces) return <Skeletons n={3} />;

  const openCount = history.filter(h => !h.resolved_at).length;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ display: "flex", gap: 6 }}>
        {([
          ["rules", `Rules (${rules.length})`],
          ["history", `History${openCount ? ` — ${openCount} open` : ""}`],
          ["traces", `Traces (${traces.length})`],
        ] as [SubTab, string][]).map(([id, label]) => (
          <button key={id} onClick={() => setSub(id)} style={{ ...(sub === id ? S.btnPrimary : S.btnSecondary), padding: "6px 12px", fontSize: 11 }}>
            {label}
          </button>
        ))}
      </div>

      {sub === "rules" && (
        rules.length === 0 ? <EmptyNote>No alert rules configured.</EmptyNote> : (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {rules.map(rule => (
              <div key={rule.id} style={{
                display: "flex", alignItems: "center", gap: 12,
                background: "var(--bg-surface)", border: "1px solid var(--border)", borderRadius: 10, padding: "10px 16px",
              }}>
                <span style={{ fontSize: 13, fontWeight: 600, color: "var(--t1)", flex: 1 }}>{rule.name}</span>
                <span style={{ fontSize: 11, color: "var(--t4)" }}>{rule.rule_type} · {rule.target}{rule.threshold != null ? ` > ${rule.threshold}` : ""}</span>
                <button
                  onClick={() => void toggleRule(rule)}
                  disabled={busy === rule.id}
                  style={{
                    padding: "4px 10px", borderRadius: 8, border: "1px solid var(--border)", fontSize: 11, fontWeight: 600,
                    cursor: busy === rule.id ? "wait" : "pointer",
                    background: rule.enabled ? "rgba(0,200,83,.12)" : "rgba(255,255,255,.04)",
                    color: rule.enabled ? "#00C853" : "var(--t4)",
                  }}
                >
                  {busy === rule.id ? "…" : rule.enabled ? "Enabled" : "Disabled"}
                </button>
              </div>
            ))}
          </div>
        )
      )}

      {sub === "history" && (
        history.length === 0 ? <EmptyNote>No alerts have fired.</EmptyNote> : (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {history.map(h => (
              <div key={h.id} style={{
                display: "flex", alignItems: "center", gap: 12,
                background: "var(--bg-surface)", border: `1px solid ${h.resolved_at ? "var(--border)" : "rgba(255,82,82,.3)"}`,
                borderRadius: 10, padding: "10px 16px",
              }}>
                <span style={{
                  fontSize: 10, fontWeight: 700, textTransform: "uppercase", minWidth: 60,
                  color: h.resolved_at ? "var(--t4)" : "#FF5252",
                }}>
                  {h.resolved_at ? "resolved" : "open"}
                </span>
                <span style={{ fontSize: 13, fontWeight: 600, color: "var(--t1)" }}>{h.rule_name}</span>
                <span style={{ fontSize: 11, color: "var(--t3)", flex: 1 }}>{h.message}</span>
                <span style={{ fontSize: 11, color: "var(--t4)" }}>{new Date(h.fired_at).toLocaleString()}</span>
              </div>
            ))}
          </div>
        )
      )}

      {sub === "traces" && (
        traces.length === 0 ? <EmptyNote>No traces recorded yet.</EmptyNote> : (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {traces.map(t => (
              <div key={t.span_id} style={{
                display: "flex", alignItems: "center", gap: 12,
                background: "var(--bg-surface)", border: `1px solid ${t.error ? "rgba(255,82,82,.3)" : "var(--border)"}`,
                borderRadius: 10, padding: "8px 16px",
              }}>
                <span style={{ fontSize: 12, fontWeight: 600, color: "var(--t1)", minWidth: 160 }}>{t.name}</span>
                <span style={{ fontSize: 11, color: "var(--t4)" }}>{t.service}</span>
                <span style={{ fontSize: 11, color: "var(--t4)", marginLeft: "auto" }}>{t.duration_ms.toFixed(1)}ms</span>
                {t.error && <span style={{ fontSize: 11, color: "#FF5252" }}>{t.error}</span>}
              </div>
            ))}
          </div>
        )
      )}
    </div>
  );
}
