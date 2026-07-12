/**
 * ResourceUsageTab — peak CPU/memory columns for one worker. Deliberately
 * plain numbers, no charting library or time-series — the phase explicitly
 * excludes an OpenTelemetry-style metrics pipeline; sandbox_workers only
 * stores peak values, matching usage_records' counter style elsewhere in
 * this codebase.
 * Data: GET /sandbox/workers/{id}/resource-usage
 */
import { useState, useEffect } from "react";
import { apiFetch, parseJSON } from "../../../shared/utils/api";

interface ResourceUsage {
  worker_id: string;
  backend: string;
  status: string;
  cpu_seconds_used: number | null;
  memory_mb_peak: number | null;
}

export function ResourceUsageTab({ workerId }: { workerId: string }) {
  const [usage, setUsage] = useState<ResourceUsage | null>(null);

  useEffect(() => {
    let alive = true;
    setUsage(null);
    (async () => {
      try {
        const r = await apiFetch(`/sandbox/workers/${workerId}/resource-usage`);
        if (!r.ok) throw new Error();
        const d = await parseJSON<ResourceUsage>(r, "resource usage");
        if (alive) setUsage(d);
      } catch { /* leave null -> shows loading state indefinitely on error, acceptable for a read-only stat panel */ }
    })();
    return () => { alive = false; };
  }, [workerId]);

  if (usage === null) {
    return <div style={{ fontSize: 12, color: "var(--t4)" }}>Loading…</div>;
  }

  const cells: [string, string][] = [
    ["Backend", usage.backend],
    ["Status", usage.status],
    ["CPU seconds used", usage.cpu_seconds_used != null ? usage.cpu_seconds_used.toFixed(2) : "—"],
    ["Peak memory (MB)", usage.memory_mb_peak != null ? usage.memory_mb_peak.toFixed(1) : "—"],
  ];

  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 12 }}>
      {cells.map(([label, value]) => (
        <div key={label} style={{ background: "rgba(255,255,255,.03)", border: "1px solid var(--border)", borderRadius: 10, padding: "10px 14px" }}>
          <div style={{ fontSize: 10, color: "var(--t5)", textTransform: "uppercase", fontWeight: 700, marginBottom: 4 }}>{label}</div>
          <div style={{ fontSize: 14, color: "var(--t2)", fontWeight: 600 }}>{value}</div>
        </div>
      ))}
    </div>
  );
}
