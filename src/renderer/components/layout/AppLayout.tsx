import { Suspense, useState, useCallback, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { useAppContext } from "../../contexts/app";
import { useAuth } from "../../contexts/AuthContext";
import { useOrg } from "../../contexts/OrgContext";
import { PageTransition } from "../../shared/ui/gold";
import { ErrorBoundary } from "../../shared/ui/ErrorBoundary";
import { LoadingSpinner } from "../../shared/ui/LoadingSpinner";
import { lazyPage } from "../../shared/lib/staleChunk";
import { Sidebar } from "./Sidebar";
import { CommandPalette } from "./CommandPalette";
import { CopilotButton } from "../../shared/ui/copilot";
import { NotificationBell } from "../../shared/ui/notifications";
import type { Page } from "../../types";

const HomePage        = lazyPage(() => import("../../features/home").then(m => m.HomePage));
const AIWorkspace     = lazyPage(() => import("../../features/ai").then(m => m.AIWorkspace));
const DevWorkspace    = lazyPage(() => import("../../features/dev").then(m => m.DevWorkspace));
const SocialPage      = lazyPage(() => import("../../features/social").then(m => m.SocialPage));
const SettingsPage    = lazyPage(() => import("../../features/settings").then(m => m.SettingsPage));
const DesignStudio    = lazyPage(() => import("../../features/design-studio").then(m => m.DesignStudio));
const AutomationPage  = lazyPage(() => import("../../features/automation/AutomationPage").then(m => m.AutomationPage));
const AgentOSPage     = lazyPage(() => import("../../features/agentos").then(m => m.AgentOSPage));
const MarketplacePage = lazyPage(() => import("../../features/marketplace").then(m => m.MarketplacePage));
const OrganizationsPage = lazyPage(() => import("../../features/organizations").then(m => m.OrganizationsPage));
const TeamsPage         = lazyPage(() => import("../../features/teams").then(m => m.TeamsPage));
const BillingPage       = lazyPage(() => import("../../features/billing").then(m => m.BillingPage));
const PluginsPage       = lazyPage(() => import("../../features/plugins").then(m => m.PluginsPage));
const SandboxPage       = lazyPage(() => import("../../features/sandbox").then(m => m.SandboxPage));
const AIRoutingPage     = lazyPage(() => import("../../features/ai-routing").then(m => m.AIRoutingPage));
const ObservabilityPage = lazyPage(() => import("../../features/observability").then(m => m.ObservabilityPage));
const AppBuilderPage  = lazyPage(() => import("../../features/app-builder").then(m => m.AppBuilderPage));
const RunsPage        = lazyPage(() => import("../../features/runs").then(m => m.RunsPage));
const IntegrationsPage    = lazyPage(() => import("../../features/integrations").then(m => m.IntegrationsPage));
const TrainingStudioPage  = lazyPage(() => import("../../features/training-studio").then(m => m.TrainingStudioPage));
const DevicesPage         = lazyPage(() => import("../../features/devices").then(m => m.DevicesPage));
const BusinessLabPage     = lazyPage(() => import("../../features/business-lab").then(m => m.BusinessLabPage));
const DiscoverPage        = lazyPage(() => import("../../features/discover").then(m => m.DiscoverPage));
const FeedPage            = lazyPage(() => import("../../features/feed").then(m => m.FeedPage));
const CareersPage = lazyPage(() => import("../../features/careers/CareersPage").then(m => m.CareersPage));
const StudyLibraryPage = lazyPage(() => import("../../features/study-library/StudyLibraryPage").then(m => m.StudyLibraryPage));
const LeadsPage           = lazyPage(() => import("../../features/leads").then(m => m.LeadsPage));
const SaasFactoryPage     = lazyPage(() => import("../../features/saas-factory").then(m => m.SaasFactoryPage));
const NewProjectPage      = lazyPage(() => import("../../features/new-project/NewProjectPage").then(m => m.NewProjectPage));

/** Map page keys → sidebar nav translation keys */
const PAGE_NAV_KEY: Record<string, string> = {
  "home":         "home",
  "ai":           "ai",
  "dev":          "dev",
  "design":       "design",
  "automation":   "automation",
  "agentos":      "agentos",
  "marketplace":  "marketplace",
  "plugins":      "plugins",
  "sandbox":      "sandbox",
  "ai-routing":   "aiRouting",
  "observability":"observability",
  "organizations":"organizations",
  "teams":        "teams",
  "billing":      "billing",
  "social":       "social",
  "settings":     "settings",
  "app-builder":  "appBuilder",
  "runs":         "runs",
  "integrations": "integrations",
  "training":     "trainingStudio",
  "devices":        "devices",
  "business-lab":   "businessLab",
  "discover":       "discover",
  "feed":           "feed",
  "careers":        "careers",
  "study-library":  "studyLibrary",
  "leads":          "leads",
  "saas-factory":   "saasFactory",
  "new-project":    "newProject",
};

function SunIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="4"/>
      <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/>
    </svg>
  );
}

function MoonIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
    </svg>
  );
}

function SearchIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
    </svg>
  );
}

/** Global top bar — breadcrumb + search shortcut + theme + notifications + user */
function PageTopBar({ onOpenCmd }: { onOpenCmd: () => void }) {
  const { t } = useTranslation("common");
  const { page, theme, toggleTheme } = useAppContext();

  const { user }       = useAuth();
  const { currentOrg } = useOrg();

  const navKey = PAGE_NAV_KEY[page];
  const pageTitle = navKey ? t(`sidebar.nav.${navKey}`) : page;

  const initials = user?.email
    ? user.email.substring(0, 2).toUpperCase()
    : "FL";

  return (
    <div className="flow-topbar">
      <div className="flow-topbar__left">
        {/* Org name when available */}
        {/* On phones the org name is hidden (CSS) so the page title fits. */}
        {currentOrg && (
          <span className="flow-topbar__org">
            <span style={{ fontSize: 12, color: "var(--t3)", maxWidth: 120, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {currentOrg.name}
            </span>
            <svg aria-hidden="true" className="flow-topbar__chevron" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ color: "var(--b2)", flexShrink: 0 }}>
              <polyline points="9 18 15 12 9 6"/>
            </svg>
          </span>
        )}
        <span className="flow-topbar__crumb">{pageTitle}</span>
      </div>
      <div className="flow-topbar__right">
        {/* Search shortcut */}
        <button className="flow-topbar__search" onClick={onOpenCmd} aria-label={t("appLayout.openCommandPalette", { defaultValue: "Open command palette" })}>
          <SearchIcon />
          <span style={{ color: "var(--t4)", fontSize: 12 }}>{t("appLayout.search", { defaultValue: "Search…" })}</span>
          <span className="flow-topbar__kbd">⌘K</span>
        </button>

        {/* Theme toggle */}
        <button
          className="flow-topbar__btn"
          onClick={toggleTheme}
          title={theme === "dark" ? t("sidebar.switchToLight") : t("sidebar.switchToDark")}
          aria-label={theme === "dark" ? t("sidebar.switchToLight") : t("sidebar.switchToDark")}
        >
          {theme === "dark" ? <SunIcon /> : <MoonIcon />}
        </button>

        {/* Notification bell */}
        <NotificationBell collapsed />

        {/* User avatar chip */}
        {user && (
          <div
            title={user.email}
            aria-label={user.email}
            style={{
              width: 28, height: 28, borderRadius: "50%", flexShrink: 0,
              background: "linear-gradient(135deg, var(--accent), var(--teal))",
              display: "flex", alignItems: "center", justifyContent: "center",
              fontSize: 10, fontWeight: 700, color: "#fff",
              cursor: "default", userSelect: "none",
            }}
          >
            {initials}
          </div>
        )}
      </div>
    </div>
  );
}

