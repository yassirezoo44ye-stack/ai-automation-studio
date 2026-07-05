import type { Tool } from "../../types/canvas.types";
import styles from "./LeftToolbar.module.css";

interface ToolDef {
  id:      Tool;
  label:   string;
  icon:    string;
  shortcut: string;
}

const TOOLS: ToolDef[] = [
  { id: "select",    label: "Select",    icon: "↖",  shortcut: "V" },
  { id: "hand",      label: "Pan",       icon: "✋",  shortcut: "H" },
  { id: "text",      label: "Text",      icon: "T",   shortcut: "T" },
  { id: "rect",      label: "Rectangle", icon: "▭",   shortcut: "R" },
  { id: "circle",    label: "Ellipse",   icon: "○",   shortcut: "O" },
  { id: "triangle",  label: "Triangle",  icon: "△",   shortcut: "" },
  { id: "line",      label: "Line",      icon: "╱",   shortcut: "L" },
  { id: "pen",       label: "Pen",       icon: "✏",   shortcut: "P" },
  { id: "image",     label: "Image",     icon: "🖼",  shortcut: "" },
  { id: "eyedropper",label: "Color Pick",icon: "💧",  shortcut: "I" },
  { id: "crop",      label: "Crop",      icon: "⊹",   shortcut: "C" },
];

interface Props {
  activeTool: Tool;
  onToolChange: (tool: Tool) => void;
}

export function LeftToolbar({ activeTool, onToolChange }: Props) {
  return (
    <aside className={styles.toolbar} role="toolbar" aria-label="Drawing tools">
      {TOOLS.map(t => (
        <button
          key={t.id}
          className={`${styles.toolBtn} ${activeTool === t.id ? styles.active : ""}`}
          onClick={() => onToolChange(t.id)}
          title={`${t.label}${t.shortcut ? ` (${t.shortcut})` : ""}`}
          aria-pressed={activeTool === t.id}
        >
          <span className={styles.icon}>{t.icon}</span>
        </button>
      ))}
    </aside>
  );
}
