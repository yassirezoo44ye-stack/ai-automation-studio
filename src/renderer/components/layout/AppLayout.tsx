import { lazy, Suspense, useState, useCallback, useEffect } from "react";
import { useAppContext } from "../../contexts/app";
import { PageTransition } from "../../shared/ui/gold";
import { ErrorBoundary } from "../../shared/ui/ErrorBoundary";
import { LoadingSpinner } from "../../shared/ui/LoadingSpinner";
import { Sidebar } from "./Sidebar";
import { CommandPalette } from "./CommandPalette";
import type { Page } from "../../types";

const HomePage       = lazy(() => import("../../features/home").then(m => ({ default: m.HomePage })));
const AIWorkspace    = lazy(() => import("../../features/ai").then(m => ({ default: m.AIWorkspace })));
const DevWorkspace   = lazy(() => import("../../features/dev").then(m => ({ default: m.DevWorkspace })));
const SocialPage     = lazy(() => import("../../features/social").then(m => ({ default: m.SocialPage })));
const SettingsPage   = lazy(() => import("../../features/settings").then(m => ({ default: m.SettingsPage })));
const DesignStudio   = lazy(() => import("../../features/design-studio").then(m => ({ default: m.DesignStudio })));
const AutomationPage = lazy(() => import("../../features/automation/AutomationPage").then(m => ({ default: m.AutomationPage })));
const AgentOSPage      = lazy(() => import("../../features/agentos").then(m => ({ default: m.AgentOSPage })));
const MarketplacePage  = lazy(() => import("../../features/marketplace").then(m => ({ default: m.MarketplacePage })));
const OrganizationsPage = lazy(() => import("../../features/organizations").then(m => ({ default: m.OrganizationsPage })));
const TeamsPage         = lazy(() => import("../../features/teams").then(m => ({ default: m.TeamsPage })));
const BillingPage       = lazy(() => import("../../features/billing").then(m => ({ default: m.BillingPage })));
const PluginsPage       = lazy(() => import("../../features/plugins").then(m => ({ default: m.PluginsPage })));
const SandboxPage       = lazy(() => import("../../features/sandbox").then(m => ({ default: m.SandboxPage })));
const AIRoutingPage     = lazy(() => import("../../features/ai-routing").then(m => ({ default: m.AIRoutingPage })));
const ObservabilityPage = lazy(() => import("../../features/observability").then(m => ({ default: m.ObservabilityPage })));

const FALLBACK = <LoadingSpinner fullPage label="Loading workspace…" />;

function WorkspaceContent() {
  const { page } = useAppContext();
  return (
    // Keyed by page: an error on one page must never leak into the next
    // page's fallback UI. Without a key, ErrorBoundary is the same instance
    // across navigations and its `hasError` state only ever clears via the
    // manual Retry button — so a crash on "ai" would keep showing "Error in
    // ai" chrome after navigating away to "home".
    <ErrorBoundary key={page} name={page}>
      <Suspense fallback={FALLBACK}>
        <PageTransition pageKey={page}>
        {page === "home"       && <HomePage />}
        {page === "ai"         && <AIWorkspace />}
        {page === "dev"        && <DevWorkspace />}
        {page === "design"     && <DesignStudio />}
        {page === "automation" && <AutomationPage />}
        {page === "agentos"    && <AgentOSPage />}
        {page === "marketplace" && <MarketplacePage />}
        {page === "organizations" && <OrganizationsPage />}
        {page === "teams"       && <TeamsPage />}
        {page === "billing"     && <BillingPage />}
        {page === "plugins"     && <PluginsPage />}
        {page === "sandbox"     && <SandboxPage />}
        {page === "ai-routing"  && <AIRoutingPage />}
        {page === "observability" && <ObservabilityPage />}
        {page === "social"     && <SocialPage />}
        {page === "settings"   && <SettingsPage />}
        </PageTransition>
      </Suspense>
    </ErrorBoundary>
  );
}

export function AppLayout() {
  const { setPage, isPageTransitioning } = useAppContext();
  const [mobileOpen, setMobileOpen]   = useState(false);
  const [cmdOpen,    setCmdOpen]       = useState(false);
  const closeMobile = useCallback(() => setMobileOpen(false), []);

  // Global Ctrl+K / Cmd+K opens command palette
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
      {/* Skip-to-content for keyboard/screen-reader users */}
      <a href="#main-content" className="skip-link">Skip to main content</a>

      {/* Mobile hamburger */}
      <button
        className="mobile-menu-btn"
        onClick={() => setMobileOpen(v => !v)}
        aria-label="Open navigation menu"
        aria-expanded={mobileOpen}
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M3 12h18M3 6h18M3 18h18"/>
        </svg>
      </button>

      <div className="app-layout">
        <Sidebar mobileOpen={mobileOpen} onMobileClose={closeMobile} />
        <main id="main-content" className="app-main">
          {/* Only visible while a not-yet-cached page's chunk is loading —
              near-instant (no visible flash) once every route has been
              visited once in this session. */}
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
    </>
  );
}
