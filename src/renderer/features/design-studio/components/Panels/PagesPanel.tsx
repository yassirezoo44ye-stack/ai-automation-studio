/**
 * PagesPanel — full multi-page document manager.
 * Supports page selection, rename, duplicate, reorder (up/down), and delete.
 */
import { useState, useRef } from "react";
import { useDesign } from "../../stores/designStore";

const s: Record<string, React.CSSProperties> = {
  root:    { display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" },
  header:  { padding: "10px 12px 6px", display: "flex", alignItems: "center", justifyContent: "space-between" },
  title:   { fontSize: "11px", fontWeight: 600, color: "#6b7280", textTransform: "uppercase", letterSpacing: "0.05em" },
  addBtn:  { padding: "3px 8px", fontSize: "18px", lineHeight: 1, background: "#4f46e5", color: "#fff", border: "none", borderRadius: "4px", cursor: "pointer" },
  list:    { flex: 1, overflowY: "auto", padding: "4px 8px" },
  item:    { display: "flex", alignItems: "center", gap: "8px", padding: "6px 8px", borderRadius: "6px", marginBottom: "4px", cursor: "pointer", userSelect: "none" as const },
  thumb:   { width: "56px", height: "32px", borderRadius: "3px", border: "1px solid #374151", background: "#1f2937", flexShrink: 0, overflow: "hidden", display: "flex", alignItems: "center", justifyContent: "center", fontSize: "10px", color: "#6b7280" },
  thumbImg:{ width: "100%", height: "100%", objectFit: "cover" as const },
  meta:    { flex: 1, minWidth: 0 },
  name:    { fontSize: "12px", color: "#f9fafb", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" as const },
  nameInput: { fontSize: "12px", color: "#f9fafb", background: "transparent", border: "none", borderBottom: "1px solid #4f46e5", outline: "none", width: "100%" },
  actions: { display: "flex", gap: "2px", flexShrink: 0 },
  btn:     { padding: "2px 5px", fontSize: "11px", background: "transparent", color: "#6b7280", border: "none", borderRadius: "3px", cursor: "pointer" },
};

export function PagesPanel() {
  const { state, dispatch, setPage, duplicatePage, removePage, reorderPage, renamePage } = useDesign();
  const { pages, currentPageId } = state.project;
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  const startRename = (id: string, name: string) => {
    setEditingId(id);
    setEditValue(name);
    setTimeout(() => inputRef.current?.focus(), 0);
  };

  const commitRename = () => {
    if (editingId && editValue.trim()) renamePage(editingId, editValue.trim());
    setEditingId(null);
  };

  const addPage = () => {
    dispatch({
      type: "ADD_PAGE",
      page: {
        id: `p_${Date.now()}`,
        name: `Page ${pages.length + 1}`,
        width: 1280,
        height: 720,
        backgroundColor: "#ffffff",
        json: { version: "6.6.0", objects: [] },
        thumbnail: "",
      },
    });
  };

  return (
    <div style={s.root}>
      <div style={s.header}>
        <span style={s.title}>Pages ({pages.length})</span>
        <button style={s.addBtn} onClick={addPage} title="Add page">+</button>
      </div>

      <div style={s.list}>
        {pages.map((page, idx) => {
          const active = page.id === currentPageId;
          return (
            <div
              key={page.id}
              style={{
                ...s.item,
                background: active ? "#312e81" : "transparent",
                border: `1px solid ${active ? "#4f46e5" : "transparent"}`,
              }}
              onClick={() => setPage(page.id)}
              onDoubleClick={() => startRename(page.id, page.name)}
              aria-label={`Page ${idx + 1}: ${page.name}`}
              role="button"
              tabIndex={0}
              onKeyDown={e => e.key === "Enter" && setPage(page.id)}
            >
              {/* Thumbnail */}
              <div style={s.thumb}>
                {page.thumbnail
                  ? <img src={page.thumbnail} style={s.thumbImg} alt="" />
                  : <span>{idx + 1}</span>
                }
              </div>

              {/* Name */}
              <div style={s.meta}>
                {editingId === page.id ? (
                  <input
                    ref={inputRef}
                    style={s.nameInput}
                    value={editValue}
                    onChange={e => setEditValue(e.target.value)}
                    onBlur={commitRename}
                    onKeyDown={e => { if (e.key === "Enter") commitRename(); if (e.key === "Escape") setEditingId(null); }}
                    onClick={e => e.stopPropagation()}
                    aria-label="Rename page"
                  />
                ) : (
                  <div style={s.name} title={page.name}>{page.name}</div>
                )}
              </div>

              {/* Actions */}
              <div style={s.actions} onClick={e => e.stopPropagation()}>
                <button
                  style={s.btn}
                  title="Move up"
                  disabled={idx === 0}
                  onClick={() => reorderPage(idx, idx - 1)}
                  aria-label="Move page up"
                >↑</button>
                <button
                  style={s.btn}
                  title="Move down"
                  disabled={idx === pages.length - 1}
                  onClick={() => reorderPage(idx, idx + 1)}
                  aria-label="Move page down"
                >↓</button>
                <button
                  style={s.btn}
                  title="Duplicate"
                  onClick={() => duplicatePage(page.id)}
                  aria-label="Duplicate page"
                >⧉</button>
                <button
                  style={{ ...s.btn, color: pages.length <= 1 ? "#374151" : "#ef4444" }}
                  title="Delete"
                  disabled={pages.length <= 1}
                  onClick={() => removePage(page.id)}
                  aria-label="Delete page"
                >✕</button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
