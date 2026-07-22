import type { ReactNode } from "react";

interface Props {
  icon?: ReactNode;
  title: string;
  description?: string;
  action?: ReactNode;
  /** Tighter padding/gap for inline use (a panel or sidebar), instead of
   * this page's whole content area. */
  compact?: boolean;
}

export function EmptyState({ icon, title, description, action, compact = false }: Props) {
  return (
    <div
      className="empty-state"
      style={{ direction: "ltr", padding: compact ? "20px 16px" : "48px 24px" }}
    >
      {icon && <div style={{ marginBottom: 16, opacity: 0.5 }}>{icon}</div>}
      <div style={{ fontWeight: 600, color: "var(--t2)", marginBottom: 6 }}>{title}</div>
      {description && (
        <div style={{ fontSize: 13, color: "var(--t4)", maxWidth: 320, lineHeight: 1.6 }}>
          {description}
        </div>
      )}
      {action && <div style={{ marginTop: 16 }}>{action}</div>}
    </div>
  );
}
