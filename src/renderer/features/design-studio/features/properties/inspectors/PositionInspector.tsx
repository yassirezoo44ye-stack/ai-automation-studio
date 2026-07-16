/**
 * PositionInspector — shows/edits X, Y, W, H, Angle, Opacity for selected objects.
 * Reads selection from Fabric canvas; applies changes through Commands.
 */
import { useState, useEffect, useCallback } from "react";
import type { Canvas as FabricCanvas, FabricObject } from "fabric";
import { commandManager } from "../../../core/commands/CommandManager";
import { MoveObjectCommand } from "../../../core/commands/commands/MoveObject";
import { ResizeObjectCommand } from "../../../core/commands/commands/ResizeObject";
import { RotateObjectCommand } from "../../../core/commands/commands/RotateObject";
import { getMeta } from "../../../utils/fabricUtils";

interface Props {
  getCanvas: () => FabricCanvas | null;
  selectedIds: string[];
}

interface ObjectProps {
  x:       number;
  y:       number;
  width:   number;
  height:  number;
  angle:   number;
  opacity: number;
}

function getActiveProps(canvas: FabricCanvas): ObjectProps | null {
  const objs = canvas.getActiveObjects();
  if (!objs.length) return null;
  const obj = objs.length === 1 ? objs[0] : canvas.getActiveObject();
  if (!obj) return null;
  const br = obj.getBoundingRect();
  return {
    x:       Math.round(obj.left ?? 0),
    y:       Math.round(obj.top  ?? 0),
    width:   Math.round(br.width),
    height:  Math.round(br.height),
    angle:   Math.round(obj.angle ?? 0),
    opacity: Math.round((obj.opacity ?? 1) * 100),
  };
}

export function PositionInspector({ getCanvas, selectedIds }: Props) {
  const [props, setProps] = useState<ObjectProps | null>(null);

  useEffect(() => {
    const fc = getCanvas();
    if (!fc || !selectedIds.length) { setProps(null); return; }
    setProps(getActiveProps(fc));
  }, [getCanvas, selectedIds]);

  const applyChange = useCallback(async (field: keyof ObjectProps, value: number) => {
    const fc = getCanvas();
    if (!fc || !selectedIds.length) return;

    if (field === "x" || field === "y") {
      const after = new Map(selectedIds.map(id => {
        const obj = fc.getObjects().find(o => getMeta(o)?.id === id);
        return [id, { left: field === "x" ? value : (obj?.left ?? 0), top: field === "y" ? value : (obj?.top ?? 0) }];
      }));
      await commandManager.execute(fc, new MoveObjectCommand(selectedIds, after));
    }

    if (field === "angle") {
      const after = new Map(selectedIds.map(id => [id, value]));
      await commandManager.execute(fc, new RotateObjectCommand(selectedIds, after));
    }

    if (field === "opacity") {
      const objs = fc.getActiveObjects();
      objs.forEach(o => o.set({ opacity: value / 100 }));
      fc.renderAll();
    }

    setProps(getActiveProps(fc));
  }, [getCanvas, selectedIds]);

  if (!props) {
    return (
      <div style={{ padding: "12px", color: "#BDBDBD", fontSize: "12px", textAlign: "center" }}>
        No object selected
      </div>
    );
  }

  const row: React.CSSProperties = { display: "flex", gap: "8px", marginBottom: "8px" };
  const label: React.CSSProperties = { fontSize: "11px", color: "#BDBDBD", marginBottom: "2px" };
  const input: React.CSSProperties = {
    width: "100%", padding: "4px 6px", fontSize: "12px", border: "1px solid #2A2A2A",
    borderRadius: "4px", background: "#1A1A1A", color: "#F2F2F2", outline: "none",
  };
  const group = (lbl: string, field: keyof ObjectProps) => (
    <div style={{ flex: 1 }}>
      <div style={label}>{lbl}</div>
      <input
        style={input}
        type="number"
        value={props[field]}
        onChange={e => {
          const v = parseFloat(e.target.value) || 0;
          setProps(p => p ? { ...p, [field]: v } : null);
        }}
        onBlur={e => void applyChange(field, parseFloat(e.target.value) || 0)}
      />
    </div>
  );

  return (
    <div style={{ padding: "12px" }}>
      <div style={{ fontSize: "11px", fontWeight: 600, color: "#8F8F8F", marginBottom: "10px", textTransform: "uppercase", letterSpacing: "0.05em" }}>Position</div>
      <div style={row}>{group("X", "x")}{group("Y", "y")}</div>
      <div style={row}>{group("W", "width")}{group("H", "height")}</div>
      <div style={row}>{group("°", "angle")}{group("%", "opacity")}</div>
    </div>
  );
}
