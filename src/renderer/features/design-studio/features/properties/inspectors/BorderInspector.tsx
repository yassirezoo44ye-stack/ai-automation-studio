/**
 * BorderInspector — border radius for rect/shape objects.
 */
import { useState, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import type { Canvas as FabricCanvas, Rect } from "fabric";

interface Props {
  getCanvas:   () => FabricCanvas | null;
  selectedIds: string[];
}

const secWrap: React.CSSProperties = { padding: "12px", borderTop: "1px solid var(--b1)" };
const secHeader: React.CSSProperties = {
  fontSize: "11px", fontWeight: 600, color: "var(--t3)",
  marginBottom: "10px", textTransform: "uppercase", letterSpacing: "0.05em",
};

export function BorderInspector({ getCanvas, selectedIds }: Props) {
  const { t } = useTranslation("designStudio");
  const [radius, setRadius] = useState(0);
  const [hasRadius, setHasRadius] = useState(false);

  useEffect(() => {
    queueMicrotask(() => {
      const fc = getCanvas();
      if (!fc || !selectedIds.length) return;
      const obj = fc.getActiveObjects()[0];
      const r = (obj as Rect)?.rx ?? 0;
      setHasRadius("rx" in (obj ?? {}));
      setRadius(r);
    });
  }, [getCanvas, selectedIds]);

  const apply = useCallback((r: number) => {
    const fc = getCanvas();
    if (!fc) return;
    fc.getActiveObjects().forEach(o => {
      if ("rx" in o) o.set({ rx: r, ry: r } as Partial<Rect>);
    });
    fc.renderAll();
  }, [getCanvas]);

  if (!selectedIds.length || !hasRadius) return null;

  return (
    <div style={secWrap}>
      <div style={secHeader}>{t("inspectors.border.header")}</div>
      <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
        <span style={{ fontSize: "11px", color: "var(--t3)", width: "48px", flexShrink: 0 }}>
          {t("inspectors.border.radius")}
        </span>
        <input
          style={{ flex: 1, accentColor: "var(--accent)" }}
          type="range" min={0} max={200} value={radius}
          onChange={e => { setRadius(+e.target.value); apply(+e.target.value); }}
        />
        <span style={{ fontSize: "12px", color: "var(--t1)", width: "36px", textAlign: "end", fontVariantNumeric: "tabular-nums" }}>
          {radius}px
        </span>
      </div>
    </div>
  );
}
