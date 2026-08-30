/**
 * LeftToolbar — vertical tool strip for the Design Studio canvas.
 *
 * Icons: inline SVG (16×16, currentColor) matching standard design-tool
 * conventions (Figma / Canva style). No emoji, no unicode symbols.
 */
import { useTranslation } from "react-i18next";
import type { Tool } from "../../types/canvas.types";
import styles from "./LeftToolbar.module.css";

// ── SVG icon primitives ────────────────────────────────────────────────────

function Svg({ children, title }: { children: React.ReactNode; title?: string }) {
  return (
    <svg
      width="16" height="16" viewBox="0 0 16 16"
      fill="none" xmlns="http://www.w3.org/2000/svg"
      aria-hidden={title ? undefined : "true"}
      role={title ? "img" : undefined}
    >
      {title && <title>{title}</title>}
      {children}
    </svg>
  );
}

const SelectIcon = () => (
  <Svg>
    <path d="M3 2L3 12L6.5 9L8.5 13.5L10 12.8L8 8.3L12 8.3L3 2Z" fill="currentColor"/>
  </Svg>
);

const HandIcon = () => (
  <Svg>
    <path d="M8 2.5C8 1.9 8.4 1.5 9 1.5C9.6 1.5 10 1.9 10 2.5V7H10.5C10.5 7 11 6.5 11.5 6.5C12 6.5 12.5 6.9 12.5 7.5V8.5C12.5 8.5 13 8 13.5 8C14 8 14.5 8.4 14.5 9V11C14.5 13.2 12.7 15 10.5 15H6.5C5.3 15 4.2 14.4 3.5 13.5L1.5 11L2.3 10.3C2.7 9.9 3.3 9.8 3.8 10.1L5 10.8V2.5C5 1.9 5.4 1.5 6 1.5C6.6 1.5 7 1.9 7 2.5V7H8V2.5Z" stroke="currentColor" strokeWidth="1" fill="none"/>
  </Svg>
);

const TextIcon = () => (
  <Svg>
    <path d="M2 3H14M8 3V13M5 13H11" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
  </Svg>
);

const RectIcon = () => (
  <Svg>
    <rect x="2" y="2" width="12" height="12" rx="1" stroke="currentColor" strokeWidth="1.5" fill="none"/>
  </Svg>
);

const CircleIcon = () => (
  <Svg>
    <circle cx="8" cy="8" r="6" stroke="currentColor" strokeWidth="1.5" fill="none"/>
  </Svg>
);

const TriangleIcon = () => (
  <Svg>
    <path d="M8 2.5L14 13.5H2L8 2.5Z" stroke="currentColor" strokeWidth="1.5" fill="none" strokeLinejoin="round"/>
  </Svg>
);

const LineIcon = () => (
  <Svg>
    <line x1="2.5" y1="13.5" x2="13.5" y2="2.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
  </Svg>
);

const PenIcon = () => (
  <Svg>
    <path d="M8 2L10.5 4.5L5 10L3 13L6 11L11.5 5.5L14 8L8 2Z" stroke="currentColor" strokeWidth="1.2" fill="none" strokeLinejoin="round"/>
    <circle cx="8" cy="8" r="1" fill="currentColor"/>
  </Svg>
);

const ImageIcon = () => (
  <Svg>
    <rect x="2" y="3" width="12" height="10" rx="1" stroke="currentColor" strokeWidth="1.5" fill="none"/>
    <circle cx="5.5" cy="6.5" r="1.5" fill="currentColor" opacity="0.6"/>
    <path d="M2 11L5 8L7.5 10.5L10 8.5L14 12" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round" fill="none"/>
  </Svg>
);

const EyedropperIcon = () => (
  <Svg>
    <path d="M10 2L12 4L5.5 10.5L3.5 12.5L2 14L2 14L3.5 12.5L5.5 10.5L10 2Z" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round" fill="none"/>
    <path d="M10 2L12 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
    <circle cx="3" cy="13" r="1.2" fill="currentColor" opacity="0.7"/>
  </Svg>
);

const CropIcon = () => (
  <Svg>
    <path d="M4 2V12H14" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
    <path d="M2 4H12V14" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
  </Svg>
);

// ── Tool definitions ───────────────────────────────────────────────────────

interface ToolDef {
  id:       Tool;
  jsonKey:  string;
  icon:     React.ReactNode;
  shortcut: string;
}

const TOOLS: ToolDef[] = [
  { id: "select",     jsonKey: "select",    icon: <SelectIcon />,     shortcut: "V" },
  { id: "hand",       jsonKey: "pan",       icon: <HandIcon />,       shortcut: "H" },
  { id: "text",       jsonKey: "text",      icon: <TextIcon />,       shortcut: "T" },
  { id: "rect",       jsonKey: "rectangle", icon: <RectIcon />,       shortcut: "R" },
  { id: "circle",     jsonKey: "ellipse",   icon: <CircleIcon />,     shortcut: "O" },
  { id: "triangle",   jsonKey: "triangle",  icon: <TriangleIcon />,   shortcut: ""  },
  { id: "line",       jsonKey: "line",      icon: <LineIcon />,       shortcut: "L" },
  { id: "pen",        jsonKey: "pen",       icon: <PenIcon />,        shortcut: "P" },
  { id: "image",      jsonKey: "image",     icon: <ImageIcon />,      shortcut: ""  },
  { id: "eyedropper", jsonKey: "colorPick", icon: <EyedropperIcon />, shortcut: "I" },
  { id: "crop",       jsonKey: "crop",      icon: <CropIcon />,       shortcut: "C" },
];

// ── Divider positions (after these tool indices) ───────────────────────────
const DIVIDERS_AFTER = new Set([1, 2, 7]);

// ── Component ─────────────────────────────────────────────────────────────

interface Props {
  activeTool: Tool;
  onToolChange: (tool: Tool) => void;
}

export function LeftToolbar({ activeTool, onToolChange }: Props) {
  const { t } = useTranslation("designStudio");
  return (
    // eslint-disable-next-line jsx-a11y/no-noninteractive-element-to-interactive-role
    <aside className={styles.toolbar} role="toolbar" aria-label={t("leftToolbar.ariaLabel")}>
      {TOOLS.map((tool, idx) => {
        const label = t(`leftToolbar.tools.${tool.jsonKey}`);
        const title = tool.shortcut
          ? t("leftToolbar.toolTitleWithShortcut", { label, shortcut: tool.shortcut })
          : label;
        return (
          <div key={tool.id}>
            <button
              className={`${styles.toolBtn} ${activeTool === tool.id ? styles.active : ""}`}
              onClick={() => onToolChange(tool.id)}
              title={title}
              aria-pressed={activeTool === tool.id}
              aria-label={label}
            >
              <span className={styles.icon}>{tool.icon}</span>
            </button>
            {DIVIDERS_AFTER.has(idx) && <div className={styles.divider} />}
          </div>
        );
      })}
    </aside>
  );
}
