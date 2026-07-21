// Small shared presentational pieces used by every tab in this feature —
// avoids re-deriving the same status-color / card-grid markup 10 times.
import type { ReactNode } from "react";
import { GlassCard, GoldButton } from "../../shared/ui/gold";
import { EmptyState } from "../../shared/ui/EmptyState";
import { StatusBadge as SharedStatusBadge } from "../../shared/ui/StatusBadge";
import type { HealthStatus, ProbeResult } from "./types";

const HEALTH_KIND = {
  healthy: "success", degraded: "warning", unhealthy: "error", unknown: "neutral",
} as const;

export function StatusBadge({ status }: { status: HealthStatus }) {
  return <SharedStatusBadge kind={HEALTH_KIND[status]} label={status} />;
}

export function ProbeCard({ probe }: { probe: ProbeResult }) {
  return (
    <GlassCard lift={false}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
        <span style={{ fontSize: 14, fontWeight: 600, color: "var(--t1)", letterSpacing: "-0.1px" }}>{probe.name}</span>
        <StatusBadge status={probe.status} />
      </div>
      <div style={{ fontSize: 13, color: "var(--t3)", lineHeight: 1.5, marginBottom: 8 }}>{probe.message || "—"}</div>
      <div style={{ fontSize: 11, color: "var(--t4)" }}>{probe.duration_ms.toFixed(1)}ms</div>
    </GlassCard>
  );
}

export function MetricCard({ label, value, suffix = "" }: { label: string; value: number | string; suffix?: string }) {
  return (
    <GlassCard lift={false}>
      <div style={{ fontSize: 13, color: "var(--t3)", marginBottom: 6 }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 700, color: "var(--t1)" }}>
        {typeof value === "number" ? value.toLocaleString(undefined, { maximumFractionDigits: 2 }) : value}{suffix}
      </div>
    </GlassCard>
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

export function ErrorNote({ children, onRetry }: { children: ReactNode; onRetry?: () => void }) {
  return (
    <EmptyState
      icon={<span style={{ fontSize: 40 }}>⚠️</span>}
      title="Could not load this data"
      description={typeof children === "string" ? children : undefined}
      action={onRetry ? <GoldButton variant="ghost" onClick={onRetry}>Retry</GoldButton> : undefined}
    />
  );
}

export function EmptyNote({ children }: { children: ReactNode }) {
  return (
    <EmptyState title={typeof children === "string" ? children : "Nothing here yet"} />
  );
}
