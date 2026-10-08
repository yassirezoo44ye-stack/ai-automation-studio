import { useState, useEffect, useCallback, useTransition } from "react";
import type { Page } from "../types";
import { AppContext, type Theme, type FeedIntent, type ProjectWorkspace } from "./app";

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

/** /project/:id/:workspace → Page */
const WORKSPACE_TO_PAGE: Record<ProjectWorkspace, Page> = {
  build:        "app-builder",
  design:       "design",
  automation:   "automation",
  runs:         "runs",
  integrations: "integrations",
};

/** Page → workspace segment (only for project-scoped pages) */
const PAGE_TO_WORKSPACE: Partial<Record<Page, ProjectWorkspace>> = {
  "app-builder": "build",
  design:        "design",
  automation:    "automation",
  runs:          "runs",
  integrations:  "integrations",
};

type ParsedRoute = { page: Page; projectId: string | null };

function parseCurrentPath(): ParsedRoute {
  const path = window.location.pathname;
  // /project/:projectId/:workspace
  const m = path.match(/^\/project\/([^/]+)\/([^/]+)/);
  if (m) {
    const projectId = m[1];
    const workspaceSegment = m[2] as ProjectWorkspace;
    const page = WORKSPACE_TO_PAGE[workspaceSegment];
    if (page) {
      // Keep projectId as-is — backend validates ownership; never silently remap to Demo.
      return { page, projectId };
    }
    // Unknown workspace segment — fall through to flat-path resolution with no projectId.
  }
  // Strip /feed/:id suffix — feed page handles its own ID state
  const base = path.startsWith("/feed/") ? "/feed" : path;
  return { page: PATH_TO_PAGE[base] ?? "app-builder", projectId: null };
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
  const [initialRoute] = useState<ParsedRoute>(parseCurrentPath);
  const [page, setPageState] = useState<Page>(initialRoute.page);
  const [activeProjectId, setActiveProjectId] = useState<string | null>(initialRoute.projectId);

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

  /** Navigate to /project/:projectId/:workspace — URL is the source of truth. */
  const setActiveProject = useCallback((projectId: string, workspace: ProjectWorkspace = "build") => {
    const newPage = WORKSPACE_TO_PAGE[workspace];
    setActiveProjectId(projectId);
    startPageTransition(() => setPageState(newPage));
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

  // Keep the URL bar in sync with page + activeProjectId.
  // /project/:id/:workspace when on a project-scoped page with an active project;
  // flat path otherwise. replaceState — no history entry per page click.
  useEffect(() => {
    const workspace = PAGE_TO_WORKSPACE[page];
    const path = workspace && activeProjectId
      ? `/project/${activeProjectId}/${workspace}`
      : PAGE_TO_PATH[page] ?? "/";
    if (window.location.pathname !== path) {
      window.history.replaceState(null, "", path);
    }
  }, [page, activeProjectId]);

  const setTheme = useCallback((t: Theme) => setThemeState(t), []);
  const toggleTheme = useCallback(() => setThemeState(prev => prev === "dark" ? "light" : "dark"), []);

  return (
    <AppContext.Provider value={{ page, setPage, isPageTransitioning, sidebarCollapsed, setSidebarCollapsed, theme, setTheme, toggleTheme, feedIntent, setFeedIntent, activeProjectId, setActiveProject }}>
      {children}
    </AppContext.Provider>
  );
}
