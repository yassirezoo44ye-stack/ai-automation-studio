/**
 * HistoryPanel — displays the CommandManager undo/redo stack.
 * Subscribes to CommandExecuted/Undone/Redone design bus events to stay live.
 */
import { useState, useEffect } from "react";
import { commandManager } from "../../core/commands/CommandManager";
import { designBus } from "../../core/events/DesignEventBus";

const s: Record<string, React.CSSProperties> = {
  root:    { display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" },
  header:  { padding: "10px 12px 6px", fontSize: "11px", fontWeight: 600, color: "#6b7280", textTransform: "uppercase", letterSpacing: "0.05em" },
  list:    { flex: 1, overflowY: "auto", padding: "0 8px 8px" },
  item:    { display: "flex", alignItems: "center", gap: "8px", padding: "5px 8px", borderRadius: "4px", marginBottom: "2px", cursor: "default" },
  dot:     { width: "6px", height: "6px", borderRadius: "50%", flexShrink: 0 },
  desc:    { fontSize: "12px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" as const, flex: 1 },
  idx:     { fontSize: "10px", color: "#6b7280", flexShrink: 0 },
  empty:   { color: "#6b7280", fontSize: "12px", textAlign: "center" as const, padding: "24px 12px" },
  footer:  { padding: "6px 12px", borderTop: "1px solid #1f2937", display: "flex", gap: "8px" },
  footerBtn: { flex: 1, padding: "4px 8px", fontSize: "12px", border: "1px solid #374151", borderRadius: "4px", background: "transparent", color: "#d1d5db", cursor: "pointer" },
};

export function HistoryPanel() {
  const [entries, setEntries] = useState(() => commandManager.history());

  const refresh = () => {
    setEntries(commandManager.history());
  };

  useEffect(() => {
    const unsubs = [
      designBus.on("CommandExecuted", refresh),
      designBus.on("CommandUndone",   refresh),
      designBus.on("CommandRedone",   refresh),
    ];
    return () => unsubs.forEach(fn => fn());
  }, []);

  return (
    <div style={s.root}>
      <div style={s.header}>History ({entries.length})</div>

      <div style={s.list} role="list" aria-label="Command history">
        {entries.length === 0 && <div style={s.empty}>No history yet</div>}
        {entries.map((entry, idx) => (
          <div
            key={idx}
            role="listitem"
            style={{
              ...s.item,
              background: entry.isCurrent ? "#312e81" : "transparent",
              opacity:    !entry.isCurrent && idx > entries.findIndex(e => e.isCurrent) ? 0.4 : 1,
            }}
            aria-current={entry.isCurrent}
          >
            <div style={{ ...s.dot, background: entry.isCurrent ? "#4f46e5" : "#6b7280" }} />
            <span style={{ ...s.desc, color: entry.isCurrent ? "#e0e7ff" : "#d1d5db" }}>
              {entry.description}
            </span>
            <span style={s.idx}>{idx + 1}</span>
          </div>
        ))}
      </div>

      <div style={s.footer}>
        <button
          style={{ ...s.footerBtn, opacity: commandManager.canUndo() ? 1 : 0.4 }}
          disabled={!commandManager.canUndo()}
          onClick={() => commandManager.undo(null as never)}
          aria-label="Undo"
        >↩ Undo</button>
        <button
          style={{ ...s.footerBtn, opacity: commandManager.canRedo() ? 1 : 0.4 }}
          disabled={!commandManager.canRedo()}
          onClick={() => commandManager.redo(null as never)}
          aria-label="Redo"
        >↪ Redo</button>
      </div>
    </div>
  );
}
