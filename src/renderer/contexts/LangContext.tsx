import { useState, useEffect, useCallback } from "react";
import i18n from "../i18n";
import { LangContext, type Lang } from "./lang";

function getStoredLang(): Lang {
  try {
    const stored = localStorage.getItem("axon-lang");
    if (stored === "en" || stored === "ar") return stored;
    if (navigator.language?.toLowerCase().startsWith("ar")) return "ar";
  } catch {
    // localStorage unavailable (e.g. private browsing with storage blocked)
  }
  return "en";
}

function applyLang(l: Lang) {
  document.documentElement.lang = l;
  document.documentElement.dir = l === "ar" ? "rtl" : "ltr";
  try { localStorage.setItem("axon-lang", l); } catch { /* ignore */ }
  void i18n.changeLanguage(l);
}

export function LangProvider({ children }: { children: React.ReactNode }) {
  const [lang, setLangState] = useState<Lang>(() => {
    const l = getStoredLang();
    applyLang(l);
    return l;
  });

  useEffect(() => { applyLang(lang); }, [lang]);

  const setLang = useCallback((l: Lang) => setLangState(l), []);
  const toggleLang = useCallback(() => setLangState(prev => prev === "en" ? "ar" : "en"), []);

  return (
    <LangContext.Provider value={{ lang, setLang, toggleLang }}>
      {children}
    </LangContext.Provider>
  );
}
