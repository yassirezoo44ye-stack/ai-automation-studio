/**
 * AppTreePanel
 *
 * The primary left panel for Flow App Builder.
 * Shows the app structure tree: APP / DATA / AI / AUTOMATION / DEPLOY.
 *
 * The original drawing tools (Rect / Circle / Text / …) are preserved via
 * the "Insert & Design Tools" button at the bottom, which switches the
 * DesignStudio back to the classic LeftToolbar + panel mode. No Fabric.js
 * capability is lost — it is just moved to a sub-mode.
 */
import { useState } from "react";
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
  label: string;
  icon: string;
  badge?: number;
  comingSoon?: boolean;
}

interface TreeGroup {
  id: string;
  label: string;
  items: TreeItem[];
}

const TREE_GROUPS: TreeGroup[] = [
  {
    id: "app",
    label: "APP",
    items: [
      { id: "pages",      label: "Pages",      icon: "⊟", badge: 3 },
      { id: "components", label: "Components", icon: "◫"            },
      { id: "navigation", label: "Navigation", icon: "≡"            },
      { id: "theme",      label: "Theme",      icon: "◑"            },
    ],
  },
  {
    id: "data",
    label: "DATA",
    items: [
      { id: "tables",   label: "Tables", icon: "⊞" },
      { id: "forms",    label: "Forms",  icon: "⊟" },
      { id: "api-data", label: "API",    icon: "⌗"  },
    ],
  },
  {
    id: "ai",
    label: "AI",
    items: [
      { id: "agents",     label: "Agents",     icon: "◉"                    },
      { id: "ai-actions", label: "AI Actions", icon: "⚡"                    },
      { id: "knowledge",  label: "Knowledge",  icon: "⊠", comingSoon: true  },
      { id: "models",     label: "Models",     icon: "◈"                    },
    ],
  },
  {
    id: "automation",
    label: "AUTOMATION",
    items: [
      { id: "workflows", label: "Workflows", icon: "⊡"                   },
      { id: "triggers",  label: "Triggers",  icon: "◐"                   },
      { id: "events",    label: "Events",    icon: "◔", comingSoon: true },
      { id: "jobs",      label: "Jobs",      icon: "⊜", comingSoon: true },
    ],
  },
  {
    id: "deploy",
    label: "DEPLOY",
    items: [
      { id: "deploy-preview", label: "Preview",    icon: "▶"                   },
      { id: "production",     label: "Production", icon: "⬆", comingSoon: true },
      { id: "domains",        label: "Domains",    icon: "⊕", comingSoon: true },
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
    <aside className={styles.panel} aria-label="App structure">
      {/* Header */}
      <div className={styles.header}>
        <span className={styles.headerTitle}>Flow App Builder</span>
      </div>

      {/* Tree */}
      <div className={styles.tree}>
        {/* Overview */}
        <button
          className={`${styles.treeItem} ${activeSection === "overview" ? styles.active : ""}`}
          onClick={() => onSectionChange("overview")}
        >
          <span className={styles.icon}>⌂</span>
          <span>Overview</span>
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
              {group.label}
            </button>

            {expandedGroups.has(group.id) && (
              <div>
                {group.items.map(item => (
                  <button
                    key={item.id}
                    className={`${styles.treeItem} ${styles.indented} ${activeSection === item.id ? styles.active : ""}`}
                    onClick={() => !item.comingSoon && onSectionChange(item.id)}
                    disabled={item.comingSoon}
                    title={item.comingSoon ? "Coming soon" : item.label}
                    aria-pressed={activeSection === item.id}
                  >
                    <span className={styles.icon}>{item.icon}</span>
                    <span className={styles.label}>{item.label}</span>
                    {item.badge !== undefined && (
                      <span className={styles.badge}>{item.badge}</span>
                    )}
                    {item.comingSoon && (
                      <span className={styles.soon}>Soon</span>
                    )}
                  </button>
                ))}
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
          title="Switch to drawing and layer tools"
        >
          <span>⊞</span>
          <span>Insert &amp; Design Tools</span>
        </button>
      </div>
    </aside>
  );
}
