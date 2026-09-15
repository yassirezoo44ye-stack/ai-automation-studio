// App context + hook — split from AppContext.tsx so that file exports
// only its component (react-refresh/only-export-components).
import { createContext, useContext } from "react";
import type { Page } from "../types";

export type Theme = "dark" | "light" | "high-contrast";

/**
 * Intent carried from the Feed to a target builder page.
 * Set by FeedCard on CTA press; consumed once on mount by the target page.
 */
export interface FeedIntent {
  /** ID of the source item (template id, creation id, etc.) */
  sourceId?: string;
  /** How the item originated — used by target pages to know how to load it */
  sourceType?: "creation" | "template" | "listing" | "slug";
  /** Additional context for the target page (e.g. { prompt, title }) */
  sourceMeta?: Record<string, unknown>;
  /** Original feed item id for tracking */
  originItemId: string;
}

export interface AppContextType {
  page: Page;
  setPage: (p: Page) => void;
  /** True while a page switch that suspended on an uncached lazy chunk is still resolving. */
  isPageTransitioning: boolean;
  sidebarCollapsed: boolean;
  setSidebarCollapsed: (v: boolean | ((p: boolean) => boolean)) => void;
  theme: Theme;
  setTheme: (t: Theme) => void;
  toggleTheme: () => void;
  /** Intent from the Feed — set before navigation, consumed once by the target page. */
  feedIntent: FeedIntent | null;
  setFeedIntent: (intent: FeedIntent | null) => void;
}

export const AppContext = createContext<AppContextType>({
  page: "home",
  setPage: () => {},
  isPageTransitioning: false,
  sidebarCollapsed: false,
  setSidebarCollapsed: () => {},
  theme: "dark",
  setTheme: () => {},
  toggleTheme: () => {},
  feedIntent: null,
  setFeedIntent: () => {},
});

export function useAppContext() { return useContext(AppContext); }
