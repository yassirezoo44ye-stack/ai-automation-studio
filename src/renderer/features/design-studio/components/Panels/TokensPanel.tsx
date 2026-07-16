/**
 * TokensPanel — browse, create, and delete design tokens.
 * Integrates with tokenRegistry singleton for Color, Typography, Spacing, etc.
 */
import { useState, useEffect, useCallback } from "react";
import { tokenRegistry } from "../../core/tokens/TokenRegistry";
import type { DesignToken, TokenCategory } from "../../core/tokens/DesignToken";

const CATEGORIES: { id: TokenCategory; label: string; emoji: string }[] = [
  { id: "color",      label: "Colors",     emoji: "🎨" },
  { id: "gradient",   label: "Gradients",  emoji: "🌈" },
  { id: "typography", label: "Typography", emoji: "T" },
  { id: "spacing",    label: "Spacing",    emoji: "↔" },
  { id: "radius",     label: "Radius",     emoji: "⌒" },
  { id: "shadow",     label: "Shadow",     emoji: "⊕" },
  { id: "border",     label: "Border",     emoji: "▢" },
  { id: "effect",     label: "Effects",    emoji: "✨" },
];

const s: Record<string, React.CSSProperties> = {
  root:      { display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" },
  cats:      { display: "flex", flexWrap: "wrap" as const, gap: "4px", padding: "8px 10px 6px" },
  catBtn:    { padding: "3px 8px", fontSize: "11px", borderRadius: "10px", border: "1px solid #2A2A2A", background: "transparent", cursor: "pointer" },
  list:      { flex: 1, overflowY: "auto", padding: "0 10px 8px" },
  row:       { display: "flex", alignItems: "center", gap: "8px", padding: "5px 6px", borderRadius: "4px", marginBottom: "2px" },
  preview:   { width: "20px", height: "20px", borderRadius: "3px", border: "1px solid #2A2A2A", flexShrink: 0 },
  tokenName: { flex: 1, fontSize: "12px", color: "#D6D6D6", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" as const },
  tokenVal:  { fontSize: "11px", color: "#8F8F8F", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" as const, maxWidth: "80px" },
  delBtn:    { background: "none", border: "none", color: "#8F8F8F", cursor: "pointer", fontSize: "13px", lineHeight: 1 },
  addBar:    { padding: "6px 10px", borderTop: "1px solid #1A1A1A", display: "flex", gap: "6px" },
  addIn:     { flex: 1, padding: "4px 6px", fontSize: "12px", border: "1px solid #2A2A2A", borderRadius: "4px", background: "#1A1A1A", color: "#F2F2F2", outline: "none" },
  addBtn:    { padding: "4px 10px", fontSize: "12px", background: "#D4AF37", color: "#0a0a0a", border: "none", borderRadius: "4px", cursor: "pointer" },
  empty:     { color: "#8F8F8F", fontSize: "12px", textAlign: "center" as const, padding: "16px 0" },
};

function tokenPreview(token: DesignToken): string | undefined {
  const v = token.value;
  if (v.startsWith("#") || v.startsWith("rgb") || v.startsWith("hsl")) return v;
  return undefined;
}

function tokenValueLabel(token: DesignToken): string {
  return token.value.length > 24 ? token.value.slice(0, 21) + "…" : token.value;
}

export function TokensPanel() {
  const [category, setCategory] = useState<TokenCategory>("color");
  const [tokens, setTokens]     = useState<DesignToken[]>([]);
  const [newName, setNewName]   = useState("");
  const [newValue, setNewValue] = useState("#D4AF37");

  const refresh = useCallback(() => {
    setTokens(tokenRegistry.byCategory(category));
  }, [category]);

  useEffect(() => { refresh(); }, [refresh]);

  const addToken = () => {
    if (!newName.trim()) return;
    const id = `${category}_${Date.now()}`;
    tokenRegistry.add({
      id,
      name:      newName.trim(),
      category,
      value:     newValue,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    } as DesignToken);
    setNewName("");
    refresh();
  };

  const deleteToken = (id: string) => {
    tokenRegistry.delete(id);
    refresh();
  };

  return (
    <div style={s.root}>
      {/* Category tabs */}
      <div style={s.cats} role="tablist" aria-label="Token categories">
        {CATEGORIES.map(cat => (
          <button
            key={cat.id}
            role="tab"
            aria-selected={category === cat.id}
            style={{
              ...s.catBtn,
              background:  category === cat.id ? "#D4AF37" : "transparent",
              color:       category === cat.id ? "#fff"    : "#BDBDBD",
              borderColor: category === cat.id ? "#D4AF37" : "#2A2A2A",
            }}
            onClick={() => setCategory(cat.id)}
          >{cat.emoji} {cat.label}</button>
        ))}
      </div>

      {/* Token list */}
      <div style={s.list} role="list">
        {tokens.length === 0 && <div style={s.empty}>No {category} tokens</div>}
        {tokens.map(token => {
          const preview = tokenPreview(token);
          return (
            <div key={token.name} style={s.row} role="listitem">
              {preview
                ? <div style={{ ...s.preview, background: preview }} />
                : <div style={{ ...s.preview, background: "#1A1A1A", display: "flex", alignItems: "center", justifyContent: "center", fontSize: "9px", color: "#8F8F8F" }}>{category[0].toUpperCase()}</div>
              }
              <span style={s.tokenName}>{token.name}</span>
              <span style={s.tokenVal}>{tokenValueLabel(token)}</span>
              <button style={s.delBtn} onClick={() => deleteToken(token.id)} aria-label={`Delete ${token.name}`}>✕</button>
            </div>
          );
        })}
      </div>

      {/* Add new token */}
      <div style={s.addBar}>
        <input
          style={{ ...s.addIn, flex: "0 0 90px" }}
          placeholder="Name"
          value={newName}
          onChange={e => setNewName(e.target.value)}
          onKeyDown={e => e.key === "Enter" && addToken()}
          aria-label="New token name"
        />
        {category === "color" || category === "gradient" ? (
          <input
            type="color"
            value={newValue}
            onChange={e => setNewValue(e.target.value)}
            style={{ width: "28px", height: "28px", padding: 0, border: "none", cursor: "pointer", borderRadius: "4px", flexShrink: 0 }}
            aria-label="Token color value"
          />
        ) : (
          <input
            style={s.addIn}
            placeholder="Value"
            value={newValue}
            onChange={e => setNewValue(e.target.value)}
            onKeyDown={e => e.key === "Enter" && addToken()}
            aria-label="Token value"
          />
        )}
        <button style={s.addBtn} onClick={addToken} aria-label="Add token">Add</button>
      </div>
    </div>
  );
}
