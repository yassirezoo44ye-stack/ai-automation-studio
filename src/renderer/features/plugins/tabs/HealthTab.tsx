/**
 * HealthTab — current status + recent event log.
 * Data: GET /plugins/installed/{id}/health, GET /plugins/installed/{id}/logs
 */
import { useState, useEffect } from "react";
import { apiFetch, parseJSON } from "../../../shared/utils/api";

interface LogEntry { event: string; message: string | null; created_at: string }

const EVENT_COLOR: Record<string, string> = {
  load: "#00C853", unload: "var(--t4)", reload: "#E8C87D", error: "#FF5252", tick: "var(--t4)",
};

export function HealthTab({ installationId, status }: { installationId: string; status: string }) {
  const [logs, setLogs] = useState<LogEntry[] | null>(null);

  useEffect(() => {
    let alive = true;
    setLogs(null);
    (async () => {
      try {
        const r = await apiFetch(`/plugins/installed/${installationId}/logs`);
        if (!r.ok) throw new Error();
        const d = await parseJSON<LogEntry[]>(r, "plugin logs");
        if (alive) setLogs(d);
      } catch { if (alive) setLogs([]); }
    })();
    return () => { alive = false; };
  }, [installationId]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ fontSize: 12, color: "var(--t4)" }}>Status:</span>
        <span style={{
          fontSize: 12, fontWeight: 700, textTransform: "uppercase",
          color: status === "enabled" ? "#00C853" : status === "failed" ? "#FF5252" : "var(--t3)",
        }}>
          {status}
        </span>
      </div>
      {logs === null ? (
        <div style={{ fontSize: 12, color: "var(--t4)" }}>Loading logs…</div>
      ) : logs.length === 0 ? (
        <div style={{ fontSize: 12, color: "var(--t4)" }}>No events recorded yet.</div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {logs.map((l, i) => (
            <div key={i} style={{ display: "flex", gap: 10, fontSize: 12, borderTop: i > 0 ? "1px solid var(--border)" : "none", paddingTop: i > 0 ? 6 : 0 }}>
              <span style={{ color: EVENT_COLOR[l.event] ?? "var(--t4)", fontWeight: 700, textTransform: "uppercase", fontSize: 10, minWidth: 50 }}>
                {l.event}
              </span>
              <span style={{ color: "var(--t3)", flex: 1 }}>{l.message}</span>
              <span style={{ color: "var(--t5)", fontSize: 11 }}>{new Date(l.created_at).toLocaleString()}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
