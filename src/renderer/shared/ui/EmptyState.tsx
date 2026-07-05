import type { ReactNode } from "react";

interface Props {
  icon?: ReactNode;
  title: string;
  description?: string;
  action?: ReactNode;
}

export function EmptyState({ icon, title, description, action }: Props) {
  return (
    <div className="empty-state" style={{ direction: "ltr", padding: "48px 24px" }}>
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
