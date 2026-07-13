// Small shared presentational pieces used by every tab in this feature —
// avoids re-deriving the same status-color / card-grid markup 10 times.
import type { ReactNode } from "react";
import { S } from "../../styles/theme";
import type { HealthStatus, ProbeResult } from "./types";

export function StatusBadge({ status }: { status: HealthStatus }) {
  const badgeStyle =
    status === "healthy" ? S.badgeSuccess :
    status === "degraded" ? S.badgeWarning :
    status === "unhealthy" ? S.badgeError : S.badgeNeutral;
  return (
    <span style={{ ...S.badge, ...badgeStyle }}>
      <span style={S.dot} /> {status}
    </span>
  );
}

export function ProbeCard({ probe }: { probe: ProbeResult }) {
  return (
    <div style={S.card}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
        <span style={S.cardTitle}>{probe.name}</span>
        <StatusBadge status={probe.status} />
      </div>
      <div style={{ ...S.muted, marginBottom: 8 }}>{probe.message || "—"}</div>
      <div style={{ fontSize: 11, color: "var(--t4)" }}>{probe.duration_ms.toFixed(1)}ms</div>
    </div>
  );
}

export function MetricCard({ label, value, suffix = "" }: { label: string; value: number | string; suffix?: string }) {
  return (
    <div style={S.card}>
      <div style={{ ...S.muted, marginBottom: 6 }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 700, color: "var(--t1)" }}>
        {typeof value === "number" ? value.toLocaleString(undefined, { maximumFractionDigits: 2 }) : value}{suffix}
      </div>
    </div>
  );
}

export function CardGrid({ children }: { children: ReactNode }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 14 }}>
      {children}
    </div>
  );
}

export function Skeletons({ n = 3, height = 90 }: { n?: number; height?: number }) {
  return (
    <div style={{ display: "grid", gap: 12 }}>
      {Array.from({ length: n }, (_, i) => (
        <div key={i} className="skeleton" style={{ height, borderRadius: 14 }} />
      ))}
    </div>
  );
}

export function ErrorNote({ children }: { children: ReactNode }) {
  return <div style={{ fontSize: 12, color: "var(--t4)" }}>{children}</div>;
}

export function EmptyNote({ children }: { children: ReactNode }) {
  return <div style={{ textAlign: "center", padding: "48px 0", color: "var(--t4)", fontSize: 13 }}>{children}</div>;
}
