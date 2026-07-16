/**
 * PluginHealthTab — the plugin_loader health probe plus every registered
 * background service's own health (ServiceRegistry — health_monitor,
 * dependency_monitor, security_monitor, performance_optimizer,
 * memory_compactor, system_metrics, alerting). Per-plugin install detail
 * already lives on the Plugins page, linked here rather than duplicated.
 * Data: GET /api/diagnostics/health, GET /api/diagnostics/services.
 */
import { useEffect, useState, useCallback } from "react";
import { apiFetch, parseJSON } from "../../../shared/utils/api";
import { S } from "../../../styles/theme";
import { CardGrid, ErrorNote, ProbeCard, Skeletons } from "../components";
import type { HealthReport, ServiceStatus } from "../types";

const SERVICE_COLOR: Record<string, string> = {
  running: "#00C853", starting: "#E8C87D", stopped: "var(--t4)", stopping: "#FFB300", failed: "#FF5252",
};

export function PluginHealthTab() {
  const [health, setHealth] = useState<HealthReport | null>(null);
  const [services, setServices] = useState<ServiceStatus[] | null>(null);
  const [error, setError] = useState(false);

  const load = useCallback(async () => {
    try {
      const [h, s] = await Promise.all([
        apiFetch("/api/diagnostics/health").then(r => { if (!r.ok) throw new Error(); return parseJSON<HealthReport>(r, "/api/diagnostics/health"); }),
        apiFetch("/api/diagnostics/services").then(r => { if (!r.ok) throw new Error(); return parseJSON<{ services: ServiceStatus[] }>(r, "/api/diagnostics/services"); }),
      ]);
      setHealth(h);
      setServices(s.services);
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

  if (error && !health) return <ErrorNote>Could not load plugin/service health.</ErrorNote>;
  if (!health || !services) return <Skeletons n={3} />;

  const pluginProbe = health.probes.find(p => p.name === "plugin_loader");

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      {pluginProbe && (
        <div>
          <div style={{ ...S.cardTitle, marginBottom: 12 }}>Plugin loader</div>
          <CardGrid><ProbeCard probe={pluginProbe} /></CardGrid>
          <div style={{ ...S.muted, marginTop: 10 }}>
            For per-plugin install detail, see the <span style={{ color: "#FFE58A" }}>Plugins</span> page.
          </div>
        </div>
      )}

      <div>
        <div style={{ ...S.cardTitle, marginBottom: 12 }}>Background services</div>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {services.map(s => (
            <div key={s.name} style={{
              display: "flex", alignItems: "center", gap: 12,
              background: "var(--bg-surface)", border: "1px solid var(--border)", borderRadius: 10, padding: "10px 16px",
            }}>
              <span style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", minWidth: 70, color: SERVICE_COLOR[s.state] ?? "var(--t4)" }}>
                {s.state}
              </span>
              <span style={{ fontSize: 13, fontWeight: 600, color: "var(--t1)", flex: 1 }}>{s.name}</span>
              <span style={{ fontSize: 11, color: "var(--t4)" }}>uptime {(s.uptime_s / 60).toFixed(0)}m</span>
              <span style={{ fontSize: 11, color: "var(--t4)" }}>restarts {s.restarts}</span>
              {s.error && <span style={{ fontSize: 11, color: "#FF5252" }}>{s.error}</span>}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
