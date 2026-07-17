import { useState, useEffect, useCallback } from "react";
import type { Page } from "../types";
import { AppContext, type Theme } from "./app";

function getStoredTheme(): Theme {
  try {
    const stored = localStorage.getItem("axon-theme");
    if (stored === "light" || stored === "dark") return stored;
    // Respect OS preference on first visit
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
  const [page, setPage] = useState<Page>("home");
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
    <AppContext.Provider value={{ page, setPage, sidebarCollapsed, setSidebarCollapsed, theme, setTheme, toggleTheme }}>
      {children}
    </AppContext.Provider>
  );
}
