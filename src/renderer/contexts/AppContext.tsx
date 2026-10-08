import { useState, useEffect, useCallback, useTransition } from "react";
import type { Page } from "../types";
import { AppContext, type Theme, type FeedIntent } from "./app";

const PATH_TO_PAGE: Record<string, Page> = {
  "/":              "app-builder",
  "/home":          "home",
  "/ai":            "ai",
  "/dev":           "dev",
  "/design":        "design",
  "/automation":    "automation",
  "/social":        "social",
  "/settings":      "settings",
  "/agentos":       "agentos",
  "/marketplace":   "marketplace",
  "/organizations": "organizations",
  "/teams":         "teams",
  "/billing":       "billing",
  "/plugins":       "plugins",
  "/sandbox":       "sandbox",
  "/ai-routing":    "ai-routing",
  "/observability": "observability",
  "/app-builder":   "app-builder",
  "/runs":          "runs",
  "/integrations":  "integrations",
  "/training":      "training",
  "/business-lab":  "business-lab",
  "/devices":       "devices",
  "/discover":      "discover",
  "/feed":          "feed",
  "/leads":         "leads",
  "/saas-factory":  "saas-factory",
  "/new-project":   "new-project",
};

const PAGE_TO_PATH: Partial<Record<Page, string>> = Object.fromEntries(
  Object.entries(PATH_TO_PAGE).map(([path, page]) => [page, path]),
) as Partial<Record<Page, string>>;

function pageFromCurrentPath(): Page {
  const path = window.location.pathname;
  // Strip /feed/:id suffix — feed page handles its own ID state
  const base = path.startsWith("/feed/") ? "/feed" : path;
  return PATH_TO_PAGE[base] ?? "app-builder";
}

function getStoredTheme(): Theme {
  try {
    const stored = localStorage.getItem("axon-theme");
    if (stored === "light" || stored === "dark" || stored === "high-contrast") return stored;
    // FLOW is dark-first: new visitors always start in dark mode.
    // Light mode is available via Settings — this is not a regression,
    // it is the intentional FLOW visual identity decision.
    // (High-contrast remains opt-in only, never auto-detected.)
  } catch {
    // localStorage unavailable (e.g. private browsing with storage blocked)
  }
  return "dark";
}

function applyTheme(t: Theme) {
  document.documentElement.setAttribute("data-theme", t);
  try { localStorage.setItem("axon-theme", t); } catch { /* ignore */ }
}

export function AppProvider({ children }: { children: React.ReactNode }) {
  const [page, setPageState] = useState<Page>(() => pageFromCurrentPath());
  // Page switches run as a transition so a lazy chunk that hasn't loaded yet
  // never interrupts an in-flight commit: React keeps the current page fully
  // rendered and interactive until the new one is ready, then swaps both the
  // page value and the rendered tree together in one commit. Previously a
  // plain setState here could suspend mid-render on an uncached route,
  // aborting the commit AnimatePresence relies on to track its children —
  // leaving the sidebar's active item pointing at a page whose content
  // never actually finished mounting.
  const [isPageTransitioning, startPageTransition] = useTransition();
  const setPage = useCallback((p: Page) => {
    startPageTransition(() => setPageState(p));
  }, []);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [feedIntent, setFeedIntentState] = useState<FeedIntent | null>(null);
  const setFeedIntent = useCallback((intent: FeedIntent | null) => setFeedIntentState(intent), []);
  const [theme, setThemeState] = useState<Theme>(() => {
    const t = getStoredTheme();
    applyTheme(t);
    return t;
  });

  // Sync theme attribute whenever it changes
  useEffect(() => { applyTheme(theme); }, [theme]);

  // Keep the URL bar in sync with page state so refreshing / sharing a link
  // opens the same page (deep-link fix). replaceState — no history entry per
  // page click; the app's sidebar is the navigation, not the browser back button.
  useEffect(() => {
    const path = PAGE_TO_PATH[page] ?? "/";
    if (window.location.pathname !== path) {
      window.history.replaceState(null, "", path);
    }
  }, [page]);

  const setTheme = useCallback((t: Theme) => setThemeState(t), []);
  const toggleTheme = useCallback(() => setThemeState(prev => prev === "dark" ? "light" : "dark"), []);

  return (
    <AppContext.Provider value={{ page, setPage, isPageTransitioning, sidebarCollapsed, setSidebarCollapsed, theme, setTheme, toggleTheme, feedIntent, setFeedIntent }}>
      {children}
    </AppContext.Provider>
  );
}
