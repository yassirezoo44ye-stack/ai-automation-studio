/**
 * AppTreePanel
 *
 * The primary left panel for Flow App Builder (Workspace section).
 * Shows the app structure tree: APP / DATA / AI / AUTOMATION / DEPLOY.
 *
 * Icons: SVG with currentColor — decorative icons use aria-hidden="true".
 * Shared icons imported from the project icon library; items without a
 * good library match use small inline SVG components defined below.
 *
 * Phase 2: removed dual-mode toggle (onSwitchToInsert / footer).
 * Phase 3: migrated all emoji/Unicode visual icons to SVG.
 */
import type { ReactNode } from "react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Icons } from "../../../../shared/icons";
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

// ── Local SVG icons (items without a match in the shared library) ─────────────
// All: 16×16 viewBox, stroke="currentColor", aria-hidden="true".

const NavigationIcon = () => (
  <svg width="16" height="16" viewBox="0 0 16 16" fill="none"
       xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
    <line x1="2"  y1="4"  x2="14" y2="4"  stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"/>
    <line x1="2"  y1="8"  x2="14" y2="8"  stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"/>
    <line x1="2"  y1="12" x2="10" y2="12" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"/>
  </svg>
);

const FormIcon = () => (
  <svg width="16" height="16" viewBox="0 0 16 16" fill="none"
       xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
    <rect x="2" y="2" width="12" height="12" rx="1.5"
          stroke="currentColor" strokeWidth="1.3"/>
    <line x1="4.5" y1="5.5" x2="11.5" y2="5.5"
          stroke="currentColor" strokeWidth="1.2" strokeLinecap="round"/>
    <line x1="4.5" y1="8"   x2="11.5" y2="8"
          stroke="currentColor" strokeWidth="1.2" strokeLinecap="round"/>
    <line x1="4.5" y1="10.5" x2="8"  y2="10.5"
          stroke="currentColor" strokeWidth="1.2" strokeLinecap="round"/>
  </svg>
);

const TriggerIcon = () => (
  <svg width="16" height="16" viewBox="0 0 16 16" fill="none"
       xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
    <path d="M9 2L3 9h5l-1 5 6-7H8l1-5z"
          stroke="currentColor" strokeWidth="1.3"
          strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
);

const PreviewIcon = () => (
  <svg width="16" height="16" viewBox="0 0 16 16" fill="none"
       xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
    <path d="M1.5 8s2.3-4.5 6.5-4.5S14.5 8 14.5 8 12.2 12.5 8 12.5 1.5 8 1.5 8z"
          stroke="currentColor" strokeWidth="1.3"
          strokeLinecap="round" strokeLinejoin="round"/>
    <circle cx="8" cy="8" r="1.8" stroke="currentColor" strokeWidth="1.3"/>
  </svg>
);

// ── Expand / collapse chevrons ────────────────────────────────────────────────

const ChevronDown = () => (
  <svg width="9" height="9" viewBox="0 0 9 9" fill="none"
       xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
    <path d="M2 3.5L4.5 6L7 3.5"
          stroke="currentColor" strokeWidth="1.4"
          strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
);

const ChevronRight = () => (
  <svg width="9" height="9" viewBox="0 0 9 9" fill="none"
       xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
    <path d="M3.5 2L6 4.5L3.5 7"
          stroke="currentColor" strokeWidth="1.4"
          strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
);

// ── Data model ────────────────────────────────────────────────────────────────

interface TreeItem {
  id:        AppSection;
  icon:      ReactNode;          // SVG ReactNode — replaces emoji string
  badge?:    number;
  comingSoon?: boolean;
}

interface TreeGroup {
  id:    string;
  items: TreeItem[];
}

// Labels for groups/items come from i18n — no hardcoded strings here.
// Priority: existing Icons library > local SVG component.
const TREE_GROUPS: TreeGroup[] = [
  {
    id: "app",
    items: [
      { id: "pages",      icon: <Icons.projects />, badge: 3 },
      { id: "components", icon: <Icons.dashboard />           },
      { id: "navigation", icon: <NavigationIcon />            },
      { id: "theme",      icon: <Icons.design />              },
    ],
  },
  {
    id: "data",
    items: [
      { id: "tables",   icon: <Icons.data />  },
      { id: "forms",    icon: <FormIcon />    },
      { id: "api-data", icon: <Icons.api />   },
    ],
  },
  {
    id: "ai",
    items: [
      { id: "agents",     icon: <Icons.agents />                          },
      { id: "ai-actions", icon: <Icons.ai />                              },
      { id: "knowledge",  icon: <Icons.training />, comingSoon: true      },
      { id: "models",     icon: <Icons.dev />                             },
    ],
  },
  {
    id: "automation",
    items: [
      { id: "workflows", icon: <Icons.workflows />                        },
      { id: "triggers",  icon: <TriggerIcon />                            },
      { id: "events",    icon: <Icons.monitoring />, comingSoon: true     },
      { id: "jobs",      icon: <Icons.tasks />,      comingSoon: true     },
    ],
  },
  {
    id: "deploy",
    items: [
      { id: "deploy-preview", icon: <PreviewIcon />                       },
      { id: "production",     icon: <Icons.package />, comingSoon: true   },
      { id: "domains",        icon: <Icons.social />,  comingSoon: true   },
    ],
  },
];

// ── Component ─────────────────────────────────────────────────────────────────

interface Props {
  activeSection:   AppSection | null;
  onSectionChange: (id: AppSection) => void;
}

export function AppTreePanel({ activeSection, onSectionChange }: Props) {
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
          <span className={styles.icon} aria-hidden="true"><Icons.home /></span>
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
              <span className={styles.chevron} aria-hidden="true">
                {expandedGroups.has(group.id) ? <ChevronDown /> : <ChevronRight />}
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
                      <span className={styles.icon} aria-hidden="true">{item.icon}</span>
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

    </aside>
  );
}
