// App context + hook — split from AppContext.tsx so that file exports
// only its component (react-refresh/only-export-components).
import { createContext, useContext } from "react";
import type { Page } from "../types";

export type Theme = "dark" | "light";

export interface AppContextType {
  page: Page;
  setPage: (p: Page) => void;
  sidebarCollapsed: boolean;
  setSidebarCollapsed: (v: boolean | ((p: boolean) => boolean)) => void;
  theme: Theme;
  setTheme: (t: Theme) => void;
  toggleTheme: () => void;
}

export const AppContext = createContext<AppContextType>({
  page: "home",
  setPage: () => {},
  sidebarCollapsed: false,
  setSidebarCollapsed: () => {},
  theme: "dark",
  setTheme: () => {},
  toggleTheme: () => {},
});

export function useAppContext() { return useContext(AppContext); }
