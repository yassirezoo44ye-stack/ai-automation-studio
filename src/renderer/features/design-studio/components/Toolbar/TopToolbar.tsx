/**
 * TopToolbar — header bar for Flow App Builder / Design Studio.
 *
 * New in this version:
 *  - Mode tabs: Design | Preview | Code | Deploy
 *  - "✦ Build with AI" button (opens AICommandBar)
 *
 * Existing functionality (undo/redo, zoom, import, save, export) is
 * preserved exactly — no existing props or behaviour are changed.
 */
import { useTranslation } from "react-i18next";
import styles from "./TopToolbar.module.css";

/** Studio-level mode (what the user is currently doing) */
export type StudioMode = "design" | "preview" | "code" | "deploy";

const MODE_TABS: { id: StudioMode; label: string }[] = [
  { id: "design",  label: "Design"  },
  { id: "preview", label: "Preview" },
  { id: "code",    label: "Code"    },
  { id: "deploy",  label: "Deploy"  },
];

interface Props {
  // ── existing props (unchanged) ──────────────────────────────────────────
  projectName:   string;
  unsaved:       boolean;
  historyIndex:  number;
  historyLength: number;
  zoom:          number;
  canUndo:       boolean;
  canRedo:       boolean;
  onUndo:        () => void;
  onRedo:        () => void;
  onZoomIn:      () => void;
  onZoomOut:     () => void;
  onZoomReset:   () => void;
  onExport:      () => void;
  onSave:        () => void;
  onImport:      (file: File) => void;
  // ── new props ────────────────────────────────────────────────────────────
  mode:          StudioMode;
  onModeChange:  (m: StudioMode) => void;
  onBuildWithAI: () => void;
}

export function TopToolbar({
  projectName, unsaved, zoom,
  canUndo, canRedo, onUndo, onRedo,
  onZoomIn, onZoomOut, onZoomReset,
  onExport, onSave, onImport,
  mode, onModeChange, onBuildWithAI,
}: Props) {
  const { t } = useTranslation("designStudio");

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) onImport(file);
    e.target.value = "";
  };

  return (
    <header className={styles.toolbar}>
      {/* ── Left: project name + undo/redo/zoom ───────────────────────────── */}
      <div className={styles.left}>
        <span className={styles.projectName}>
          {projectName}
          {unsaved && <span className={styles.dot} title={t("topToolbar.unsavedChanges")} />}
        </span>

        <div className={styles.divider} />

        <button
          className={styles.btn}
          onClick={onUndo}
          disabled={!canUndo}
          title={t("topToolbar.undoTitle")}
          aria-label={t("topToolbar.undoAriaLabel")}
        >
          ↩
        </button>
        <button
          className={styles.btn}
          onClick={onRedo}
          disabled={!canRedo}
          title={t("topToolbar.redoTitle")}
          aria-label={t("topToolbar.redoAriaLabel")}
        >
          ↪
        </button>

        <div className={styles.divider} />

        <button className={styles.btn} onClick={onZoomOut} title={t("topToolbar.zoomOutTitle")}>−</button>
        <button className={styles.zoomLabel} onClick={onZoomReset} title={t("topToolbar.resetZoomTitle")}>
          {Math.round(zoom * 100)}%
        </button>
        <button className={styles.btn} onClick={onZoomIn} title={t("topToolbar.zoomInTitle")}>+</button>
      </div>

      {/* ── Center: mode tabs ─────────────────────────────────────────────── */}
      <div className={styles.center} role="tablist" aria-label="Studio mode">
        {MODE_TABS.map(tab => (
          <button
            key={tab.id}
            role="tab"
            aria-selected={mode === tab.id}
            className={`${styles.modeTab} ${mode === tab.id ? styles.modeTabActive : ""}`}
            onClick={() => onModeChange(tab.id)}
            title={`Switch to ${tab.label} mode`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* ── Right: AI build + import/save/export ──────────────────────────── */}
      <div className={styles.right}>
        <button
          className={styles.btnAI}
          onClick={onBuildWithAI}
          title="Generate an app with AI"
          aria-label="Build with AI"
        >
          ✦ Build with AI
        </button>

        <div className={styles.divider} />

        <label className={styles.btnSecondary} title={t("topToolbar.importTitle")}>
          {t("topToolbar.import")}
          <input
            type="file"
            accept="application/json,.json"
            style={{ display: "none" }}
            onChange={handleFileChange}
          />
        </label>
        <button className={styles.btnSecondary} onClick={onSave} title={t("topToolbar.save")}>
          {t("topToolbar.save")}
        </button>
        <button className={styles.btnPrimary} onClick={onExport} title={t("topToolbar.export")}>
          {t("topToolbar.export")}
        </button>
      </div>
    </header>
  );
}
