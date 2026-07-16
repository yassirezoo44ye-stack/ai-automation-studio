/**
 * TypographyInspector — font family, size, weight, style, alignment, spacing.
 * Only shown when a text object is selected.
 */
import { useState, useEffect, useCallback } from "react";
import type { Canvas as FabricCanvas, IText } from "fabric";
import { getMeta } from "../../../utils/fabricUtils";
import { commandManager } from "../../../core/commands/CommandManager";
import type { ChangeFontCommand as _CFC } from "../../../core/commands/commands/ChangeFont";
import { ChangeFontCommand } from "../../../core/commands/commands/ChangeFont";

interface Props {
  getCanvas:   () => FabricCanvas | null;
  selectedIds: string[];
}

const SYSTEM_FONTS = [
  "Inter, sans-serif",
  "Poppins, sans-serif",
  "Roboto, sans-serif",
  "Open Sans, sans-serif",
  "Lato, sans-serif",
  "Montserrat, sans-serif",
  "Playfair Display, serif",
  "Merriweather, serif",
  "Georgia, serif",
  "JetBrains Mono, monospace",
];

const WEIGHTS = [
  { label: "Thin",     value: 100 },
  { label: "Light",    value: 300 },
  { label: "Regular",  value: 400 },
  { label: "Medium",   value: 500 },
  { label: "SemiBold", value: 600 },
  { label: "Bold",     value: 700 },
  { label: "ExtraBold",value: 800 },
  { label: "Black",    value: 900 },
];

export function TypographyInspector({ getCanvas, selectedIds }: Props) {
  const [textObjs, setTextObjs] = useState<IText[]>([]);
  const [fontFamily,   setFontFamily]   = useState("Inter, sans-serif");
  const [fontSize,     setFontSize]     = useState(16);
  const [fontWeight,   setFontWeight]   = useState(400);
  const [fontStyle,    setFontStyle]    = useState<"normal" | "italic">("normal");
  const [textAlign,    setTextAlign]    = useState<"left" | "center" | "right" | "justify">("left");
  const [lineHeight,   setLineHeight]   = useState(1.4);
  const [underline,    setUnderline]    = useState(false);

  useEffect(() => {
    const fc = getCanvas();
    if (!fc || !selectedIds.length) { setTextObjs([]); return; }
    const texts = fc.getActiveObjects().filter(o => {
      const t = o.type ?? "";
      return t === "i-text" || t === "text" || t === "textbox";
    }) as IText[];
    setTextObjs(texts);
    if (texts[0]) {
      setFontFamily(texts[0].fontFamily ?? "Inter, sans-serif");
      setFontSize(texts[0].fontSize ?? 16);
      setFontWeight(typeof texts[0].fontWeight === "number" ? texts[0].fontWeight : 400);
      setFontStyle(texts[0].fontStyle === "italic" ? "italic" : "normal");
      setTextAlign((texts[0].textAlign as "left" | "center" | "right" | "justify") ?? "left");
      setLineHeight(texts[0].lineHeight ?? 1.4);
      setUnderline(texts[0].underline ?? false);
    }
  }, [getCanvas, selectedIds]);

  const applyFont = useCallback(async (patch: ConstructorParameters<typeof ChangeFontCommand>[1]) => {
    const fc = getCanvas();
    if (!fc || !textObjs.length) return;
    const ids = textObjs.map(o => getMeta(o)?.id ?? "").filter(Boolean);
    await commandManager.execute(fc, new ChangeFontCommand(ids, patch));
  }, [getCanvas, textObjs]);

  if (!textObjs.length) return null;

  const sel: React.CSSProperties = { width: "100%", padding: "4px 6px", fontSize: "12px", border: "1px solid #2A2A2A", borderRadius: "4px", background: "#1A1A1A", color: "#F2F2F2" };
  const inp: React.CSSProperties = { ...sel };
  const btn = (active: boolean): React.CSSProperties => ({
    padding: "4px 8px", fontSize: "12px", border: `1px solid ${active ? "#D4AF37" : "#2A2A2A"}`,
    borderRadius: "4px", background: active ? "#D4AF37" : "#1A1A1A", color: "#F2F2F2", cursor: "pointer",
  });

  return (
    <div style={{ padding: "12px", borderTop: "1px solid #1A1A1A" }}>
      <div style={{ fontSize: "11px", fontWeight: 600, color: "#8F8F8F", marginBottom: "10px", textTransform: "uppercase", letterSpacing: "0.05em" }}>Typography</div>

      <div style={{ marginBottom: "8px" }}>
        <div style={{ fontSize: "11px", color: "#BDBDBD", marginBottom: "2px" }}>Font Family</div>
        <select style={sel} value={fontFamily} onChange={e => { setFontFamily(e.target.value); void applyFont({ fontFamily: e.target.value }); }}>
          {SYSTEM_FONTS.map(f => <option key={f} value={f}>{f.split(",")[0]}</option>)}
        </select>
      </div>

      <div style={{ display: "flex", gap: "8px", marginBottom: "8px" }}>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: "11px", color: "#BDBDBD", marginBottom: "2px" }}>Size</div>
          <input style={inp} type="number" min={6} max={400} value={fontSize}
            onChange={e => setFontSize(+e.target.value)}
            onBlur={e => void applyFont({ fontSize: +e.target.value })} />
        </div>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: "11px", color: "#BDBDBD", marginBottom: "2px" }}>Weight</div>
          <select style={sel} value={fontWeight} onChange={e => { setFontWeight(+e.target.value); void applyFont({ fontWeight: +e.target.value }); }}>
            {WEIGHTS.map(w => <option key={w.value} value={w.value}>{w.label}</option>)}
          </select>
        </div>
      </div>

      <div style={{ display: "flex", gap: "6px", marginBottom: "8px" }}>
        <button style={btn(fontStyle === "italic")} onClick={() => { const v: "italic" | "normal" = fontStyle === "italic" ? "normal" : "italic"; setFontStyle(v); void applyFont({ fontStyle: v }); }}>I</button>
        <button style={btn(underline)} onClick={() => { const v = !underline; setUnderline(v); void applyFont({ underline: v }); }}>U</button>
        {(["left","center","right","justify"] as const).map(a => (
          <button key={a} style={btn(textAlign === a)} onClick={() => { setTextAlign(a); void applyFont({ textAlign: a }); }}>{a[0].toUpperCase()}</button>
        ))}
      </div>

      <div style={{ display: "flex", gap: "8px" }}>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: "11px", color: "#BDBDBD", marginBottom: "2px" }}>Line H</div>
          <input style={inp} type="number" step="0.1" min={0.5} max={4} value={lineHeight}
            onChange={e => setLineHeight(+e.target.value)}
            onBlur={e => void applyFont({ lineHeight: +e.target.value })} />
        </div>
      </div>
    </div>
  );
}
