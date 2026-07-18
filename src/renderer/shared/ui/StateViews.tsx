/**
 * The two view states every data-driven panel needs beyond loading/success:
 * ErrorState (with retry) and EmptyState (zero results — not a failure).
 * Pairs with useAsyncData; loading itself reuses LoadingSpinner.
 */
import type { ReactNode } from "react";
import { GoldButton } from "./gold";

export function ErrorState({
  message, suggestedFix, onRetry, compact = false,
}: {
  message: string;
  suggestedFix?: string | null;
  onRetry: () => void;
  compact?: boolean;
}) {
  return (
    <div
      role="alert"
      style={{
        flex: compact ? undefined : 1,
        display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
        gap: 10, padding: compact ? "20px 16px" : "40px 20px", textAlign: "center",
      }}
    >
      <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="var(--red, #FF5252)" strokeWidth="1.75" strokeLinecap="round">
        <circle cx="12" cy="12" r="10" /><line x1="12" y1="8" x2="12" y2="12" /><line x1="12" y1="16" x2="12.01" y2="16" />
      </svg>
      <div style={{ fontSize: 13.5, color: "var(--t2)", maxWidth: 340, lineHeight: 1.5 }}>{message}</div>
      {suggestedFix && (
        <div style={{ fontSize: 12, color: "var(--t5)", maxWidth: 340 }}>{suggestedFix}</div>
      )}
      <GoldButton variant="ghost" onClick={onRetry}>Retry</GoldButton>
    </div>
  );
}

export function EmptyState({
  icon, title, description, action, compact = false,
}: {
  icon?: ReactNode;
  title: string;
  description?: string;
  action?: ReactNode;
  compact?: boolean;
}) {
  return (
    <div
      style={{
        flex: compact ? undefined : 1,
        display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
        gap: 8, padding: compact ? "20px 16px" : "40px 20px", textAlign: "center",
      }}
    >
      {icon && (
        <div style={{
          width: 48, height: 48, borderRadius: 14, display: "flex", alignItems: "center", justifyContent: "center",
          background: "var(--accent-dim)", border: "1px solid var(--accent-border)", color: "var(--accent-2)",
        }}>
          {icon}
        </div>
      )}
      <div style={{ fontSize: 14, fontWeight: 600, color: "var(--t2)" }}>{title}</div>
      {description && <div style={{ fontSize: 12.5, color: "var(--t5)", maxWidth: 300, lineHeight: 1.5 }}>{description}</div>}
      {action}
    </div>
  );
}
