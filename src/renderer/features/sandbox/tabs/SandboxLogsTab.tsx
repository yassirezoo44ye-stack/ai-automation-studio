/**
 * SandboxLogsTab — a worker's sandbox_events history (log/network/security/
 * resource/lifecycle events), mirrors plugins/tabs/HealthTab.tsx's list
 * shape adapted to sandbox_events' event_type/severity columns.
 * Data: GET /sandbox/workers/{id}/logs
 */
import { useState, useEffect } from "react";
import { apiFetch, parseJSON } from "../../../shared/utils/api";

interface SandboxEvent {
  event_type: string;
  severity: string;
  message: string | null;
  details: Record<string, unknown>;
  created_at: string;
}

const SEVERITY_COLOR: Record<string, string> = {
  info: "var(--t4)", warning: "#f59e0b", error: "#f87171",
};

export function SandboxLogsTab({ workerId }: { workerId: string }) {
  const [logs, setLogs] = useState<SandboxEvent[] | null>(null);

  useEffect(() => {
    let alive = true;
    setLogs(null);
    (async () => {
      try {
        const r = await apiFetch(`/sandbox/workers/${workerId}/logs`);
        if (!r.ok) throw new Error();
        const d = await parseJSON<SandboxEvent[]>(r, "sandbox logs");
        if (alive) setLogs(d);
      } catch { if (alive) setLogs([]); }
    })();
    return () => { alive = false; };
  }, [workerId]);

  if (logs === null) {
    return <div style={{ fontSize: 12, color: "var(--t4)" }}>Loading logs…</div>;
  }
  if (logs.length === 0) {
    return <div style={{ fontSize: 12, color: "var(--t4)" }}>No events recorded yet.</div>;
  }
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      {logs.map((l, i) => (
        <div key={`${l.created_at}-${i}`} style={{ display: "flex", gap: 10, fontSize: 12, borderTop: i > 0 ? "1px solid var(--border)" : "none", paddingTop: i > 0 ? 6 : 0 }}>
          <span style={{ color: SEVERITY_COLOR[l.severity] ?? "var(--t4)", fontWeight: 700, textTransform: "uppercase", fontSize: 10, minWidth: 70 }}>
            {l.event_type}
          </span>
          <span style={{ color: "var(--t3)", flex: 1 }}>{l.message}</span>
          <span style={{ color: "var(--t5)", fontSize: 11 }}>{new Date(l.created_at).toLocaleString()}</span>
        </div>
      ))}
    </div>
  );
}
