interface Props {
  lines?: number;
  className?: string;
  width?: string;
  height?: string;
  circle?: boolean;
}

export function SkeletonLoader({ lines = 1, className = "", width, height, circle }: Props) {
  if (lines === 1) {
    return (
      <div
        className={`skeleton ${circle ? "skeleton-avatar" : "skeleton-text"} ${className}`}
        style={{ width: width ?? "100%", height: height ?? (circle ? (width ?? "40px") : undefined) }}
        role="status"
        aria-label="Loading…"
      />
    );
  }
  return (
    <div className={`skeleton-lines ${className}`} role="status" aria-label="Loading…" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {Array.from({ length: lines }, (_, i) => (
        <div
          key={i}
          className="skeleton skeleton-text"
          style={{ width: i === lines - 1 ? "60%" : "100%" }}
        />
      ))}
    </div>
  );
}

export function SkeletonCard({ className = "" }: { className?: string }) {
  return (
    <div className={`skeleton skeleton-card ${className}`} style={{ minHeight: 80 }} role="status" aria-label="Loading…">
      <div style={{ display: "flex", gap: 12, alignItems: "center", marginBottom: 12 }}>
        <div className="skeleton skeleton-avatar" style={{ width: 36, height: 36, flexShrink: 0 }} />
        <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 6 }}>
          <div className="skeleton skeleton-title" style={{ width: "55%" }} />
          <div className="skeleton skeleton-text"  style={{ width: "35%" }} />
        </div>
      </div>
      <div className="skeleton skeleton-text" style={{ marginBottom: 6 }} />
      <div className="skeleton skeleton-text" style={{ width: "80%" }} />
    </div>
  );
}
