import { useAppContext } from "../../contexts/AppContext";
import { useAuth } from "../../contexts/AuthContext";
import { useOrg } from "../../contexts/OrgContext";
import { Icons } from "../../icons";
import type { Page } from "../../types";

const NAV: { id: Page; label: string; icon: keyof typeof Icons }[] = [
  { id: "home",       label: "Home",       icon: "home"       },
  { id: "ai",         label: "AI",         icon: "ai"         },
  { id: "dev",        label: "Dev",        icon: "dev"        },
  { id: "design",     label: "Design",     icon: "design"     },
  { id: "automation", label: "Automation", icon: "automation" },
  { id: "agentos",       label: "AgentOS",       icon: "agentos"       },
  { id: "marketplace",   label: "Marketplace",   icon: "marketplace"   },
  { id: "plugins",       label: "Plugins",       icon: "plugins"       },
  { id: "sandbox",       label: "Sandbox",       icon: "sandbox"       },
  { id: "organizations", label: "Organizations", icon: "organizations" },
  { id: "teams",         label: "Teams",         icon: "teams"         },
  { id: "billing",       label: "Billing",       icon: "billing"       },
  { id: "social",      label: "Social",      icon: "social"      },
  { id: "settings",    label: "Settings",    icon: "settings"    },
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

interface SidebarProps {
  mobileOpen?: boolean;
  onMobileClose?: () => void;
}

export function Sidebar({ mobileOpen, onMobileClose }: SidebarProps) {
  const { page, setPage, sidebarCollapsed, setSidebarCollapsed, theme, toggleTheme } = useAppContext();
  const { user, logout } = useAuth();
  const { orgs, currentOrgId, setCurrentOrgId } = useOrg();

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
        aria-label="Main navigation"
      >
        <button
          className="sidebar__toggle"
          onClick={() => setSidebarCollapsed(v => !v)}
          aria-label={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
          title={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {sidebarCollapsed ? "›" : "‹"}
        </button>

        {orgs.length > 0 && (
          <div style={{ padding: sidebarCollapsed ? "0 8px 8px" : "0 12px 10px" }}>
            <select
              value={currentOrgId ?? ""}
              onChange={e => setCurrentOrgId(e.target.value || null)}
              aria-label="Current organization"
              title={orgs.find(o => o.id === currentOrgId)?.name ?? "Select organization"}
              style={{
                width: "100%", fontSize: sidebarCollapsed ? 0 : 12,
                background: "rgba(255,255,255,0.05)", color: "#e2e8f0",
                border: "1px solid rgba(255,255,255,0.09)", borderRadius: 8,
                padding: sidebarCollapsed ? "6px 2px" : "7px 10px",
                cursor: "pointer", outline: "none",
              }}
            >
              {orgs.map(o => <option key={o.id} value={o.id}>{o.name}</option>)}
            </select>
          </div>
        )}

        <nav className="sidebar__nav">
          {NAV.map(item => {
            const Icon = Icons[item.icon];
            const active = page === item.id;
            return (
              <button
                key={item.id}
                className={`sidebar__item ${active ? "sidebar__item--active" : ""}`}
                onClick={() => handleNav(item.id)}
                aria-current={active ? "page" : undefined}
                title={item.label}
              >
                <span className="sidebar__icon" aria-hidden="true"><Icon /></span>
                {!sidebarCollapsed && <span className="sidebar__label">{item.label}</span>}
              </button>
            );
          })}
        </nav>

        <div style={{ marginTop: "auto", display: "flex", flexDirection: "column", gap: 2 }}>
          <button
            className="sidebar__item"
            onClick={toggleTheme}
            title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
            aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
          >
            <span className="sidebar__icon" aria-hidden="true">
              {theme === "dark" ? <SunIcon /> : <MoonIcon />}
            </span>
            {!sidebarCollapsed && (
              <span className="sidebar__label">{theme === "dark" ? "Light" : "Dark"}</span>
            )}
          </button>

          {user && (
            <button
              className="sidebar__item"
              onClick={() => void logout()}
              title={`Sign out (${user.email})`}
              aria-label="Sign out"
            >
              <span className="sidebar__icon" aria-hidden="true">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/>
                </svg>
              </span>
              {!sidebarCollapsed && (
                <span className="sidebar__label" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  Sign Out
                </span>
              )}
            </button>
          )}
        </div>
      </aside>
    </>
  );
}
