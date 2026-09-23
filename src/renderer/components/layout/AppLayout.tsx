import { lazy, Suspense, useState, useCallback, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { useAppContext } from "../../contexts/app";
import { PageTransition } from "../../shared/ui/gold";
import { ErrorBoundary } from "../../shared/ui/ErrorBoundary";
import { LoadingSpinner } from "../../shared/ui/LoadingSpinner";
import { Sidebar } from "./Sidebar";
import { CommandPalette } from "./CommandPalette";
import { CopilotButton } from "../../shared/ui/copilot";
import { NotificationBell } from "../../shared/ui/notifications";
import type { Page } from "../../types";

// When a deploy replaces a lazy chunk the old in-memory bundle references the
// old hash, which 404s.  Catch only genuine stale-chunk TypeErrors (identified
// by their browser-issued message), reload once, and let the fresh bundle load
// the correct chunk.  sessionStorage guards against an infinite reload loop if
// the chunk is genuinely missing rather than just stale.
const _CHUNK_RELOAD_KEY = "__flow_chunk_reload__";

// Substrings emitted by each browser when a dynamic import 404s after a deploy.
// Deliberately NOT matching every TypeError — only these browser-native messages
// confirm the error is a failed network fetch, not a runtime error inside the
// imported module (e.g. "Cannot read properties of undefined").
const _STALE_CHUNK_MSGS = [
  "Failed to fetch dynamically imported module", // Chrome / Edge
  "Importing a module script failed",            // Safari
  "error loading dynamically imported module",   // Firefox
];

export function _isStaleChunkError(err: unknown): boolean {
  if (!(err instanceof TypeError)) return false;
  const msg = (err as TypeError).message;
  return _STALE_CHUNK_MSGS.some(p => msg.includes(p));
}

function chunkFallback(err: unknown): never {
  if (_isStaleChunkError(err)) {
    try {
      if (!sessionStorage.getItem(_CHUNK_RELOAD_KEY)) {
        sessionStorage.setItem(_CHUNK_RELOAD_KEY, "1");
        window.location.reload();
      }
    } catch { /* private browsing — sessionStorage unavailable; skip reload guard */ }
  }
  throw err;
}

const HomePage        = lazy(() => import("../../features/home").then(m => ({ default: m.HomePage })).catch(chunkFallback));
const AIWorkspace     = lazy(() => import("../../features/ai").then(m => ({ default: m.AIWorkspace })).catch(chunkFallback));
const DevWorkspace    = lazy(() => import("../../features/dev").then(m => ({ default: m.DevWorkspace })).catch(chunkFallback));
const SocialPage      = lazy(() => import("../../features/social").then(m => ({ default: m.SocialPage })).catch(chunkFallback));
const SettingsPage    = lazy(() => import("../../features/settings").then(m => ({ default: m.SettingsPage })).catch(chunkFallback));
const DesignStudio    = lazy(() => import("../../features/design-studio").then(m => ({ default: m.DesignStudio })).catch(chunkFallback));
const AutomationPage  = lazy(() => import("../../features/automation/AutomationPage").then(m => ({ default: m.AutomationPage })).catch(chunkFallback));
const AgentOSPage     = lazy(() => import("../../features/agentos").then(m => ({ default: m.AgentOSPage })).catch(chunkFallback));
const MarketplacePage = lazy(() => import("../../features/marketplace").then(m => ({ default: m.MarketplacePage })).catch(chunkFallback));
const OrganizationsPage = lazy(() => import("../../features/organizations").then(m => ({ default: m.OrganizationsPage })).catch(chunkFallback));
const TeamsPage         = lazy(() => import("../../features/teams").then(m => ({ default: m.TeamsPage })).catch(chunkFallback));
const BillingPage       = lazy(() => import("../../features/billing").then(m => ({ default: m.BillingPage })).catch(chunkFallback));
const PluginsPage       = lazy(() => import("../../features/plugins").then(m => ({ default: m.PluginsPage })).catch(chunkFallback));
const SandboxPage       = lazy(() => import("../../features/sandbox").then(m => ({ default: m.SandboxPage })).catch(chunkFallback));
const AIRoutingPage     = lazy(() => import("../../features/ai-routing").then(m => ({ default: m.AIRoutingPage })).catch(chunkFallback));
const ObservabilityPage = lazy(() => import("../../features/observability").then(m => ({ default: m.ObservabilityPage })).catch(chunkFallback));
const AppBuilderPage  = lazy(() => import("../../features/app-builder").then(m => ({ default: m.AppBuilderPage })).catch(chunkFallback));
const RunsPage        = lazy(() => import("../../features/runs").then(m => ({ default: m.RunsPage })).catch(chunkFallback));
const IntegrationsPage    = lazy(() => import("../../features/integrations").then(m => ({ default: m.IntegrationsPage })).catch(chunkFallback));
const TrainingStudioPage  = lazy(() => import("../../features/training-studio").then(m => ({ default: m.TrainingStudioPage })).catch(chunkFallback));
const DevicesPage         = lazy(() => import("../../features/devices").then(m => ({ default: m.DevicesPage })).catch(chunkFallback));
const BusinessLabPage     = lazy(() => import("../../features/business-lab").then(m => ({ default: m.BusinessLabPage })).catch(chunkFallback));
const DiscoverPage        = lazy(() => import("../../features/discover").then(m => ({ default: m.DiscoverPage })).catch(chunkFallback));
const FeedPage            = lazy(() => import("../../features/feed").then(m => ({ default: m.FeedPage })).catch(chunkFallback));

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

/** Global top bar — breadcrumb + search shortcut + theme + notifications */
function PageTopBar({ onOpenCmd }: { onOpenCmd: () => void }) {
  const { t } = useTranslation("common");
  const { page, theme, toggleTheme } = useAppContext();

  const navKey = PAGE_NAV_KEY[page];
  const pageTitle = navKey ? t(`sidebar.nav.${navKey}`) : page;

  return (
    <div className="flow-topbar">
      <div className="flow-topbar__left">
        {/* Brand separator */}
        <span style={{ fontSize: 11, fontWeight: 700, color: "var(--accent)", letterSpacing: "0.04em", flexShrink: 0 }}>
          FLOW
        </span>
        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ color: "var(--b2)", flexShrink: 0 }}>
          <polyline points="9 18 15 12 9 6"/>
        </svg>
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
        <NotificationBell collapsed={false} />
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
        </Suspense>
      </ErrorBoundary>
    </PageTransition>
  );
}

export function AppLayout() {
  const { t } = useTranslation("common");
  const { setPage, isPageTransitioning } = useAppContext();
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

      <CopilotButton />
    </>
  );
}
