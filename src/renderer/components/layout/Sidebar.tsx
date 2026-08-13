import { useTranslation } from "react-i18next";
import { useAppContext } from "../../contexts/app";
import { useAuth } from "../../contexts/AuthContext";
import { useOrg } from "../../contexts/OrgContext";
import { useLangContext } from "../../contexts/lang";
import { motion } from "framer-motion";
import { Icons } from "../../icons";
import { NotificationBell } from "../../shared/ui/notifications";
import type { Page } from "../../types";

type NavItem = { id: Page; navKey: string; icon: keyof typeof Icons };
const NAV_GROUPS: { groupKey: string; items: NavItem[] }[] = [
  {
    groupKey: "workspace", items: [
      { id: "home",        navKey: "home",       icon: "home"        },
      { id: "app-builder", navKey: "appBuilder",  icon: "app-builder" },
      { id: "marketplace", navKey: "marketplace", icon: "templates"   },
    ],
  },
  {
    groupKey: "build", items: [
      { id: "design",       navKey: "design",       icon: "design"       },
      { id: "agentos",      navKey: "agentos",      icon: "agentos"      },
      { id: "automation",   navKey: "automation",   icon: "automation"   },
      { id: "runs",         navKey: "runs",         icon: "runs"         },
      { id: "integrations", navKey: "integrations", icon: "integrations" },
    ],
  },
  {
    groupKey: "platform", items: [
      { id: "observability", navKey: "observability", icon: "data"         },
      { id: "ai-routing",    navKey: "aiRouting",     icon: "api"          },
      { id: "plugins",       navKey: "plugins",       icon: "plugins"      },
      { id: "sandbox",       navKey: "sandbox",       icon: "analytics"    },
    ],
  },
  {
    groupKey: "system", items: [
      { id: "organizations", navKey: "organizations", icon: "organizations" },
      { id: "settings",      navKey: "settings",      icon: "settings"      },
    ],
  },
];

function SunIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/>
    </svg>
  );
}

function MoonIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
    </svg>
  );
}

function GlobeIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="12" r="10"/>
      <line x1="2" y1="12" x2="22" y2="12"/>
      <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>
    </svg>
  );
}

/** Flow wordmark — shown when sidebar is expanded */
function FlowLogo() {
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 10,
      padding: "20px 16px 16px",
      borderBottom: "1px solid var(--b1)",
      marginBottom: 4,
    }}>
      {/* App icon */}
      <div style={{
        width: 32, height: 32, borderRadius: 10, flexShrink: 0,
        background: "linear-gradient(135deg, var(--accent) 0%, var(--teal) 100%)",
        display: "flex", alignItems: "center", justifyContent: "center",
      }}>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/>
        </svg>
      </div>
      <div>
        <div style={{ fontSize: 15, fontWeight: 700, letterSpacing: "-0.3px", color: "var(--t1)", lineHeight: 1.2 }}>Flow</div>
        <div style={{ fontSize: 10, color: "var(--t4)", fontWeight: 500, letterSpacing: "0.04em" }}>AI Business OS</div>
      </div>
    </div>
  );
}

/** Collapsed logo — just the icon */
function FlowIcon() {
  return (
    <div style={{ display: "flex", justifyContent: "center", padding: "18px 0 14px", borderBottom: "1px solid var(--b1)", marginBottom: 4 }}>
      <div style={{
        width: 32, height: 32, borderRadius: 10,
        background: "linear-gradient(135deg, var(--accent) 0%, var(--teal) 100%)",
        display: "flex", alignItems: "center", justifyContent: "center",
      }}>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
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
  const { page, setPage, sidebarCollapsed, setSidebarCollapsed, theme, toggleTheme } = useAppContext();
  const { user, logout } = useAuth();
  const { orgs, currentOrgId, setCurrentOrgId } = useOrg();
  const { lang, toggleLang } = useLangContext();

  const handleNav = (id: Page) => {
    setPage(id);
    onMobileClose?.();
  };

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
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            {sidebarCollapsed ? <polyline points="9 18 15 12 9 6" /> : <polyline points="15 18 9 12 15 6" />}
          </svg>
        </button>

        {/* Org switcher */}
        {orgs.length > 0 && (
          <div style={{ padding: sidebarCollapsed ? "0 8px 8px" : "0 12px 10px" }}>
            <select
              value={currentOrgId ?? ""}
              onChange={e => setCurrentOrgId(e.target.value || null)}
              aria-label={t("sidebar.selectOrg")}
              title={orgs.find(o => o.id === currentOrgId)?.name ?? t("sidebar.selectOrg")}
              style={{
                width: "100%", fontSize: sidebarCollapsed ? 0 : 12,
                background: "var(--bg-input)", color: "var(--t2)",
                border: "1px solid var(--b1)", borderRadius: 8,
                padding: sidebarCollapsed ? "6px 2px" : "7px 10px",
                cursor: "pointer", outline: "none",
              }}
            >
              {orgs.map(o => <option key={o.id} value={o.id}>{o.name}</option>)}
            </select>
          </div>
        )}

        <nav className="sidebar__nav">
          {NAV_GROUPS.map(group => (
            <div key={group.groupKey} className="sidebar__group">
              {!sidebarCollapsed && (
                <div className="sidebar__group-label">{t(`sidebar.groups.${group.groupKey}`)}</div>
              )}
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
                      <motion.span layoutId="sidebar-active-pill" className="sidebar__pill"
                                   transition={{ type: "spring", stiffness: 420, damping: 32 }} />
                    )}
                    <span className="sidebar__icon" aria-hidden="true"><Icon /></span>
                    {!sidebarCollapsed && <span className="sidebar__label">{label}</span>}
                  </button>
                );
              })}
            </div>
          ))}
        </nav>

        {/* Footer actions */}
        <div style={{ marginTop: "auto", display: "flex", flexDirection: "column", gap: 2 }}>
          <NotificationBell collapsed={sidebarCollapsed} />
          <button
            className="sidebar__item"
            onClick={toggleTheme}
            title={theme === "dark" ? t("sidebar.switchToLight") : t("sidebar.switchToDark")}
            aria-label={theme === "dark" ? t("sidebar.switchToLight") : t("sidebar.switchToDark")}
          >
            <span className="sidebar__icon" aria-hidden="true">
              {theme === "dark" ? <SunIcon /> : <MoonIcon />}
            </span>
            {!sidebarCollapsed && (
              <span className="sidebar__label">{theme === "dark" ? t("sidebar.light") : t("sidebar.dark")}</span>
            )}
          </button>

          <button
            className="sidebar__item"
            onClick={toggleLang}
            title={lang === "en" ? t("sidebar.switchToArabic") : t("sidebar.switchToEnglish")}
            aria-label={lang === "en" ? t("sidebar.switchToArabic") : t("sidebar.switchToEnglish")}
          >
            <span className="sidebar__icon" aria-hidden="true"><GlobeIcon /></span>
            {!sidebarCollapsed && (
              <span className="sidebar__label">{lang === "en" ? "العربية" : "English"}</span>
            )}
          </button>

          {user && (
            <button
              className="sidebar__item"
              onClick={() => void logout()}
              title={t("sidebar.signOutTitle", { email: user.email })}
              aria-label={t("sidebar.signOut")}
            >
              <span className="sidebar__icon" aria-hidden="true">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/>
                </svg>
              </span>
              {!sidebarCollapsed && (
                <span className="sidebar__label" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {t("sidebar.signOut")}
                </span>
              )}
            </button>
          )}
        </div>
      </aside>
    </>
  );
}