function WorkspaceContent() {
  const { t } = useTranslation("common");
  const { page } = useAppContext();
  const fallback = <LoadingSpinner fullPage label={t("appLayout.loadingWorkspace")} />;
  // PageTransition is the OUTER wrapper; ErrorBoundary[key=page] is inside it.
  //
  // History of the removeChild crash (framer-motion + React 19):
  //   v1 (broken):  ErrorBoundary(key=page) > Suspense > PageTransition(AnimatePresence)
  //     When page changed, React immediately unmounted ErrorBoundary, which removed
  //     motion.div from the DOM. framer-motion then tried removeChild the already-gone
  //     node → DOMException.
  //
  //   v2 (still broken): PageTransition(AnimatePresence mode="wait") > ErrorBoundary(key=page)
  //     AnimatePresence held the old motion.div for its exit animation while React
  //     simultaneously remounted ErrorBoundary inside that same motion.div. Both React
  //     cleanup and framer-motion's exit callback called removeChild on the same node
  //     → DOMException propagated to ErrorBoundary → "خطأ في أداة إنشاء التطبيقات".
  //
  //   v3 (current, fixed): PageTransition uses a plain CSS-animated <div key={page}>
  //     React owns the entire DOM lifecycle. When page changes, React unmounts the old
  //     div + all children cleanly (no framer-motion holding a reference), then mounts
  //     the new div with a CSS enter animation. No imperative removeChild races possible.
  //     ErrorBoundary[key=page] still resets on navigation (test guard preserved).
  return (
    <PageTransition pageKey={page}>
      <ErrorBoundary key={page} name={page}>
        <Suspense fallback={fallback}>
          {page === "home"          && <HomePage />}
          {page === "ai"            && <AIWorkspace />}
          {page === "dev"           && <DevWorkspace />}
          {page === "design"        && <DesignStudio />}
          {page === "automation"    && <AutomationPage />}
          {page === "agentos"       && <AgentOSPage />}
          {page === "marketplace"   && <MarketplacePage />}
          {page === "organizations" && <OrganizationsPage />}
          {page === "teams"         && <TeamsPage />}
          {page === "billing"       && <BillingPage />}
          {page === "plugins"       && <PluginsPage />}
          {page === "sandbox"       && <SandboxPage />}
          {page === "ai-routing"    && <AIRoutingPage />}
          {page === "observability" && <ObservabilityPage />}
          {page === "social"        && <SocialPage />}
          {page === "settings"      && <SettingsPage />}
          {page === "app-builder"   && <AppBuilderPage />}
          {page === "runs"          && <RunsPage />}
          {page === "integrations"  && <IntegrationsPage />}
          {page === "training"      && <TrainingStudioPage />}
          {page === "devices"       && <DevicesPage />}
          {page === "business-lab"  && <BusinessLabPage />}
          {page === "discover"      && <DiscoverPage />}
          {page === "feed"          && <FeedPage />}
          {page === "careers"       && <CareersPage />}
          {page === "study-library" && <div className="study-library-workspace"><StudyLibraryPage /></div>}
          {page === "leads"         && <LeadsPage />}
          {page === "saas-factory"  && <SaasFactoryPage />}
          {page === "new-project"   && <NewProjectPage />}
        </Suspense>
      </ErrorBoundary>
    </PageTransition>
  );
}

export function AppLayout() {
  const { t } = useTranslation("common");
  const { page, setPage, isPageTransitioning } = useAppContext();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [cmdOpen,    setCmdOpen]    = useState(false);
  const closeMobile = useCallback(() => setMobileOpen(false), []);

  useEffect(() => {
    function handler(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && e.key === "k") {
        e.preventDefault();
        setCmdOpen(v => !v);
      }
      if (e.key === "Escape") setCmdOpen(false);
    }
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  const handleCmdNavigate = useCallback((p: Page) => {
    setPage(p);
    setCmdOpen(false);
  }, [setPage]);

  return (
    <>
      {/* Skip-to-content */}
      <a href="#main-content" className="skip-link">{t("appLayout.skipToContent")}</a>

      {/* Mobile hamburger */}
      <button
        className="mobile-menu-btn"
        onClick={() => setMobileOpen(v => !v)}
        aria-label={t("appLayout.openNavMenu")}
        aria-expanded={mobileOpen}
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M3 12h18M3 6h18M3 18h18"/>
        </svg>
      </button>

      <div className="app-layout">
        <Sidebar mobileOpen={mobileOpen} onMobileClose={closeMobile} />
        <main id="main-content" className="app-main">
          {/* Global top bar */}
          <PageTopBar onOpenCmd={() => setCmdOpen(v => !v)} />

          {/* Page-switch progress bar */}
          {isPageTransitioning && <div className="page-nav-progress" aria-hidden="true" />}

          <WorkspaceContent />
        </main>
      </div>

      {cmdOpen && (
        <CommandPalette
          onNavigate={handleCmdNavigate}
          onClose={() => setCmdOpen(false)}
        />
      )}

      {/* The floating copilot duplicates — and covered the Send button of —
          the full AI assistant page, so it is hidden there. */}
      {page !== "ai" && <CopilotButton />}
    </>
  );
}
