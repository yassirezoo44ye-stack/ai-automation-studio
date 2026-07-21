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
import { GlassCard } from "../../../shared/ui/gold";
import { CardGrid, ErrorNote, ProbeCard, Skeletons } from "../components";
import type { HealthReport, ServiceStatus } from "../types";

const SERVICE_COLOR: Record<string, string> = {
  running: "var(--green)", starting: "var(--blue)", stopped: "var(--t4)", stopping: "var(--yellow)", failed: "var(--red)",
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
    void Promise.resolve().then(load);
    const id = setInterval(() => void load(), 20000);
    return () => clearInterval(id);
  }, [load]);

  if (error && !health) return <ErrorNote onRetry={() => void load()}>Could not load plugin/service health.</ErrorNote>;
  if (!health || !services) return <Skeletons n={3} />;

  const pluginProbe = health.probes.find(p => p.name === "plugin_loader");

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      {pluginProbe && (
        <div>
          <div style={{ fontSize: 14, fontWeight: 600, color: "var(--t1)", letterSpacing: "-0.1px", marginBottom: 12 }}>Plugin loader</div>
          <CardGrid><ProbeCard probe={pluginProbe} /></CardGrid>
          <div style={{ fontSize: 13, color: "var(--t3)", lineHeight: 1.5, marginTop: 10 }}>
            For per-plugin install detail, see the <span style={{ color: "var(--accent-2)" }}>Plugins</span> page.
          </div>
        </div>
      )}

      <div>
        <div style={{ fontSize: 14, fontWeight: 600, color: "var(--t1)", letterSpacing: "-0.1px", marginBottom: 12 }}>Background services</div>
        <GlassCard lift={false}>
          {services.map((s, i) => (
            <div key={s.name} style={{
              display: "flex", alignItems: "center", gap: 12,
              padding: "10px 4px", borderTop: i > 0 ? "1px solid var(--border)" : "none",
            }}>
              <span style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", minWidth: 70, color: SERVICE_COLOR[s.state] ?? "var(--t4)" }}>
                {s.state}
              </span>
              <span style={{ fontSize: 13, fontWeight: 600, color: "var(--t1)", flex: 1 }}>{s.name}</span>
              <span style={{ fontSize: 11, color: "var(--t4)" }}>uptime {(s.uptime_s / 60).toFixed(0)}m</span>
              <span style={{ fontSize: 11, color: "var(--t4)" }}>restarts {s.restarts}</span>
              {s.error && <span style={{ fontSize: 11, color: "var(--red)" }}>{s.error}</span>}
            </div>
          ))}
        </GlassCard>
      </div>
    </div>
  );
}
