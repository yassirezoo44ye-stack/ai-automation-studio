import { useTranslation } from "react-i18next";
import styles from "./TopToolbar.module.css";

interface Props {
  projectName:  string;
  unsaved:      boolean;
  historyIndex: number;
  historyLength:number;
  zoom:         number;
  canUndo:      boolean;
  canRedo:      boolean;
  onUndo:       () => void;
  onRedo:       () => void;
  onZoomIn:     () => void;
  onZoomOut:    () => void;
  onZoomReset:  () => void;
  onExport:     () => void;
  onSave:       () => void;
  onImport:     (file: File) => void;
}

export function TopToolbar({
  projectName, unsaved, zoom,
  canUndo, canRedo, onUndo, onRedo,
  onZoomIn, onZoomOut, onZoomReset,
  onExport, onSave, onImport,
}: Props) {
  const { t } = useTranslation("designStudio");
  return (
    <header className={styles.toolbar}>
      <div className={styles.left}>
        <span className={styles.projectName}>
          {projectName}
          {unsaved && <span className={styles.dot} title={t("topToolbar.unsavedChanges")} />}
        </span>
      </div>

      <div className={styles.center}>
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

      <div className={styles.right}>
        <label className={styles.btnSecondary} title={t("topToolbar.importTitle")}>
          {t("topToolbar.import")}
          <input
            type="file"
            accept="application/json,.json"
            style={{ display: "none" }}
            onChange={e => {
              const file = e.target.files?.[0];
              if (file) onImport(file);
              e.target.value = "";
            }}
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
