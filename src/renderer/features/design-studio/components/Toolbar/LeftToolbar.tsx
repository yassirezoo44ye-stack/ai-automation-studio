import { useTranslation } from "react-i18next";
import type { Tool } from "../../types/canvas.types";
import styles from "./LeftToolbar.module.css";

interface ToolDef {
  id:      Tool;
  jsonKey: string;
  icon:    string;
  shortcut: string;
}

const TOOLS: ToolDef[] = [
  { id: "select",    jsonKey: "select",    icon: "↖",  shortcut: "V" },
  { id: "hand",      jsonKey: "pan",       icon: "✋",  shortcut: "H" },
  { id: "text",      jsonKey: "text",      icon: "T",   shortcut: "T" },
  { id: "rect",      jsonKey: "rectangle", icon: "▭",   shortcut: "R" },
  { id: "circle",    jsonKey: "ellipse",   icon: "○",   shortcut: "O" },
  { id: "triangle",  jsonKey: "triangle",  icon: "△",   shortcut: "" },
  { id: "line",      jsonKey: "line",      icon: "╱",   shortcut: "L" },
  { id: "pen",       jsonKey: "pen",       icon: "✏",   shortcut: "P" },
  { id: "image",     jsonKey: "image",     icon: "🖼",  shortcut: "" },
  { id: "eyedropper",jsonKey: "colorPick", icon: "💧",  shortcut: "I" },
  { id: "crop",      jsonKey: "crop",      icon: "⊹",   shortcut: "C" },
];

interface Props {
  activeTool: Tool;
  onToolChange: (tool: Tool) => void;
}

export function LeftToolbar({ activeTool, onToolChange }: Props) {
  const { t } = useTranslation("designStudio");
  return (
    // <aside> carrying role="toolbar" is the standard WAI-ARIA toolbar
    // pattern (a landmark element grouping a row of buttons) — jsx-a11y's
    // element/role map is conservative here, not flagging a real issue.
    // eslint-disable-next-line jsx-a11y/no-noninteractive-element-to-interactive-role
    <aside className={styles.toolbar} role="toolbar" aria-label={t("leftToolbar.ariaLabel")}>
      {TOOLS.map(tool => {
        const label = t(`leftToolbar.tools.${tool.jsonKey}`);
        return (
          <button
            key={tool.id}
            className={`${styles.toolBtn} ${activeTool === tool.id ? styles.active : ""}`}
            onClick={() => onToolChange(tool.id)}
            title={tool.shortcut ? t("leftToolbar.toolTitleWithShortcut", { label, shortcut: tool.shortcut }) : label}
            aria-pressed={activeTool === tool.id}
          >
            <span className={styles.icon}>{tool.icon}</span>
          </button>
        );
      })}
    </aside>
  );
}
