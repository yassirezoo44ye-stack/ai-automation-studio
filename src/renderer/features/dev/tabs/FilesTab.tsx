/**
 * FilesTab — dual-pane file tree + code viewer.
 */
import { fileIcon } from "../../../utils/files";
import type { BuildFile } from "../../../shared/types";

interface FilesTabProps {
  files:      { path: string; content?: string }[];
  activeFile: BuildFile | null;
  onSelect:   (f: { path: string; content?: string }) => void;
}

const TREE_ITEM: React.CSSProperties = {
  padding: "7px 14px", cursor: "pointer", fontSize: 12,
  display: "flex", gap: 6, alignItems: "center", transition: "background .15s",
  userSelect: "none",
};

export function FilesTab({ files, activeFile, onSelect }: FilesTabProps) {
  return (
    <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>
      {/* File tree */}
      <nav
        style={{ width: 220, borderRight: "1px solid rgba(255,255,255,0.06)", overflowY: "auto", background: "#0a0c10", flexShrink: 0 }}
        aria-label="File tree"
      >
        {files.length === 0 && (
          <div style={{ padding: "40px 16px", fontSize: 12, color: "var(--t5)", textAlign: "center" }}>
            No files yet
          </div>
        )}
        {files.map(f => {
          const active = activeFile?.path === f.path;
          return (
            <div
              key={f.path}
              role="button"
              tabIndex={0}
              onClick={() => onSelect(f)}
              onKeyDown={e => e.key === "Enter" && onSelect(f)}
              style={{
                ...TREE_ITEM,
                color:       active ? "#e2e8f0" : "rgba(148,163,184,.7)",
                background:  active ? "rgba(139,92,246,.12)" : "transparent",
                borderLeft:  active ? "2px solid #8b5cf6" : "2px solid transparent",
              }}
              aria-current={active ? "true" : undefined}
              title={f.path}
            >
              <span aria-hidden="true">{fileIcon(f.path)}</span>
              <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {f.path}
              </span>
            </div>
          );
        })}
      </nav>

      {/* Code viewer */}
      <div style={{ flex: 1, overflow: "auto", background: "#080a0f" }}>
        {activeFile ? (
          <>
            <div style={{
              padding: "10px 20px", borderBottom: "1px solid #1e2438",
              fontSize: 12, color: "#6b7a99",
              display: "flex", justifyContent: "space-between", alignItems: "center",
              position: "sticky", top: 0, background: "#080a0f", zIndex: 1,
            }}>
              <span>{fileIcon(activeFile.path)} {activeFile.path}</span>
              <span>{activeFile.content.split("\n").length} lines</span>
            </div>
            <pre style={{
              margin: 0, padding: "16px 20px", fontSize: 13,
              color: "#c8d3f0", lineHeight: 1.6,
              fontFamily: "var(--font-mono)", overflowX: "auto",
            }}>
              <code>{activeFile.content}</code>
            </pre>
          </>
        ) : (
          <div style={{
            display: "flex", alignItems: "center", justifyContent: "center",
            height: "100%", color: "var(--t5)", flexDirection: "column", gap: 10,
          }}>
            <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.2" aria-hidden="true">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
              <polyline points="14 2 14 8 20 8"/>
            </svg>
            <span style={{ fontSize: 13 }}>Select a file from the tree</span>
          </div>
        )}
      </div>
    </div>
  );
}
