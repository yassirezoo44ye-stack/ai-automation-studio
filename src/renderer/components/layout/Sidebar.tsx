import { useTranslation } from "react-i18next";
import { useAppContext } from "../../contexts/app";
import { useAuth } from "../../contexts/AuthContext";
import { useOrg } from "../../contexts/OrgContext";
import { useLangContext } from "../../contexts/lang";
import { motion } from "framer-motion";
import { Icons } from "../../icons";
import type { Page } from "../../types";

type NavItem = { id: Page; navKey: string; icon: keyof typeof Icons };


/**
 * Navigation groups — five semantic sections matching the Command Center spec.
 *
 * WORKSPACE  — daily entry points (no label, no sep)
 * BUILD      — creation tools
 * OPERATE    — monitoring & execution
 * PLATFORM   — infrastructure & integrations
 * ORGANIZATION — admin
 */
const NAV_GROUPS: {
  groupKey: string;
  showLabel: boolean;
  showSep: boolean;
  items: NavItem[];
}[] = [
  {
    groupKey: "workspace",
    showLabel: false,
    showSep: false,
    items: [
      { id: "home", navKey: "home", icon: "home"  },
      { id: "ai",   navKey: "ai",   icon: "ai"    },
    ],
  },
  {
    groupKey: "build",
    showLabel: true,
    showSep: true,
    items: [
      { id: "app-builder", navKey: "appBuilder",  icon: "app-builder" },
      { id: "design",      navKey: "design",      icon: "design"      },
      { id: "agentos",     navKey: "agentos",     icon: "agentos"     },
      { id: "automation",  navKey: "automation",  icon: "automation"  },
    ],
  },
  {
    groupKey: "operate",
    showLabel: true,
    showSep: true,
    items: [
      { id: "runs",         navKey: "runs",         icon: "runs"         },
      { id: "observability",navKey: "observability",icon: "data"         },
      { id: "sandbox",      navKey: "sandbox",      icon: "analytics"    },
    ],
  },
  {
    groupKey: "platform",
    showLabel: true,
    showSep: true,
    items: [
      { id: "ai-routing",    navKey: "aiRouting",    icon: "api"          },
      { id: "integrations",  navKey: "integrations", icon: "integrations" },
      { id: "plugins",       navKey: "plugins",      icon: "plugins"      },
      { id: "marketplace",   navKey: "marketplace",  icon: "templates"    },
    ],
  },
  {
    groupKey: "organization",
    showLabel: false,
    showSep: true,
    items: [
      { id: "organizations", navKey: "organizations", icon: "organizations" },
      { id: "teams",         navKey: "teams",         icon: "teams"         },
      { id: "billing",       navKey: "billing",       icon: "billing"       },
      { id: "settings",      navKey: "settings",      icon: "settings"      },
    ],
  },
];

function GlobeIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="10"/>
      <line x1="2" y1="12" x2="22" y2="12"/>
      <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>
    </svg>
  );
}

function SignOutIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/>
      <polyline points="16 17 21 12 16 7"/>
      <line x1="21" y1="12" x2="9" y2="12"/>
    </svg>
  );
}

function CollapseIcon({ collapsed }: { collapsed: boolean }) {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      {collapsed ? <polyline points="9 18 15 12 9 6" /> : <polyline points="15 18 9 12 15 6" />}
    </svg>
  );
}

/** Expanded logo — icon + wordmark */
function FlowLogo() {
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 10,
      padding: "16px 14px 14px",
      borderBottom: "1px solid var(--b1)",
      marginBottom: 6,
      flexShrink: 0,
    }}>
      <div style={{
        width: 30, height: 30, borderRadius: 9, flexShrink: 0,
        background: "linear-gradient(135deg, var(--accent) 0%, var(--teal) 100%)",
        display: "flex", alignItems: "center", justifyContent: "center",
        boxShadow: "var(--glow-pink-subtle)",
      }}>
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
          <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/>
        </svg>
      </div>
      <div>
        <div style={{ fontSize: 14, fontWeight: 800, letterSpacing: "-0.4px", color: "var(--t1)", lineHeight: 1.2 }}>Flow</div>
        <div style={{ fontSize: 9.5, color: "var(--t5)", fontWeight: 500, letterSpacing: "0.06em", textTransform: "uppercase" }}>AI Business OS</div>
      </div>
    </div>
  );
}

/** Collapsed logo — icon only */
function FlowIcon() {
  return (
    <div style={{
      display: "flex", justifyContent: "center",
      padding: "14px 0 12px",
      borderBottom: "1px solid var(--b1)",
      marginBottom: 6,
      flexShrink: 0,
    }}>
      <div style={{
        width: 30, height: 30, borderRadius: 9,
        background: "linear-gradient(135deg, var(--accent) 0%, var(--teal) 100%)",
        display: "flex", alignItems: "center", justifyContent: "center",
        boxShadow: "var(--glow-pink-subtle)",
      }}>
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
          <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/>
        </svg>
      </div>
    </div>
  );
}

interface SidebarProps {
  mobileOpen?: boolean;
  onMobileClose?: () => void;
}

