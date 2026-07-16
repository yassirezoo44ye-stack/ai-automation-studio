/**
 * ProvidersTab — provider availability + circuit breaker state.
 * Data: GET /api/ai/providers (app/routers/ai_router_api.py, reads
 * PlatformProviderRegistry.health() + app/ai/circuit_breaker.py).
 */
import { useEffect, useState } from "react";
import { apiFetch, parseJSON } from "../../../shared/utils/api";
import { S } from "../../../styles/theme";

interface ProviderHealth {
  available: boolean;
  provider_id: string;
  default_model: string | null;
  circuit_state: "closed" | "open" | "half_open";
}

const CIRCUIT_COLOR: Record<string, string> = {
  closed: "#00C853", half_open: "#FFB300", open: "#FF5252",
};

export function ProvidersTab() {
  const [providers, setProviders] = useState<Record<string, ProviderHealth> | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const r = await apiFetch("/api/ai/providers");
        if (!r.ok) throw new Error();
        const d = await parseJSON<{ providers: Record<string, ProviderHealth> }>(r, "/api/ai/providers");
        if (alive) setProviders(d.providers);
      } catch {
        if (alive) setError(true);
      }
    })();
    return () => { alive = false; };
  }, []);

  if (error) {
    return <div style={{ fontSize: 12, color: "var(--t4)" }}>Could not load provider health.</div>;
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
        <div key={p.provider_id} style={S.card}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
            <span style={S.cardTitle}>{p.provider_id}</span>
            <span style={{
              ...S.badge, ...(p.available ? S.badgeSuccess : S.badgeNeutral),
            }}>
              <span style={S.dot} /> {p.available ? "configured" : "not configured"}
            </span>
          </div>
          <div style={{ ...S.muted, marginBottom: 10 }}>
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
        </div>
      ))}
    </div>
  );
}
