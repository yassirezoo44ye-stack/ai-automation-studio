import { useCopilot } from "../../../contexts/copilot";
import { CopilotPanel } from "./CopilotPanel";

/** Persistent floating action button — mounted once in AppLayout, available on every page. */
export function CopilotButton() {
  const { open, setOpen } = useCopilot();

  return (
    <div className="g-copilot-fab-wrap">
      {open && <CopilotPanel />}
      <button
        type="button"
        className="g-copilot-fab"
        onClick={() => setOpen(!open)}
        aria-label={open ? "Close AI Copilot" : "Open AI Copilot"}
        aria-expanded={open}
        aria-haspopup="dialog"
        title="AI Copilot"
      >
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M12 2a5 5 0 0 1 5 5v2a5 5 0 0 1-10 0V7a5 5 0 0 1 5-5z"/>
          <path d="M2 20c0-3 3.5-5 10-5s10 2 10 5"/>
        </svg>
      </button>
    </div>
  );
}
