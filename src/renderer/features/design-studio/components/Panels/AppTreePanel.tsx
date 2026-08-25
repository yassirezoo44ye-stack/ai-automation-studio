/**
 * AppTreePanel
 *
 * The primary left panel for Flow App Builder.
 * Shows the app structure tree: APP / DATA / AI / AUTOMATION / DEPLOY.
 *
 * All user-visible strings use i18n (designStudio namespace).
 * The original drawing tools (Rect / Circle / Text / …) are preserved via
 * the "Insert & Design Tools" button at the bottom, which switches the
 * DesignStudio back to the classic LeftToolbar + panel mode.
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";
import styles from "./AppTreePanel.module.css";

// ── Section types ─────────────────────────────────────────────────────────────

export type AppSection =
  | "overview"
  // APP
  | "pages" | "components" | "navigation" | "theme"
  // DATA
  | "tables" | "forms" | "api-data"
  // AI
  | "agents" | "ai-actions" | "knowledge" | "models"
  // AUTOMATION
  | "workflows" | "triggers" | "events" | "jobs"
  // DEPLOY
  | "deploy-preview" | "production" | "domains";

interface TreeItem {
  id: AppSection;
  icon: string;
  badge?: number;
  comingSoon?: boolean;
}

interface TreeGroup {
  id: string;
  items: TreeItem[];
}

// Labels for groups/items come from i18n — no hardcoded strings here.
const TREE_GROUPS: TreeGroup[] = [
  {
    id: "app",
    items: [
      { id: "pages",      icon: "⊟", badge: 3 },
      { id: "components", icon: "◫"            },
      { id: "navigation", icon: "≡"            },
      { id: "theme",      icon: "◑"            },
    ],
  },
  {
    id: "data",
    items: [
      { id: "tables",   icon: "⊞" },
      { id: "forms",    icon: "⊟" },
      { id: "api-data", icon: "⌗"  },
    ],
  },
  {
    id: "ai",
    items: [
      { id: "agents",     icon: "◉"                    },
      { id: "ai-actions", icon: "⚡"                    },
      { id: "knowledge",  icon: "⊠", comingSoon: true  },
      { id: "models",     icon: "◈"                    },
    ],
  },
  {
    id: "automation",
    items: [
      { id: "workflows", icon: "⊡"                   },
      { id: "triggers",  icon: "◐"                   },
      { id: "events",    icon: "◔", comingSoon: true },
      { id: "jobs",      icon: "⊜", comingSoon: true },
    ],
  },
  {
    id: "deploy",
    items: [
      { id: "deploy-preview", icon: "▶"                   },
      { id: "production",     icon: "⬆", comingSoon: true },
      { id: "domains",        icon: "⊕", comingSoon: true },
    ],
  },
];

// ── Component ─────────────────────────────────────────────────────────────────

interface Props {
  activeSection: AppSection | null;
  onSectionChange: (id: AppSection) => void;
  /** Switches DesignStudio back to the original LeftToolbar + panel layout */
  onSwitchToInsert: () => void;
}

export function AppTreePanel({ activeSection, onSectionChange, onSwitchToInsert }: Props) {
  const { t } = useTranslation("designStudio");

  // APP section is expanded by default so new users see page list immediately
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set(["app"]));

  const toggleGroup = (id: string) => {
    setExpandedGroups(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  return (
    <aside className={styles.panel} aria-label={t("appTreePanel.ariaLabel")}>
      {/* Header */}
      <div className={styles.header}>
        <span className={styles.headerTitle}>{t("appTreePanel.headerTitle")}</span>
      </div>

      {/* Tree */}
      <div className={styles.tree}>
        {/* Overview */}
        <button
          className={`${styles.treeItem} ${activeSection === "overview" ? styles.active : ""}`}
          onClick={() => onSectionChange("overview")}
        >
          <span className={styles.icon}>⌂</span>
          <span>{t("appTreePanel.overview")}</span>
        </button>

        {/* Groups */}
        {TREE_GROUPS.map(group => (
          <div key={group.id} className={styles.group}>
            <button
              className={styles.groupHeader}
              onClick={() => toggleGroup(group.id)}
              aria-expanded={expandedGroups.has(group.id)}
            >
              <span className={styles.chevron}>
                {expandedGroups.has(group.id) ? "▾" : "▸"}
              </span>
              {t(`appTreePanel.groups.${group.id}`)}
            </button>

            {expandedGroups.has(group.id) && (
              <div>
                {group.items.map(item => {
                  const itemLabel = t(`appTreePanel.items.${item.id}`);
                  return (
                    <button
                      key={item.id}
                      className={`${styles.treeItem} ${styles.indented} ${activeSection === item.id ? styles.active : ""}`}
                      onClick={() => !item.comingSoon && onSectionChange(item.id)}
                      disabled={item.comingSoon}
                      title={item.comingSoon ? t("appTreePanel.comingSoon") : itemLabel}
                      aria-pressed={activeSection === item.id}
                    >
                      <span className={styles.icon}>{item.icon}</span>
                      <span className={styles.label}>{itemLabel}</span>
                      {item.badge !== undefined && (
                        <span className={styles.badge}>{item.badge}</span>
                      )}
                      {item.comingSoon && (
                        <span className={styles.soon}>{t("appTreePanel.comingSoon")}</span>
                      )}
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Footer — switch to Insert / Design Tools mode */}
      <div className={styles.footer}>
        <button
          className={styles.insertBtn}
          onClick={onSwitchToInsert}
          title={t("appTreePanel.insertToolsTitle")}
        >
          <span>⊞</span>
          <span>{t("appTreePanel.insertTools")}</span>
        </button>
      </div>
    </aside>
  );
}
