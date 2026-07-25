// Lang context + hook — split from LangContext.tsx so that file exports
// only its component (react-refresh/only-export-components).
import { createContext, useContext } from "react";

export type Lang = "en" | "ar";

export interface LangContextType {
  lang: Lang;
  setLang: (l: Lang) => void;
  toggleLang: () => void;
}

export const LangContext = createContext<LangContextType>({
  lang: "en",
  setLang: () => {},
  toggleLang: () => {},
});

export function useLangContext() { return useContext(LangContext); }