export function Sidebar({ mobileOpen, onMobileClose }: SidebarProps) {
  const { t } = useTranslation("common");
  const { page, setPage, sidebarCollapsed, setSidebarCollapsed } = useAppContext();
  const { user, logout } = useAuth();
  const { orgs, currentOrgId, setCurrentOrgId } = useOrg();
  const { lang, toggleLang } = useLangContext();

  const handleNav = (id: Page) => {
    setPage(id);
    onMobileClose?.();
  };

  // User initials for avatar
  const userInitials = user?.email
    ? user.email.substring(0, 2).toUpperCase()
    : "FL";

  return (
    <>
      {mobileOpen && (
        <div className="sidebar-backdrop" onClick={onMobileClose} aria-hidden="true" />
      )}
      <aside
        className={`sidebar ${sidebarCollapsed ? "sidebar--collapsed" : ""} ${mobileOpen ? "sidebar--open" : ""}`}
        role="navigation"
        aria-label={t("sidebar.mainNav")}
      >
        {/* Logo area */}
        {sidebarCollapsed ? <FlowIcon /> : <FlowLogo />}

        {/* Collapse toggle */}
        <button
          className="sidebar__toggle"
          onClick={() => setSidebarCollapsed(v => !v)}
          aria-label={sidebarCollapsed ? t("sidebar.expand") : t("sidebar.collapse")}
          title={sidebarCollapsed ? t("sidebar.expand") : t("sidebar.collapse")}
        >
          <CollapseIcon collapsed={sidebarCollapsed} />
        </button>

        {/* Org switcher */}
        {orgs.length > 1 && (
          <div style={{ padding: sidebarCollapsed ? "0 8px 6px" : "0 10px 8px" }}>
            <select
              value={currentOrgId ?? ""}
              onChange={e => setCurrentOrgId(e.target.value || null)}
              aria-label={t("sidebar.selectOrg")}
              title={orgs.find(o => o.id === currentOrgId)?.name ?? t("sidebar.selectOrg")}
              style={{
                width: "100%",
                fontSize: sidebarCollapsed ? 0 : 11,
                background: "var(--bg-input)", color: "var(--t3)",
                border: "1px solid var(--b1)", borderRadius: 7,
                padding: sidebarCollapsed ? "6px 2px" : "6px 9px",
                cursor: "pointer", outline: "none", height: 28,
              }}
            >
              {orgs.map(o => <option key={o.id} value={o.id}>{o.name}</option>)}
            </select>
          </div>
        )}

        {/* Navigation */}
        <nav className="sidebar__nav" aria-label={t("sidebar.mainNav")}>
          {NAV_GROUPS.map(group => (
            <div key={group.groupKey}>
              {/* Group separator */}
              {group.showSep && <div className="sidebar__sep" aria-hidden="true" />}

              {/* Group label */}
              {group.showLabel && !sidebarCollapsed && (
                <div className="sidebar__group-label">
                  {t(`sidebar.groups.${group.groupKey}`)}
                </div>
              )}

              <div className="sidebar__group" style={{ marginBottom: 0 }}>
                {group.items.map(item => {
                  const Icon = Icons[item.icon];
                  const active = page === item.id;
                  const label = t(`sidebar.nav.${item.navKey}`);
                  return (
                    <button
                      key={item.id}
                      className={`sidebar__item ${active ? "sidebar__item--active" : ""}`}
                      onClick={() => handleNav(item.id)}
                      aria-current={active ? "page" : undefined}
                      title={label}
                    >
                      {active && (
                        <motion.span
                          layoutId="sidebar-active-pill"
                          className="sidebar__pill"
                          transition={{ type: "spring", stiffness: 500, damping: 36 }}
                        />
                      )}
                      <span className="sidebar__icon" aria-hidden="true">
                        <Icon />
                      </span>
                      {!sidebarCollapsed && (
                        <span className="sidebar__label">{label}</span>
                      )}
                    </button>
                  );
                })}
              </div>
            </div>
          ))}
        </nav>

        {/* Footer */}
        <div className="sidebar__user-footer">
          {/* Lang toggle */}
          <button
            className="sidebar__item"
            onClick={toggleLang}
            title={lang === "en" ? t("sidebar.switchToArabic") : t("sidebar.switchToEnglish")}
            aria-label={lang === "en" ? t("sidebar.switchToArabic") : t("sidebar.switchToEnglish")}
            style={{ minHeight: 34 }}
          >
            <span className="sidebar__icon" aria-hidden="true"><GlobeIcon /></span>
            {!sidebarCollapsed && (
              <span className="sidebar__label" style={{ fontSize: 12 }}>
                {lang === "en" ? "العربية" : "English"}
              </span>
            )}
          </button>

          {/* User info + logout */}
          {user && (
            <button
              className="sidebar__item"
              onClick={() => void logout()}
              title={t("sidebar.signOutTitle", { email: user.email })}
              aria-label={t("sidebar.signOut")}
              style={{ minHeight: 34 }}
            >
              {sidebarCollapsed ? (
                <span className="sidebar__icon" aria-hidden="true">
                  <SignOutIcon />
                </span>
              ) : (
                <>
                  <span className="sidebar__avatar" aria-hidden="true">{userInitials}</span>
                  <span
                    className="sidebar__label"
                    style={{
                      overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                      fontSize: 12, flex: 1, textAlign: "start",
                    }}
                  >
                    {user.email}
                  </span>
                  <span style={{ flexShrink: 0, color: "var(--t5)", display: "flex" }}>
                    <SignOutIcon />
                  </span>
                </>
              )}
            </button>
          )}
        </div>
      </aside>
    </>
  );
}
