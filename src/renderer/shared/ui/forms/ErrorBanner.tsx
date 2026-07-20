import { GoldButton } from "../gold";

export function ErrorBanner({
  message, suggestedFix, onRetry, onDismiss,
}: {
  message: string;
  suggestedFix?: string | null;
  onRetry?: () => void;
  onDismiss?: () => void;
}) {
  return (
    <div className="g-error-banner" role="alert">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ flexShrink: 0, marginTop: 1 }} aria-hidden="true">
        <circle cx="12" cy="12" r="10" /><line x1="12" y1="8" x2="12" y2="12" /><line x1="12" y1="16" x2="12.01" y2="16" />
      </svg>
      <div style={{ flex: 1 }}>
        <div>{message}</div>
        {suggestedFix && <div style={{ opacity: 0.85, marginTop: 2 }}>{suggestedFix}</div>}
        {onRetry && (
          <div style={{ marginTop: 8 }}>
            <GoldButton variant="ghost" onClick={onRetry}>Retry</GoldButton>
          </div>
        )}
      </div>
      {onDismiss && (
        <button type="button" onClick={onDismiss} aria-label="Dismiss" style={{ background: "none", border: "none", color: "inherit", cursor: "pointer", fontSize: 16, lineHeight: 1, padding: 0 }}>×</button>
      )}
    </div>
  );
}
