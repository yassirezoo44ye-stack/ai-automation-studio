/**
 * ProvidersTab — provider availability + circuit breaker state.
 * Data: GET /api/ai/providers (app/routers/ai_router_api.py, reads
 * PlatformProviderRegistry.health() + app/ai/circuit_breaker.py).
 */
import { useEffect, useState, useCallback } from "react";
import { apiFetch, parseJSON } from "../../../shared/utils/api";
import { GlassCard, GoldButton } from "../../../shared/ui/gold";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { StatusBadge } from "../../../shared/ui/StatusBadge";

interface ProviderHealth {
  available: boolean;
  provider_id: string;
  default_model: string | null;
  circuit_state: "closed" | "open" | "half_open";
}

const CIRCUIT_COLOR: Record<string, string> = {
  closed: "var(--green)", half_open: "var(--yellow)", open: "var(--red)",
};

export function ProvidersTab() {
  const [providers, setProviders] = useState<Record<string, ProviderHealth> | null>(null);
  const [error, setError] = useState(false);

  const load = useCallback(async () => {
    setError(false);
    try {
      const r = await apiFetch("/api/ai/providers");
      if (!r.ok) throw new Error();
      const d = await parseJSON<{ providers: Record<string, ProviderHealth> }>(r, "/api/ai/providers");
      setProviders(d.providers);
    } catch {
      setError(true);
    }
  }, []);

  useEffect(() => { void Promise.resolve().then(load); }, [load]);

  if (error) {
    return (
      <EmptyState
        icon={<span style={{ fontSize: 40 }}>⚠️</span>}
        title="Could not load provider health"
        description="Something went wrong reaching the server."
        action={<GoldButton variant="ghost" onClick={() => void load()}>Retry</GoldButton>}
      />
    );
  }
  if (!providers) {
    return (
      <div style={{ display: "grid", gap: 12 }}>
        {[1, 2, 3].map(i => <div key={i} className="skeleton" style={{ height: 72, borderRadius: 14 }} />)}
      </div>
    );
  }

  const entries = Object.values(providers);
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: 14 }}>
      {entries.map(p => (
        <GlassCard key={p.provider_id} lift={false}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
            <span style={{ fontSize: 14, fontWeight: 600, color: "var(--t1)", letterSpacing: "-0.1px" }}>{p.provider_id}</span>
            <StatusBadge kind={p.available ? "success" : "neutral"} label={p.available ? "configured" : "not configured"} />
          </div>
          <div style={{ fontSize: 13, color: "var(--t3)", lineHeight: 1.5, marginBottom: 10 }}>
            {p.default_model ?? "no default model — set the API key to enable"}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontSize: 11, color: "var(--t4)" }}>Circuit:</span>
            <span style={{
              fontSize: 11, fontWeight: 700, textTransform: "uppercase",
              color: CIRCUIT_COLOR[p.circuit_state] ?? "var(--t4)",
            }}>
              {p.circuit_state.replace("_", "-")}
            </span>
          </div>
        </GlassCard>
      ))}
    </div>
  );
}
