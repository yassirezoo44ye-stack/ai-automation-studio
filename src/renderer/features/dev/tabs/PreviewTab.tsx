/**
 * PreviewTab — iframe sandbox for HTML projects and server previews.
 */
import { S } from "../../../styles/theme";

interface PreviewTabProps {
  previewUrl: string | null;
  canOpenPreview: boolean;
  onOpenPreview: () => void;
}

export function PreviewTab({ previewUrl, canOpenPreview, onOpenPreview }: PreviewTabProps) {
  if (previewUrl) {
    return (
      <iframe
        src={previewUrl}
        style={{ flex: 1, border: "none", background: "#fff", width: "100%", height: "100%" }}
        title="App preview"
        sandbox={previewUrl.startsWith("blob:") ? "allow-scripts allow-same-origin" : undefined}
      />
    );
  }

  return (
    <div style={{
      flex: 1, display: "flex", alignItems: "center", justifyContent: "center",
      flexDirection: "column", gap: 16, color: "var(--t5)", padding: 24,
    }}>
      <svg width="56" height="56" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.2" aria-hidden="true">
        <rect x="2" y="3" width="20" height="14" rx="2"/>
        <line x1="8" y1="21" x2="16" y2="21"/>
        <line x1="12" y1="17" x2="12" y2="21"/>
      </svg>
      <div style={{ fontSize: 14, color: "var(--t4)", textAlign: "center" }}>
        No preview available
      </div>
      <div style={{ fontSize: 12, color: "var(--t5)", textAlign: "center", maxWidth: 300 }}>
        Build an HTML project and run it, or click below if a static preview is available.
      </div>
      {canOpenPreview && (
        <button onClick={onOpenPreview} style={{ ...S.btnPrimary, fontSize: 13 }}>
          Open HTML Preview
        </button>
      )}
    </div>
  );
}
