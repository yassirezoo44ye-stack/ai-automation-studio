import { lazy, Suspense } from "react";
import { useTranslation } from "react-i18next";
import { useCopilot } from "../../../contexts/copilot";

// Loaded on first open: the panel pulls in react-markdown (~39 KB gzipped),
// which the landing page and every first paint used to download up front.
const CopilotPanel = lazy(() => import("./CopilotPanel").then(m => ({ default: m.CopilotPanel })));

/** Persistent floating action button — mounted once in AppLayout, available on every page. */
export function CopilotButton() {
  const { open, setOpen } = useCopilot();
  const { t } = useTranslation("common");

  return (
    <div className="g-copilot-fab-wrap">
      {open && <Suspense fallback={null}><CopilotPanel /></Suspense>}
      <button
        type="button"
        className="g-copilot-fab"
        onClick={() => setOpen(!open)}
        aria-label={open ? t("copilot.close") : t("copilot.open")}
        aria-expanded={open}
        aria-haspopup="dialog"
        title={t("copilot.title")}
      >
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M12 2a5 5 0 0 1 5 5v2a5 5 0 0 1-10 0V7a5 5 0 0 1 5-5z"/>
          <path d="M2 20c0-3 3.5-5 10-5s10 2 10 5"/>
        </svg>
      </button>
    </div>
  );
}
