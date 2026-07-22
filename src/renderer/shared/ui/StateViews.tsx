/**
 * The two view states every data-driven panel needs beyond loading/success:
 * ErrorState (with retry) and EmptyState (zero results — not a failure).
 * Pairs with useAsyncData; loading itself reuses LoadingSpinner.
 *
 * EmptyState re-exports shared/ui/EmptyState.tsx — that's the canonical
 * implementation (Billing/Teams/Organizations/Sandbox/Plugins/AI Routing/
 * Observability all import it directly); this file used to define a
 * second, near-identical component instead of reusing it.
 */
import { GoldButton } from "./gold";

export { EmptyState } from "./EmptyState";

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
