import { lazy, Suspense, useState, useCallback, useEffect } from "react";
import { useAppContext } from "../../contexts/AppContext";
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

const FALLBACK = <LoadingSpinner fullPage label="Loading workspace…" />;

function WorkspaceContent() {
  const { page } = useAppContext();
  return (
    <ErrorBoundary name={page}>
      <Suspense fallback={FALLBACK}>
        {page === "home"       && <HomePage />}
        {page === "ai"         && <AIWorkspace />}
        {page === "dev"        && <DevWorkspace />}
        {page === "design"     && <DesignStudio />}
        {page === "automation" && <AutomationPage />}
        {page === "social"     && <SocialPage />}
        {page === "settings"   && <SettingsPage />}
      </Suspense>
    </ErrorBoundary>
  );
}

export function AppLayout() {
  const { setPage } = useAppContext();
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
