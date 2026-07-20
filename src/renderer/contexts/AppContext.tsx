import { useState, useEffect, useCallback, useTransition } from "react";
import type { Page } from "../types";
import { AppContext, type Theme } from "./app";

function getStoredTheme(): Theme {
  try {
    const stored = localStorage.getItem("axon-theme");
    if (stored === "light" || stored === "dark" || stored === "high-contrast") return stored;
    // Respect OS preference on first visit — high-contrast is opt-in only
    // via Settings (see SettingsPage's THEME_OPTIONS), never auto-detected,
    // since prefers-contrast support/semantics vary too much across
    // browsers to safely auto-switch a whole theme on it.
    if (window.matchMedia?.("(prefers-color-scheme: light)").matches) return "light";
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
  const [page, setPageState] = useState<Page>("home");
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
  const [theme, setThemeState] = useState<Theme>(() => {
    const t = getStoredTheme();
    applyTheme(t);
    return t;
  });

  // Sync theme attribute whenever it changes
  useEffect(() => { applyTheme(theme); }, [theme]);

  const setTheme = useCallback((t: Theme) => setThemeState(t), []);
  const toggleTheme = useCallback(() => setThemeState(prev => prev === "dark" ? "light" : "dark"), []);

  return (
    <AppContext.Provider value={{ page, setPage, isPageTransitioning, sidebarCollapsed, setSidebarCollapsed, theme, setTheme, toggleTheme }}>
      {children}
    </AppContext.Provider>
  );
}
