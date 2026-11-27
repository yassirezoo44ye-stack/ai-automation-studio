import { useState } from "react";
import type { Canvas as FabricCanvas } from "fabric";
import { useTranslation } from "react-i18next";
import { PositionInspector }   from "../../features/properties/inspectors/PositionInspector";
import { AppearanceInspector } from "../../features/properties/inspectors/AppearanceInspector";
import { TypographyInspector } from "../../features/properties/inspectors/TypographyInspector";
import { ShadowInspector }     from "../../features/properties/inspectors/ShadowInspector";
import { BorderInspector }     from "../../features/properties/inspectors/BorderInspector";
import { EffectsInspector }    from "../../features/properties/inspectors/EffectsInspector";
import styles from "./PropertiesPanel.module.css";

type PanelTab = "style" | "action" | "data" | "ai";

interface Props {
  getCanvas:   () => FabricCanvas | null;
  selectedIds: string[];
  onBringForward: () => void;
  onSendBackward: () => void;
}

const EVENTS = ["onClick", "onHover", "onFocus", "onBlur"];

export function PropertiesPanel({ getCanvas, selectedIds, onBringForward, onSendBackward }: Props) {
  const { t } = useTranslation("designStudio");
  const [tab, setTab] = useState<PanelTab>("style");
  const [aiPrompt, setAiPrompt] = useState("");

  if (!selectedIds.length) {
    return (
      <div style={{
        padding: "16px 12px",
        color: "#6b7280",
        fontSize: "12px",
        textAlign: "center",
        lineHeight: 1.5,
      }}>
        {t("propertiesPanel.emptyState")}
      </div>
    );
  }

  const layerBtn: React.CSSProperties = {
    flex: 1, padding: "6px 8px", fontSize: "12px", border: "1px solid #374151",
    borderRadius: "4px", background: "#1f2937", color: "#f9fafb", cursor: "pointer",
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", maxHeight: "100%", overflow: "hidden" }}>
      {/* Tab bar */}
      <div className={styles.tabs} role="tablist">
        {(["style", "action", "data", "ai"] as PanelTab[]).map(id => (
          <button
            key={id}
            role="tab"
            aria-selected={tab === id}
            className={`${styles.tab} ${tab === id ? styles.tabActive : ""}`}
            onClick={() => setTab(id)}
          >
            {t(`propertiesPanel.tabs.${id}`, id.charAt(0).toUpperCase() + id.slice(1))}
          </button>
        ))}
      </div>

      {/* Style tab — existing inspectors */}
      {tab === "style" && (
        <div className={styles.tabContent}>
          <div style={{ display: "flex", gap: "8px", padding: "8px 12px 0" }}>
            <button
              onClick={onBringForward}
              title={t("propertiesPanel.bringForward")}
              aria-label={t("propertiesPanel.bringForward")}
              style={layerBtn}
            >
              {t("propertiesPanel.bringForward")}
            </button>
            <button
              onClick={onSendBackward}
              title={t("propertiesPanel.sendBackward")}
              aria-label={t("propertiesPanel.sendBackward")}
              style={layerBtn}
            >
              {t("propertiesPanel.sendBackward")}
            </button>
          </div>
          <PositionInspector   getCanvas={getCanvas} selectedIds={selectedIds} />
          <AppearanceInspector getCanvas={getCanvas} selectedIds={selectedIds} />
          <TypographyInspector getCanvas={getCanvas} selectedIds={selectedIds} />
          <ShadowInspector     getCanvas={getCanvas} selectedIds={selectedIds} />
          <BorderInspector     getCanvas={getCanvas} selectedIds={selectedIds} />
          <EffectsInspector    getCanvas={getCanvas} selectedIds={selectedIds} />
        </div>
      )}

      {/* Action tab — event bindings */}
      {tab === "action" && (
        <div className={styles.tabContent}>
          <div className={styles.eventList}>
            {EVENTS.map(ev => (
              <div key={ev} className={styles.eventItem}>
                <span className={styles.eventName}>{ev}</span>
                <span style={{ fontSize: 11, color: "var(--text-secondary)" }}>
                  {t("propertiesPanel.action.noAction", "No action")}
                </span>
              </div>
            ))}
            <button className={styles.eventAdd}>
              + {t("propertiesPanel.action.addEvent", "Add event")}
            </button>
          </div>
        </div>
      )}

      {/* Data tab — data bindings */}
      {tab === "data" && (
        <div className={styles.tabContent}>
          <div className={styles.dataSection}>
            {t("propertiesPanel.data.binding", "Data binding")}
          </div>
          {[
            { label: t("propertiesPanel.data.source", "Source"), placeholder: "e.g. users[0].name" },
            { label: t("propertiesPanel.data.format", "Format"), placeholder: "e.g. {value}" },
          ].map(({ label, placeholder }) => (
            <div key={label} className={styles.dataRow}>
              <span className={styles.dataLabel}>{label}</span>
              <input
                className={styles.dataField}
                placeholder={placeholder}
                type="text"
                readOnly
              />
            </div>
          ))}
          <div className={styles.dataSection} style={{ marginTop: 8 }}>
            {t("propertiesPanel.data.visibility", "Visibility")}
          </div>
          <div className={styles.dataRow}>
            <span className={styles.dataLabel}>{t("propertiesPanel.data.showIf", "Show if")}</span>
            <input
              className={styles.dataField}
              placeholder="e.g. user.role === 'admin'"
              type="text"
              readOnly
            />
          </div>
        </div>
      )}

      {/* AI tab — AI-assisted suggestions */}
      {tab === "ai" && (
        <div className={styles.tabContent}>
          <div className={styles.aiSuggest}>
            <div style={{ fontSize: 11, color: "var(--text-secondary)", marginBottom: 10 }}>
              {t("propertiesPanel.ai.quickActions", "Quick actions")}
            </div>
            {[
              t("propertiesPanel.ai.suggest.style", "Suggest styles"),
              t("propertiesPanel.ai.suggest.spacing", "Fix spacing"),
              t("propertiesPanel.ai.suggest.contrast", "Check contrast"),
              t("propertiesPanel.ai.suggest.copy", "Rewrite copy"),
            ].map(label => (
              <span key={label} className={styles.aiChip}>{label}</span>
            ))}
            <div className={styles.aiPromptRow}>
              <input
                className={styles.aiPromptInput}
                placeholder={t("propertiesPanel.ai.promptPlaceholder", "Ask AI about this element…")}
                value={aiPrompt}
                onChange={e => setAiPrompt(e.target.value)}
              />
              <button
                className={styles.aiPromptBtn}
                disabled={!aiPrompt.trim()}
                onClick={() => setAiPrompt("")}
              >
                {t("propertiesPanel.ai.send", "Ask")}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
