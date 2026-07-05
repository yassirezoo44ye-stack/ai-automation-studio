/**
 * BrandKitPanel — visual panel for managing brand colors, fonts, and logos.
 * Reads from state.brandKit and dispatches SET_BRAND_KIT on changes.
 */
import { useState } from "react";
import { useDesign } from "../../stores/designStore";
import type { BrandKit, BrandColor, BrandFont, BrandLogo } from "../../types/canvas.types";

const s: Record<string, React.CSSProperties> = {
  root:      { display: "flex", flexDirection: "column", height: "100%", overflowY: "auto", padding: "8px" },
  section:   { marginBottom: "16px" },
  secTitle:  { fontSize: "11px", fontWeight: 600, color: "#6b7280", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: "8px", display: "flex", alignItems: "center", justifyContent: "space-between" },
  addBtn:    { fontSize: "18px", lineHeight: 1, background: "none", border: "none", color: "#4f46e5", cursor: "pointer", padding: "0 4px" },
  colorGrid: { display: "flex", flexWrap: "wrap" as const, gap: "6px" },
  swatch:    { width: "32px", height: "32px", borderRadius: "6px", border: "1px solid #374151", cursor: "pointer", position: "relative" as const, flexShrink: 0 },
  swatchDel: { position: "absolute" as const, top: "-4px", right: "-4px", width: "14px", height: "14px", borderRadius: "50%", background: "#ef4444", color: "#fff", fontSize: "9px", display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer", border: "none", lineHeight: 1 },
  fontItem:  { padding: "6px 8px", borderRadius: "6px", background: "#1f2937", marginBottom: "4px", display: "flex", alignItems: "center", justifyContent: "space-between" },
  fontName:  { fontSize: "13px", color: "#f9fafb" },
  fontSub:   { fontSize: "10px", color: "#9ca3af" },
  logoItem:  { display: "flex", alignItems: "center", gap: "8px", padding: "4px 0", borderBottom: "1px solid #1f2937" },
  logoThumb: { width: "40px", height: "28px", background: "#1f2937", borderRadius: "4px", border: "1px solid #374151", objectFit: "contain" as const },
  delBtn:    { background: "none", border: "none", color: "#6b7280", cursor: "pointer", fontSize: "14px", lineHeight: 1 },
  emptyNote: { color: "#6b7280", fontSize: "12px", textAlign: "center" as const, padding: "8px 0", fontStyle: "italic" as const },
  addColorBtn:{ padding: "0", width: "32px", height: "32px", borderRadius: "6px", border: "2px dashed #374151", cursor: "pointer", background: "transparent", color: "#6b7280", fontSize: "18px", display: "flex", alignItems: "center", justifyContent: "center" },
};

const uid = () => Math.random().toString(36).slice(2, 9);

export function BrandKitPanel() {
  const { state, dispatch } = useDesign();
  const kit = state.brandKit as BrandKit;

  const update = (patch: Partial<BrandKit>) =>
    dispatch({ type: "SET_BRAND_KIT", brandKit: { ...kit, ...patch } });

  // Colors
  const [newColor, setNewColor] = useState("#4f46e5");
  const [addingColor, setAddingColor] = useState(false);

  const addColor = () => {
    update({ colors: [...kit.colors, { id: uid(), name: newColor, value: newColor }] });
    setAddingColor(false);
  };
  const removeColor = (id: string) =>
    update({ colors: kit.colors.filter((c: BrandColor) => c.id !== id) });

  // Fonts
  const addFont = () => {
    const family = window.prompt("Font family (e.g. 'Inter, sans-serif'):");
    if (!family) return;
    const name = family.split(",")[0].trim();
    update({ fonts: [...kit.fonts, { id: uid(), name, family, weights: [400, 700] }] });
  };
  const removeFont = (id: string) =>
    update({ fonts: kit.fonts.filter((f: BrandFont) => f.id !== id) });

  // Logos
  const addLogo = () => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = "image/*";
    input.onchange = () => {
      const file = input.files?.[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = () => {
        update({ logos: [...kit.logos, { id: uid(), name: file.name, src: reader.result as string }] });
      };
      reader.readAsDataURL(file);
    };
    input.click();
  };
  const removeLogo = (id: string) =>
    update({ logos: kit.logos.filter((l: BrandLogo) => l.id !== id) });

  return (
    <div style={s.root}>
      {/* Colors */}
      <div style={s.section}>
        <div style={s.secTitle}>
          <span>Brand Colors</span>
          <button style={s.addBtn} onClick={() => setAddingColor(v => !v)} aria-label="Add color">+</button>
        </div>
        <div style={s.colorGrid}>
          {kit.colors.map((c: BrandColor) => (
            <div key={c.id} style={{ ...s.swatch, background: c.value }} title={c.name}>
              <button
                style={s.swatchDel}
                onClick={() => removeColor(c.id)}
                aria-label={`Remove ${c.name}`}
              >✕</button>
            </div>
          ))}
          {addingColor ? (
            <div style={{ display: "flex", gap: "4px", alignItems: "center" }}>
              <input
                type="color"
                value={newColor}
                onChange={e => setNewColor(e.target.value)}
                style={{ width: "32px", height: "32px", padding: 0, border: "none", cursor: "pointer", borderRadius: "6px" }}
                aria-label="Pick color"
              />
              <button
                style={{ padding: "4px 8px", fontSize: "12px", background: "#4f46e5", color: "#fff", border: "none", borderRadius: "4px", cursor: "pointer" }}
                onClick={addColor}
              >Add</button>
            </div>
          ) : (
            <button style={s.addColorBtn} onClick={() => setAddingColor(true)} aria-label="Add brand color">+</button>
          )}
        </div>
        {!kit.colors.length && !addingColor && (
          <div style={s.emptyNote}>No brand colors yet</div>
        )}
      </div>

      {/* Fonts */}
      <div style={s.section}>
        <div style={s.secTitle}>
          <span>Brand Fonts</span>
          <button style={s.addBtn} onClick={addFont} aria-label="Add font">+</button>
        </div>
        {kit.fonts.length === 0 && <div style={s.emptyNote}>No brand fonts yet</div>}
        {kit.fonts.map((f: BrandFont) => (
          <div key={f.id} style={s.fontItem}>
            <div>
              <div style={{ ...s.fontName, fontFamily: f.family }}>{f.name}</div>
              <div style={s.fontSub}>{f.weights.join(", ")}</div>
            </div>
            <button style={s.delBtn} onClick={() => removeFont(f.id)} aria-label={`Remove ${f.name}`}>✕</button>
          </div>
        ))}
      </div>

      {/* Logos */}
      <div style={s.section}>
        <div style={s.secTitle}>
          <span>Logos</span>
          <button style={s.addBtn} onClick={addLogo} aria-label="Upload logo">+</button>
        </div>
        {kit.logos.length === 0 && <div style={s.emptyNote}>No logos yet</div>}
        {kit.logos.map((l: BrandLogo) => (
          <div key={l.id} style={s.logoItem}>
            <img src={l.src} style={s.logoThumb} alt={l.name} />
            <span style={{ flex: 1, fontSize: "12px", color: "#d1d5db", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{l.name}</span>
            <button style={s.delBtn} onClick={() => removeLogo(l.id)} aria-label={`Remove ${l.name}`}>✕</button>
          </div>
        ))}
      </div>
    </div>
  );
}
