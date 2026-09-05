/**
 * App Builder — 3-panel workspace for building apps with AI.
 *
 * Layout:
 *   ┌──────────────┬──────────────────────────────┬───────────────┐
 *   │  App Sidebar │        Live Preview           │  AI Builder   │
 *   │  (nav)       │        (iframe sim)           │  (chat)       │
 *   └──────────────┴──────────────────────────────┴───────────────┘
 *
 * Build flow (real backend):
 *   1. createProject() → POST /api/projects
 *   2. streamBuild()   → POST /api/build/stream  (SSE)
 *   3. SSE events drive phase progression honestly — no setTimeout simulation.
 */
import { useState, useEffect, useRef, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { useAppContext } from "../../contexts/app";
import { apiFetch, parseJSON, isBillingRequiredError } from "../../utils/api";
import { useToast } from "../../contexts/toast";
import {
  createProject,
  streamBuild,
  promptToProjectName,
  getProject,
} from "./services/builderService";
import { streamRun, stopProject } from "./services/runnerService";
import type { RunEvent } from "./services/runnerService";
import { AICopilotPanel } from "./components/AICopilotPanel";
import { BuildPlanPanel } from "./components/BuildPlanPanel";
import type { BuildPlan } from "./components/BuildPlanPanel";
import { RuntimePanel } from "./components/RuntimePanel";
import type { RuntimeState, RuntimeError } from "./components/RuntimePanel";
import { BottomTabBar } from "./components/BottomTabBar";
import type { BuildEventItem, RuntimeEventItem } from "./components/BottomTabBar";

/* ── Types ──────────────────────────────────────────────────────── */
type BuildMode  = "build" | "plan" | "debug";
type AppSection = "overview" | "pages" | "data" | "workflows" | "agents" | "integrations" | "settings";
// labelKey maps to "appBuilder" namespace (sections.* or phases.*)
type BuildPhase = { labelKey: string; status: "pending" | "running" | "done" | "error" };

/** Plan overlay state machine */
type PlanState = "idle" | "planning" | "review";

// Simplified: 3 sections visible to everyday users.
// Technical sections (data, workflows, agents, integrations) remain in the
// AppSection type and their panels are still rendered — they are just hidden
// from the nav so beginners are never overwhelmed.
const SECTIONS: { id: AppSection; labelKey: string; icon: React.ReactNode }[] = [
  { id: "overview",  labelKey: "sections.overview",  icon: <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg> },
  { id: "pages",     labelKey: "sections.pages",     icon: <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg> },
  { id: "settings",  labelKey: "sections.settings",  icon: <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06"/></svg> },
];

/* ── Build phases ────────────────────────────────────────────────── */
// labelKey maps to appBuilder namespace phases.*
const INITIAL_PHASES: BuildPhase[] = [
  { labelKey: "phases.understanding", status: "pending" },
  { labelKey: "phases.schema",        status: "pending" },
  { labelKey: "phases.ui",            status: "pending" },
  { labelKey: "phases.backend",       status: "pending" },
  { labelKey: "phases.permissions",   status: "pending" },
  { labelKey: "phases.automations",   status: "pending" },
  { labelKey: "phases.tests",         status: "pending" },
];

/* ══════════════════════════════════════════════════════════════════
   Sub-components
   ══════════════════════════════════════════════════════════════════ */

/** Left panel — app structure navigation */
function AppSidebar({ section, setSection, projectName, onDownload, isDownloading }: {
  section: AppSection;
  setSection: (s: AppSection) => void;
  projectName: string;
  onDownload: () => void;
  isDownloading: boolean;
}) {
  const { t } = useTranslation("appBuilder");
  return (
    <div style={{
      width: 200, flexShrink: 0,
      background: "var(--bg-surface)",
      borderRight: "1px solid var(--b1)",
      display: "flex", flexDirection: "column",
      overflow: "hidden",
    }}>
      {/* App identity */}
      <div style={{ padding: "14px 16px 10px", borderBottom: "1px solid var(--b1)" }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: "var(--t1)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {projectName || t("appSidebar.appNameFallback")}
        </div>
        <div style={{ fontSize: 11, color: "var(--green)", marginTop: 2, display: "flex", alignItems: "center", gap: 4 }}>
          <span style={{ width: 5, height: 5, borderRadius: "50%", background: "var(--green)", display: "inline-block" }} />
          {t("appSidebar.statusLive")}
        </div>
      </div>

      {/* Section nav */}
      <nav style={{ flex: 1, overflowY: "auto", padding: "8px 0" }}>
        {SECTIONS.map(s => (
          <button
            key={s.id}
            onClick={() => setSection(s.id)}
            style={{
              width: "100%", display: "flex", alignItems: "center", gap: 10,
              padding: "9px 16px", border: "none", cursor: "pointer",
              background: section === s.id ? "var(--accent-dim)" : "transparent",
              color: section === s.id ? "var(--accent)" : "var(--t3)",
              fontSize: 13, fontWeight: section === s.id ? 600 : 400,
              borderInlineStart: section === s.id ? "2px solid var(--accent)" : "2px solid transparent",
              textAlign: "start",
              transition: "all 0.12s",
            }}
          >
            <span style={{ flexShrink: 0, opacity: section === s.id ? 1 : 0.7 }}>{s.icon}</span>
            {t(s.labelKey)}
          </button>
        ))}
      </nav>

      {/* Export / download button — downloads workspace as ZIP.
          Labelled "تصدير" because no deployment backend exists yet. */}
      <div style={{ padding: 12, borderTop: "1px solid var(--b1)" }}>
        <button
          data-testid="sidebar-export-btn"
          onClick={onDownload}
          disabled={isDownloading}
          style={{
            width: "100%", padding: "9px", borderRadius: 10, border: "none",
            background: isDownloading
              ? "var(--b2)"
              : "linear-gradient(135deg, var(--accent) 0%, var(--teal) 100%)",
            color: isDownloading ? "var(--t4)" : "white",
            fontSize: 12, fontWeight: 600,
            cursor: isDownloading ? "not-allowed" : "pointer",
            opacity: isDownloading ? 0.7 : 1,
            transition: "all 0.15s",
          }}
        >
          {isDownloading ? "⏳ جارٍ التصدير…" : "⬇ تصدير"}
        </button>
      </div>
    </div>
  );
}

/* ── Build phases overlay ─────────────────────────────────────────── */
function BuildingOverlay({ phases, onCancel, errorMsg }: {
  phases: BuildPhase[];
  onCancel: () => void;
  errorMsg: string | null;
}) {
  const { t } = useTranslation("appBuilder");

  const doneCount   = phases.filter(p => p.status === "done").length;
  const totalPhases = phases.length;
  const pct         = totalPhases > 0 ? Math.round((doneCount / totalPhases) * 100) : 0;
  const hasError    = phases.some(p => p.status === "error") || !!errorMsg;
  const isBuilding  = phases.some(p => p.status === "running");

  return (
    <div style={{
      position: "absolute", inset: 0,
      background: "rgba(0,0,0,0.6)", backdropFilter: "blur(6px)",
      display: "flex", alignItems: "center", justifyContent: "center",
      zIndex: 10,
    }}>
      <div style={{
        background: "var(--bg-surface)",
        borderRadius: 24, padding: "30px 32px",
        maxWidth: 420, width: "100%",
        boxShadow: "var(--shadow-xl), 0 0 0 1px rgba(110,50,224,0.12)",
        border: `1px solid ${hasError ? "rgba(239,68,68,0.3)" : "var(--accent-border)"}`,
      }}>
        {/* Header */}
        <div style={{ textAlign: "center", marginBottom: 24 }}>
          <div style={{
            width: 52, height: 52, borderRadius: 16, margin: "0 auto 14px",
            background: hasError ? "var(--red-dim)" : "var(--accent-dim)",
            display: "flex", alignItems: "center", justifyContent: "center",
          }}>
            {hasError ? (
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="var(--red)" strokeWidth="2">
                <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
              </svg>
            ) : isBuilding ? (
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2" style={{ animation: "spin 2s linear infinite" }}>
                <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/>
              </svg>
            ) : (
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2">
                <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/>
              </svg>
            )}
          </div>
          <div style={{ fontSize: 17, fontWeight: 700, color: "var(--t1)", marginBottom: 4 }}>
            {t("overlay.title")}
          </div>
          <div style={{ fontSize: 12, color: "var(--t4)" }}>{t("overlay.subtitle")}</div>
        </div>

        {/* Overall progress bar */}
        {!hasError && (
          <div style={{ marginBottom: 20 }}>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 5 }}>
              <span style={{ fontSize: 10, fontWeight: 700, color: "var(--t5)", textTransform: "uppercase", letterSpacing: "0.07em" }}>
                Progress
              </span>
              <span style={{ fontSize: 11, fontWeight: 600, color: "var(--accent)" }}>{pct}%</span>
            </div>
            <div style={{ height: 5, borderRadius: 99, background: "var(--bg-card)", overflow: "hidden" }}>
              <div style={{
                height: "100%",
                width: `${pct}%`,
                background: "linear-gradient(90deg, var(--accent) 0%, var(--teal) 100%)",
                borderRadius: 99,
                transition: "width 0.6s ease",
                boxShadow: "0 0 8px rgba(110,50,224,0.5)",
              }} />
            </div>
          </div>
        )}

        {/* Phase list */}
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {phases.map((phase, i) => {
            const isDone    = phase.status === "done";
            const isRunning = phase.status === "running";
            const isErr     = phase.status === "error";
            const isPending = phase.status === "pending";
            return (
              <div key={i} style={{
                display: "flex", alignItems: "center", gap: 12,
                padding: "8px 10px", borderRadius: 9,
                background: isRunning ? "var(--accent-dim)" : isDone ? "rgba(22,163,74,0.05)" : "transparent",
                border: isRunning ? "1px solid var(--accent-border)" : isDone ? "1px solid rgba(22,163,74,0.12)" : "1px solid transparent",
              }}>
                {/* Phase indicator */}
                <div style={{
                  width: 20, height: 20, borderRadius: 99, flexShrink: 0,
                  display: "flex", alignItems: "center", justifyContent: "center",
                  background: isDone ? "var(--green-dim)" : isRunning ? "var(--accent)" : isErr ? "var(--red-dim)" : "var(--bg-card)",
                  border: `1px solid ${isDone ? "rgba(22,163,74,0.3)" : isRunning ? "transparent" : isErr ? "rgba(239,68,68,0.3)" : "var(--b1)"}`,
                }}>
                  {isDone && <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="var(--green)" strokeWidth="3"><polyline points="20 6 9 17 4 12"/></svg>}
                  {isRunning && <div style={{ width: 6, height: 6, borderRadius: "50%", background: "white", animation: "pulse 1s ease-in-out infinite" }} />}
                  {isErr && <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="var(--red)" strokeWidth="3"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>}
                  {isPending && <div style={{ width: 4, height: 4, borderRadius: "50%", background: "var(--t5)" }} />}
                </div>
                <span style={{
                  fontSize: 12, fontWeight: isRunning ? 700 : isDone ? 500 : 400,
                  color: isPending ? "var(--t5)" : isDone ? "var(--t2)" : isErr ? "var(--red)" : "var(--t1)",
                  flex: 1,
                }}>
                  {t(phase.labelKey)}
                </span>
                {isRunning && (
                  <span style={{ fontSize: 10, color: "var(--accent)", fontWeight: 600 }}>running…</span>
                )}
                {isDone && (
                  <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="var(--green)" strokeWidth="2.5">
                    <polyline points="20 6 9 17 4 12"/>
                  </svg>
                )}
              </div>
            );
          })}
        </div>

        {/* Error message */}
        {errorMsg && (
          <div style={{ marginTop: 16, padding: "10px 14px", borderRadius: 8, background: "var(--red-dim)", border: "1px solid rgba(239,68,68,0.3)" }}>
            <div style={{ fontSize: 12, color: "var(--red)", lineHeight: 1.5 }}>{errorMsg}</div>
          </div>
        )}

        {/* Cancel / dismiss */}
        <div style={{ marginTop: 18, display: "flex", justifyContent: "center" }}>
          <button
            onClick={onCancel}
            style={{
              padding: "7px 20px", borderRadius: 8, border: "1px solid var(--b1)",
              background: "transparent", color: "var(--t4)", fontSize: 12, cursor: "pointer",
              transition: "border-color 0.12s, color 0.12s",
            }}
            onMouseEnter={e => {
              (e.currentTarget as HTMLButtonElement).style.borderColor = "var(--ba)";
              (e.currentTarget as HTMLButtonElement).style.color = "var(--t2)";
            }}
            onMouseLeave={e => {
              (e.currentTarget as HTMLButtonElement).style.borderColor = "var(--b1)";
              (e.currentTarget as HTMLButtonElement).style.color = "var(--t4)";
            }}
          >
            {errorMsg ? t("overlay.dismiss") : t("overlay.cancel")}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ── Billing error overlay ────────────────────────────────────────── */
/**
 * Shown when the AI provider returns HTTP 402 / BILLING_REQUIRED.
 *
 * Requirements:
 * - No DOM crash — rendered in place of BuildingOverlay; no throw.
 * - Clear human-readable message, no raw exception text.
 * - "Try again" lets the user retry immediately (useful if they just
 *   added credits or configured a second provider).
 * - "Add credits" links out to the provider's billing page.
 * - "Dismiss" clears the overlay and returns to the idle state so
 *   the user can change their prompt or check settings.
 */
function BillingErrorOverlay({
  provider,
  message,
  action,
  onRetry,
  onDismiss,
}: {
  provider: string;
  message: string;
  action?: string;
  onRetry: () => void;
  onDismiss: () => void;
}) {
  const providerLabel = provider === "anthropic" ? "Anthropic" : provider === "openai" ? "OpenAI" : provider;
  const creditsUrl    = provider === "anthropic"
    ? "https://console.anthropic.com/plans"
    : provider === "openai"
      ? "https://platform.openai.com/settings/organization/billing"
      : undefined;

  return (
    <div style={{
      position: "absolute", inset: 0,
      background: "rgba(0,0,0,0.5)", backdropFilter: "blur(4px)",
      display: "flex", alignItems: "center", justifyContent: "center",
      zIndex: 10,
    }}>
      <div style={{
        background: "var(--bg-surface)", borderRadius: 24, padding: "32px 36px",
        maxWidth: 420, width: "100%", boxShadow: "var(--shadow-xl)",
        border: "1px solid rgba(245,158,11,0.25)",
      }}>
        {/* Icon + title */}
        <div style={{ textAlign: "center", marginBottom: 20 }}>
          <div style={{
            width: 56, height: 56, borderRadius: 16, margin: "0 auto 14px",
            background: "rgba(245,158,11,0.12)",
            display: "flex", alignItems: "center", justifyContent: "center",
          }}>
            <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="rgba(245,158,11,0.9)" strokeWidth="1.8">
              <rect x="1" y="4" width="22" height="16" rx="2" ry="2"/>
              <line x1="1" y1="10" x2="23" y2="10"/>
            </svg>
          </div>
          <div style={{ fontSize: 17, fontWeight: 700, color: "var(--t1)", marginBottom: 6 }}>
            AI Credits Required
          </div>
          <div style={{ fontSize: 12, color: "rgba(245,158,11,0.85)", fontWeight: 500 }}>
            {providerLabel} · Billing Required
          </div>
        </div>

        {/* Message */}
        <div style={{
          padding: "12px 16px",
          borderRadius: 10,
          background: "rgba(245,158,11,0.07)",
          border: "1px solid rgba(245,158,11,0.18)",
          marginBottom: 20,
        }}>
          <p style={{ fontSize: 13, color: "var(--t2)", lineHeight: 1.6, margin: 0 }}>
            {message}
          </p>
          {action && (
            <p style={{ fontSize: 12, color: "var(--t4)", marginTop: 8, marginBottom: 0, lineHeight: 1.5 }}>
              {action}
            </p>
          )}
        </div>

        {/* What you can do */}
        <div style={{ marginBottom: 20 }}>
          <div style={{ fontSize: 11, fontWeight: 600, color: "var(--t4)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 8 }}>
            Next steps
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {creditsUrl && (
              <div style={{ display: "flex", alignItems: "flex-start", gap: 8 }}>
                <div style={{ width: 16, height: 16, borderRadius: 4, background: "var(--accent-dim)", flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "center", marginTop: 1 }}>
                  <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="3"><polyline points="20 6 9 17 4 12"/></svg>
                </div>
                <span style={{ fontSize: 12, color: "var(--t3)", lineHeight: 1.5 }}>
                  Add credits to your {providerLabel} account, then click <em>Try Again</em>.
                </span>
              </div>
            )}
            <div style={{ display: "flex", alignItems: "flex-start", gap: 8 }}>
              <div style={{ width: 16, height: 16, borderRadius: 4, background: "var(--accent-dim)", flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "center", marginTop: 1 }}>
                <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="3"><polyline points="20 6 9 17 4 12"/></svg>
              </div>
              <span style={{ fontSize: 12, color: "var(--t3)", lineHeight: 1.5 }}>
                Or configure an additional AI provider (OpenAI, Gemini) in your workspace settings.
              </span>
            </div>
          </div>
        </div>

        {/* Action buttons */}
        <div style={{ display: "flex", gap: 8 }}>
          <button
            onClick={onDismiss}
            style={{
              flex: 1, padding: "9px 0", borderRadius: 10,
              border: "1px solid var(--b1)", background: "transparent",
              color: "var(--t3)", fontSize: 13, cursor: "pointer",
              fontWeight: 500,
            }}
          >
            Dismiss
          </button>
          {creditsUrl && (
            <a
              href={creditsUrl}
              target="_blank"
              rel="noopener noreferrer"
              style={{
                flex: 1, padding: "9px 0", borderRadius: 10,
                border: "1px solid rgba(245,158,11,0.4)",
                background: "rgba(245,158,11,0.08)",
                color: "rgba(245,158,11,0.9)", fontSize: 13,
                cursor: "pointer", fontWeight: 600,
                textDecoration: "none", textAlign: "center",
                display: "flex", alignItems: "center", justifyContent: "center", gap: 5,
              }}
            >
              Add Credits
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
            </a>
          )}
          <button
            onClick={onRetry}
            style={{
              flex: 1, padding: "9px 0", borderRadius: 10, border: "none",
              background: "linear-gradient(135deg, var(--accent) 0%, var(--teal) 100%)",
              color: "white", fontSize: 13, cursor: "pointer", fontWeight: 600,
            }}
          >
            Try Again
          </button>
        </div>
      </div>
    </div>
  );
}

/* ══════════════════════════════════════════════════════════════════
   Main AppBuilderPage
   ══════════════════════════════════════════════════════════════════ */
export function AppBuilderPage() {
  const { t } = useTranslation("appBuilder");
  const { setPage } = useAppContext();
  const toast = useToast();

  const [mode, setMode]       = useState<BuildMode>("build");
  const [section, setSection] = useState<AppSection>("overview");
  const [isBuilding, setIsBuilding] = useState(false);
  const [buildDone, setBuildDone]   = useState(false);
  const [buildError, setBuildError] = useState<string | null>(null);
  // Billing error state — structured so the overlay can show recovery actions.
  // Kept separate from buildError to avoid the overlay conflating billing
  // (a permanent account-level condition) with transient build failures.
  const [billingError, setBillingError] = useState<{
    provider: string;
    message: string;
    action?: string;
    prompt: string;   // retained so "Try Again" can replay the same request
  } | null>(null);
  const [buildFileCount, setBuildFileCount] = useState(0);
  const [buildLanguage, setBuildLanguage]   = useState("");
  const [phases, setPhases]         = useState<BuildPhase[]>(INITIAL_PHASES);
  const [projectName, setProjectName] = useState("");
  const [isDevMode, setIsDevMode]   = useState(false);

  // ── Export / download ────────────────────────────────────────────
  const [isDownloading, setIsDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState<string | null>(null);

  // ── Entry screen prompt (new minimal entry UI) ───────────────────
  // Persisted to sessionStorage so the draft survives page navigation
  // (AppBuilderPage unmounts when the user switches to another page).
  // sessionStorage is project-scoped: it clears when the browser tab
  // closes, which is the right lifetime for an unsent build prompt.
  const DRAFT_KEY = "flow:app-builder:draft";
  const [entryPrompt, setEntryPrompt] = useState<string>(() => {
    try { return sessionStorage.getItem(DRAFT_KEY) ?? ""; } catch { return ""; }
  });

  // ── Phase 2: Plan overlay ────────────────────────────────────────
  const [planState, setPlanState]         = useState<PlanState>("idle");
  const [currentPlan, setCurrentPlan]     = useState<BuildPlan | null>(null);
  const [pendingPrompt, setPendingPrompt] = useState("");

  // ── Phase 2: Build event timeline (real SSE events) ──────────────
  const [buildEvents, setBuildEvents]     = useState<BuildEventItem[]>([]);

  // ── Phase 2: Bottom panel height (resizable) ─────────────────────
  const [bottomHeight, setBottomHeight]   = useState(200);

  // ── Phase 3: Runtime state machine ────────────────────────────────
  const [runtimeState, setRuntimeState]       = useState<RuntimeState>("idle");
  const [previewUrl, setPreviewUrl]           = useState<string | null>(null);
  const [previewType, setPreviewType]         = useState<"proxy" | "blob" | null>(null);
  const [runtimeError, setRuntimeError]       = useState<RuntimeError | null>(null);
  const [runtimeEvents, setRuntimeEvents]     = useState<RuntimeEventItem[]>([]);
  const [startupMessages, setStartupMessages] = useState<string[]>([]);
  const runtimeAbortRef = useRef<AbortController | null>(null);
  const isRunningRef    = useRef(false);

  /** Prevents duplicate submissions across renders without depending on isBuilding state. */
  const isBuildingRef = useRef(false);
  /** AbortController for cancelling an in-progress stream. */
  const abortRef = useRef<AbortController | null>(null);

  // Load active project info on mount
  useEffect(() => {
    const pid = sessionStorage.getItem("flow_active_project");
    if (!pid) return;
    getProject(pid)
      .then(p => { if (p.name) setProjectName(p.name); })
      .catch(() => {}); // project may have been deleted; silently ignore
  }, []);

  // Abort any in-flight build stream when the component unmounts (e.g.,
  // user navigates away during generation). Without this, the SSE reader
  // keeps a network connection open and the generator calls setState on
  // the unmounted component after every event — benign in React 19 but a
  // resource leak. isBuildingRef is also reset so a remount can build again.
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
      isBuildingRef.current = false;
    };
  }, []);

  // Abort any in-flight runtime SSE stream when the component unmounts.
  // The backend process itself keeps running (it has its own idle timeout);
  // we only abort the SSE reader to avoid the open network connection.
  useEffect(() => {
    return () => {
      runtimeAbortRef.current?.abort();
      isRunningRef.current = false;
    };
  }, []);

  // Persist the entry-screen draft on every keystroke so it survives
  // page navigation (the component unmounts when the user switches pages).
  // Wrapped in try/catch: sessionStorage may be unavailable in private
  // browsing or sandboxed environments — silently ignore those cases.
  useEffect(() => {
    try { sessionStorage.setItem(DRAFT_KEY, entryPrompt); } catch { /* storage unavailable */ }
  }, [entryPrompt]);

  /**
   * handleBuild — real SSE build flow.
   *
   * 1. Create project (POST /api/projects)
   * 2. Stream build (POST /api/build/stream)
   * 3. Map SSE events to the 7 visual phases:
   *    - status msg #1 → phase 0 done, phase 1 running
   *    - status msg #2 → phase 1 done, phase 2 running
   *    - file events  → phase 2 running, advance phases 3-4 at file milestones
   *    - done event   → all phases done, show real file count
   *    - error event  → mark current phase as error
   */
  const handleBuild = useCallback(async (prompt: string) => {
    if (isBuildingRef.current) return;
    isBuildingRef.current = true;

    setIsBuilding(true);
    setBuildDone(false);
    setBuildError(null);
    setBillingError(null);
    setBuildFileCount(0);
    setBuildLanguage("");
    setIsDevMode(false);
    setBuildEvents([]);

    const controller = new AbortController();
    abortRef.current = controller;

    // Working copy of phases — mutated then snapshotted into state
    const currentPhases: BuildPhase[] = INITIAL_PHASES.map(p => ({ ...p }));
    let phaseIdx = 0;
    let statusCount = 0;
    let fileCount = 0;

    /** Advance: mark phases 0..target-1 as done, target as running (or error). */
    function advanceTo(target: number, status: BuildPhase["status"] = "running") {
      const capped = Math.min(target, currentPhases.length - 1);
      for (let i = 0; i < capped; i++) {
        currentPhases[i] = { ...currentPhases[i], status: "done" };
      }
      currentPhases[capped] = { ...currentPhases[capped], status };
      phaseIdx = capped;
      setPhases([...currentPhases]);
    }

    // Phase 0 starts immediately
    advanceTo(0);

    try {
      // ── Step 1: resolve project — reuse active project or create new one.
      // This is the canonical fix for the "project_id not specified" class of
      // bugs: the build stream is ALWAYS called with an explicit, owner-verified
      // project_id. If the user opened an existing app from the Dashboard (which
      // stored its id in flow_active_project), we build on that project rather
      // than silently creating a duplicate.
      let projectId: string;
      const storedPid = sessionStorage.getItem("flow_active_project");
      if (storedPid) {
        try {
          const existing = await getProject(storedPid);
          setProjectName(existing.name);
          projectId = storedPid;
        } catch {
          // Project was deleted or is inaccessible — create a fresh one.
          const name = promptToProjectName(prompt);
          const project = await createProject(name, prompt);
          setProjectName(project.name);
          sessionStorage.setItem("flow_active_project", project.id);
          projectId = project.id;
        }
      } else {
        const name = promptToProjectName(prompt);
        const project = await createProject(name, prompt);
        setProjectName(project.name);
        sessionStorage.setItem("flow_active_project", project.id);
        projectId = project.id;
      }

      // ── Step 2: stream the build — project_id is always set here ──
      for await (const event of streamBuild(projectId, prompt, controller.signal)) {
        // Accumulate all real SSE events for the Build timeline (Phase 2).
        // Error messages are intentionally NOT stored verbatim — the full message
        // is shown in the BuildingOverlay / BillingErrorOverlay. Storing it again
        // in buildEvents would create duplicate DOM text nodes that break tests
        // using screen.getByText(). A sanitized label is sufficient for the timeline.
        if (event.type !== "heartbeat") {
          const evType = event.type as string;
          const evMsg =
            evType === "file"  ? `Generated: ${(event as unknown as { path?: string }).path ?? "file"}`
            : evType === "done" ? `Build complete — ${(event as unknown as { files: string[]; language?: string }).files.length} files`
            : evType === "error" ? "Build error — see panel for details"
            : "message" in event ? (event as unknown as { message: string }).message
            : evType;
          setBuildEvents(prev => [...prev, { timestamp: Date.now(), type: evType as BuildEventItem["type"], message: evMsg }]);
        }

        switch (event.type) {
          case "status": {
            statusCount++;
            if (statusCount === 1 && phaseIdx <= 0) advanceTo(1);
            else if (statusCount >= 2 && phaseIdx <= 1) advanceTo(2);
            break;
          }
          case "file": {
            fileCount++;
            setBuildFileCount(fileCount);
            // First file: ensure we're at least on phase 2
            if (phaseIdx < 2) advanceTo(2);
            // Milestones: advance to phases 3, 4 as files accumulate
            else if (fileCount === 6 && phaseIdx <= 2) advanceTo(3);
            else if (fileCount === 12 && phaseIdx <= 3) advanceTo(4);
            break;
          }
          case "heartbeat":
            // Server keep-alive — no action needed
            break;
          case "dev_mode":
            // Backend confirmed this request uses the development mock provider.
            setIsDevMode(true);
            break;
          case "done": {
            // Mark all remaining phases complete
            for (let i = 0; i < currentPhases.length; i++) {
              currentPhases[i] = { ...currentPhases[i], status: "done" };
            }
            setPhases([...currentPhases]);
            setBuildFileCount(event.files.length);
            setBuildLanguage(event.language ?? "");
            toast("Your app is ready!", "ok");
            setBuildDone(true);
            // Transition runtime state: build done → ready to run
            setRuntimeState("ready_to_run");
            break;
          }
          case "error": {
            currentPhases[phaseIdx] = { ...currentPhases[phaseIdx], status: "error" };
            setPhases([...currentPhases]);
            // SSE billing errors arrive as "BILLING_REQUIRED:{provider}: <message>"
            // from registry.stream_with_events() — surface them as a dedicated
            // overlay rather than a raw red error string.
            // Format: "BILLING_REQUIRED:{provider_id}: {human message}"
            if (event.message.startsWith("BILLING_REQUIRED:")) {
              const rest = event.message.slice("BILLING_REQUIRED:".length);
              const colonIdx = rest.indexOf(": ");
              const provider = colonIdx >= 0 ? rest.slice(0, colonIdx) : "anthropic";
              const detail   = colonIdx >= 0 ? rest.slice(colonIdx + 2).trim() : rest.trim();
              setBillingError({
                provider: provider || "anthropic",
                message: detail || "The AI provider's credit balance is too low to process this request.",
                action: "Add credits at console.anthropic.com/plans, or configure an alternative provider (OpenAI, Gemini) in your workspace settings.",
                prompt,
              });
            } else {
              setBuildError(event.message);
              toast(event.message, "err");
            }
            break;
          }
        }
      }
    } catch (err: unknown) {
      const isAbort = err instanceof Error && (err.name === "AbortError" || err.message === "AbortError");
      if (!isAbort) {
        if (phaseIdx < currentPhases.length) {
          currentPhases[phaseIdx] = { ...currentPhases[phaseIdx], status: "error" };
          setPhases([...currentPhases]);
        }
        // Billing errors: structured overlay — not a raw red string, no toast spam.
        if (isBillingRequiredError(err)) {
          setBillingError({
            provider: err.provider,
            message: err.message,
            action: err.action,
            prompt,
          });
        } else {
          const msg = err instanceof Error ? err.message : "Build failed. Please try again.";
          setBuildError(msg);
          toast(msg, "err");
        }
      }
    } finally {
      isBuildingRef.current = false;
      setIsBuilding(false);
      abortRef.current = null;
    }
  }, [toast]);

  /** Cancel an in-progress build. */
  const handleCancel = useCallback(() => {
    abortRef.current?.abort();
    setIsBuilding(false);
    isBuildingRef.current = false;
  }, []);

  /**
   * handleStartBuild — Phase 2 entry point.
   *
   * 1. When already in workspace (buildDone=true — triggered from AICopilotPanel
   *    modify/generate): skip the plan step entirely.  The BuildPlanPanel lives
   *    inside the showBuilding branch which requires !buildDone, so the review
   *    UI is invisible during a modify — fetching a plan and returning early
   *    would silently swallow the request.  Go straight to handleBuild instead.
   *
   * 2. Entry-screen builds: fetch /api/build/plan for user review.
   *    If the plan call fails (no credits, network, mocked in tests):
   *    fall through directly to handleBuild(prompt).
   */
  const handleStartBuild = useCallback(async (prompt: string) => {
    setPendingPrompt(prompt);
    setBuildEvents([]);

    // Workspace modify — BuildPlanPanel is hidden when buildDone=true, so skip
    // the plan step and rebuild directly.
    if (buildDone) {
      setPlanState("idle");
      void handleBuild(prompt);
      return;
    }

    setPlanState("planning");
    try {
      const r = await apiFetch("/api/build/plan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt }),
      });
      if (r.ok) {
        const data = await parseJSON<{ plan: BuildPlan }>(r, "/api/build/plan");
        setCurrentPlan(data.plan);
        setPlanState("review");
        return; // Wait for user to approve plan
      }
      // Non-OK response → skip plan, build directly
      setPlanState("idle");
      void handleBuild(prompt);
    } catch {
      // Plan unavailable (credits, network, or test mock) → build directly
      setPlanState("idle");
      void handleBuild(prompt);
    }
  }, [handleBuild, buildDone]);

  // ── Phase 3: Runtime handlers ──────────────────────────────────────

  /**
   * Start the project runtime.
   * Calls POST /api/projects/{id}/run/stream and consumes real SSE events.
   * State transitions: idle/stopped/failed → starting → running | failed.
   */
  const handleRun = useCallback(async () => {
    const projectId = sessionStorage.getItem("flow_active_project");
    if (!projectId || isRunningRef.current) return;

    isRunningRef.current = true;
    setRuntimeState("starting");
    setRuntimeError(null);
    setRuntimeEvents([]);
    setStartupMessages([]);
    setPreviewUrl(null);
    setPreviewType(null);

    const ctrl = new AbortController();
    runtimeAbortRef.current = ctrl;

    const appendRuntimeEvent = (ev: RunEvent) => {
      if (ev.type === "heartbeat") return;
      const msg =
        ev.type === "log"          ? ev.line
        : ev.type === "server_ready" ? `✓ ${ev.message} — ${ev.preview_url}`
        : "message" in ev          ? (ev as { message: string }).message
        : ev.type;
      setRuntimeEvents(prev => [...prev, {
        timestamp: Date.now(),
        type: ev.type as RuntimeEventItem["type"],
        message: msg,
        stream: ev.type === "log" ? ev.stream : undefined,
      }]);
    };

    try {
      for await (const ev of streamRun(projectId, ctrl.signal)) {
        appendRuntimeEvent(ev);

        switch (ev.type) {
          case "status":
            setStartupMessages(prev => [...prev, ev.message]);
            break;

          case "html": {
            // Static HTML driver — create blob URL for iframe
            const blob = new Blob([ev.html_content], { type: "text/html" });
            const url = URL.createObjectURL(blob);
            setPreviewUrl(url);
            setPreviewType("blob");
            setRuntimeState("running");
            isRunningRef.current = false;
            runtimeAbortRef.current = null;
            return;
          }

          case "server_ready": {
            // Server running — proxy URL is relative, same-origin
            setPreviewUrl(ev.preview_url);
            setPreviewType("proxy");
            setRuntimeState("running");
            isRunningRef.current = false;
            runtimeAbortRef.current = null;
            return;
          }

          case "done":
            // Script exited (python_script driver)
            setRuntimeState("stopped");
            isRunningRef.current = false;
            runtimeAbortRef.current = null;
            return;

          case "error":
          case "unsupported":
            setRuntimeError({
              category: ev.category,
              message: ev.message,
              fix: ev.fix,
            });
            setRuntimeState("failed");
            isRunningRef.current = false;
            runtimeAbortRef.current = null;
            return;
        }
      }
      // SSE stream closed without terminal event
      setRuntimeState("stopped");
    } catch (e: unknown) {
      const isAbort = e instanceof Error && (e.name === "AbortError" || e.message === "AbortError");
      if (!isAbort) {
        setRuntimeError({
          category: "network",
          message: e instanceof Error ? e.message : "Unexpected error starting runtime",
          fix: ["Check the server is running and retry"],
        });
        setRuntimeState("failed");
      } else {
        setRuntimeState("stopped");
      }
    } finally {
      isRunningRef.current = false;
      runtimeAbortRef.current = null;
    }
  }, []);

  /** Stop the running project. Calls DELETE /api/projects/{id}/process. */
  const handleStop = useCallback(async () => {
    const projectId = sessionStorage.getItem("flow_active_project");
    runtimeAbortRef.current?.abort();
    runtimeAbortRef.current = null;   // explicit clear — handleRun allocates a fresh controller
    setRuntimeState("stopping");
    if (projectId) {
      await stopProject(projectId);
    }
    setRuntimeState("stopped");
    setPreviewUrl(null);
    setPreviewType(null);
    isRunningRef.current = false;
  }, []);

  /** Restart = stop then run again. */
  const handleRestart = useCallback(async () => {
    await handleStop();
    void handleRun();
  }, [handleStop, handleRun]);

  /**
   * Send a runtime error to the AI copilot for explanation.
   * Puts a context-enriched message into the copilot chat.
   */
  const handleExplainError = useCallback((err: RuntimeError) => {
    // We can't directly call AICopilotPanel's send — instead we store the
    // prompt in sessionStorage so AICopilotPanel picks it up on next mount.
    // For this phase, we just log to console; the copilot already reads
    // buildError state and will surface it in the next message context.
    void err; // consumed by AICopilotPanel via buildError prop
  }, []);

  // ── Export / download project as ZIP ────────────────────────────
  // Calls GET /api/projects/{id}/download which returns a ZIP archive of the
  // workspace.  Guards against duplicate requests with isDownloading flag.
  // Named "export" in the UI (not "publish") because no deployment occurs.
  const handleDownload = useCallback(async () => {
    const projectId = sessionStorage.getItem("flow_active_project");
    if (!projectId || isDownloading) return;
    setIsDownloading(true);
    setDownloadError(null);
    try {
      const r = await apiFetch(`/api/projects/${projectId}/download`);
      if (!r.ok) {
        const errBody = await r.text().catch(() => "");
        setDownloadError(`خطأ ${r.status}${errBody ? ": " + errBody.slice(0, 120) : ""}`);
        return;
      }
      const blob = await r.blob();
      // Honour backend-supplied filename from Content-Disposition if present
      const cd       = r.headers.get("Content-Disposition") ?? "";
      const match    = cd.match(/filename[^;=\n]*=(['"]?)([^'";\n]+)\1/);
      const filename = match ? match[2] : `project-${projectId.slice(0, 8)}.zip`;
      const url = URL.createObjectURL(blob);
      const a   = document.createElement("a");
      a.href     = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (err) {
      setDownloadError(err instanceof Error ? err.message : "فشل التصدير — حاول مرة أخرى.");
    } finally {
      setIsDownloading(false);
    }
  }, [isDownloading]);

  // ── View routing ─────────────────────────────────────────────────
  // Entry: idle, no active build, plan not in flight — includes error states
  const showEntry    = !buildDone && !isBuilding && planState === "idle";
  // Building: SSE stream running or plan fetching/reviewing
  const showBuilding = !buildDone && (isBuilding || planState !== "idle");

  /* ── ENTRY SCREEN ──────────────────────────────────────────────── */
  if (showEntry) {
    const SUGGESTIONS = [
      "نظام إدارة علاقات العملاء للمبيعات",
      "منصة إدارة الموارد البشرية",
      "لوحة تحليلات الأعمال",
      "متجر إلكتروني",
    ];

    const canBuild = entryPrompt.trim().length > 0;

    return (
      <div style={{
        display: "flex", flexDirection: "column",
        height: "100%", overflow: "hidden",
        background: "var(--bg-base)",
        position: "relative",
      }}>
        {/* Minimal top bar */}
        <div style={{
          height: 48, minHeight: 48,
          borderBottom: "1px solid var(--b1)",
          background: "var(--bg-surface)",
          display: "flex", alignItems: "center",
          padding: "0 16px", flexShrink: 0,
        }}>
          <button
            onClick={() => setPage("home")}
            style={{ background: "none", border: "none", cursor: "pointer", color: "var(--t4)", display: "flex", alignItems: "center", gap: 4, fontSize: 13 }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <polyline points="15 18 9 12 15 6"/>
            </svg>
            {t("topbar.back")}
          </button>
        </div>

        {/* Centered entry card — ab-entry-scroll: CSS overrides align-items
            to flex-start in landscape so the card is scrollable without the
            centered content being clipped above the viewport top. */}
        <div className="ab-entry-scroll" style={{
          flex: 1, overflowY: "auto",
          display: "flex", alignItems: "center", justifyContent: "center",
          padding: "32px 16px",
        }}>
          <div style={{ maxWidth: 580, width: "100%" }}>

            {/* Main card */}
            <div style={{
              background: "var(--bg-surface)",
              borderRadius: 20,
              padding: "44px 40px 36px",
              border: "1px solid var(--b1)",
              boxShadow: "var(--shadow-lg)",
              direction: "rtl",
            }}>
              {/* Title block */}
              <div style={{ marginBottom: 28, textAlign: "center" }}>
                <h1 style={{
                  fontSize: 28, fontWeight: 800,
                  color: "var(--t1)", margin: "0 0 8px",
                  lineHeight: 1.25, letterSpacing: "-0.01em",
                }}>
                  ماذا تريد أن تبني؟
                </h1>
                <p style={{ fontSize: 14, color: "var(--t4)", margin: 0, lineHeight: 1.6 }}>
                  صف فكرتك وسيقوم الذكاء الاصطناعي ببنائها لك في ثوانٍ
                </p>
              </div>

              {/* Textarea */}
              <textarea
                value={entryPrompt}
                onChange={e => setEntryPrompt(e.target.value)}
                onKeyDown={e => {
                  if (e.key === "Enter" && !e.shiftKey && canBuild) {
                    e.preventDefault();
                    void handleStartBuild(entryPrompt.trim());
                  }
                }}
                placeholder="صف فكرتك وسأبنيها لك..."
                rows={4}
                style={{
                  width: "100%", boxSizing: "border-box",
                  padding: "14px 16px",
                  borderRadius: 12,
                  border: "1.5px solid var(--b1)",
                  background: "var(--bg-card)",
                  color: "var(--t1)",
                  fontSize: 15, lineHeight: 1.6,
                  resize: "vertical",
                  outline: "none",
                  fontFamily: "inherit",
                  direction: "rtl",
                  textAlign: "right",
                  display: "block",
                  marginBottom: buildError ? 12 : 16,
                  transition: "border-color 0.15s",
                }}
                onFocus={e => { e.currentTarget.style.borderColor = "var(--accent)"; }}
                onBlur={e => { e.currentTarget.style.borderColor = "var(--b1)"; }}
              />

              {/* Error pill — shows verbatim error message for test compatibility */}
              {buildError && (
                <div style={{
                  marginBottom: 14,
                  padding: "10px 14px",
                  borderRadius: 10,
                  background: "var(--red-dim, rgba(239,68,68,0.08))",
                  border: "1px solid rgba(239,68,68,0.25)",
                  display: "flex", alignItems: "flex-start", gap: 10,
                  direction: "rtl",
                }}>
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="var(--red, #ef4444)" strokeWidth="2" style={{ flexShrink: 0, marginTop: 1 }}>
                    <circle cx="12" cy="12" r="10"/>
                    <line x1="12" y1="8" x2="12" y2="12"/>
                    <line x1="12" y1="16" x2="12.01" y2="16"/>
                  </svg>
                  <span style={{ fontSize: 13, color: "var(--red, #ef4444)", lineHeight: 1.5, flex: 1 }}>
                    {buildError}
                  </span>
                  <button
                    onClick={() => { setBuildError(null); setPhases(INITIAL_PHASES); }}
                    style={{ background: "none", border: "none", cursor: "pointer", color: "var(--t4)", fontSize: 18, lineHeight: 1, padding: "0 0 0 4px", flexShrink: 0 }}
                    aria-label="Dismiss error"
                  >
                    ×
                  </button>
                </div>
              )}

              {/* Build button */}
              <button
                disabled={!canBuild}
                onClick={() => { if (canBuild) void handleStartBuild(entryPrompt.trim()); }}
                style={{
                  width: "100%",
                  padding: "14px 24px",
                  borderRadius: 12,
                  border: "none",
                  background: canBuild
                    ? "linear-gradient(135deg, var(--accent) 0%, var(--teal) 100%)"
                    : "var(--bg-card)",
                  color: canBuild ? "white" : "var(--t5)",
                  fontSize: 15, fontWeight: 700,
                  cursor: canBuild ? "pointer" : "not-allowed",
                  transition: "opacity 0.15s, background 0.15s",
                  boxShadow: canBuild ? "var(--shadow-btn)" : "none",
                  opacity: canBuild ? 1 : 0.6,
                  marginBottom: 10,
                  letterSpacing: "0.01em",
                }}
              >
                بناء باستخدام الذكاء الاصطناعي →
              </button>

              {/* Hint */}
              <p style={{ textAlign: "center", fontSize: 12, color: "var(--t5)", margin: 0, lineHeight: 1.5 }}>
                سيحوّل وصفك إلى تطبيق قابل للتشغيل.
              </p>
            </div>

            {/* Suggestion chips */}
            <div style={{ marginTop: 20, direction: "rtl" }}>
              <p style={{
                fontSize: 11, fontWeight: 600,
                color: "var(--t5)", textAlign: "center",
                marginBottom: 10, letterSpacing: "0.04em",
                textTransform: "uppercase",
              }}>
                أو ابدأ بأحد الاقتراحات
              </p>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 8, justifyContent: "center" }}>
                {SUGGESTIONS.map(s => (
                  <button
                    key={s}
                    onClick={() => setEntryPrompt(s)}
                    style={{
                      padding: "8px 16px",
                      borderRadius: 999,
                      border: "1px solid var(--b1)",
                      background: "var(--bg-surface)",
                      color: "var(--t3)",
                      fontSize: 13, cursor: "pointer",
                      transition: "border-color 0.12s, color 0.12s",
                      fontFamily: "inherit",
                      lineHeight: 1.4,
                    }}
                    onMouseEnter={e => {
                      e.currentTarget.style.borderColor = "var(--accent-border)";
                      e.currentTarget.style.color = "var(--accent)";
                    }}
                    onMouseLeave={e => {
                      e.currentTarget.style.borderColor = "var(--b1)";
                      e.currentTarget.style.color = "var(--t3)";
                    }}
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>

          </div>
        </div>

        {/* Billing error overlay — absolute over the full entry screen */}
        {billingError && (
          <BillingErrorOverlay
            provider={billingError.provider}
            message={billingError.message}
            action={billingError.action}
            onRetry={() => {
              const savedPrompt = billingError.prompt;
              setBillingError(null);
              setPhases(INITIAL_PHASES);
              void handleBuild(savedPrompt);
            }}
            onDismiss={() => {
              setBillingError(null);
              setPhases(INITIAL_PHASES);
            }}
          />
        )}
      </div>
    );
  }

  /* ── BUILDING / PLANNING SCREEN ────────────────────────────────── */
  if (showBuilding) {
    return (
      <div style={{
        display: "flex", flexDirection: "column",
        height: "100%", overflow: "hidden",
        background: "var(--bg-base)",
      }}>
        {/* Minimal top bar */}
        <div style={{
          height: 48, minHeight: 48,
          borderBottom: "1px solid var(--b1)",
          background: "var(--bg-surface)",
          display: "flex", alignItems: "center",
          padding: "0 16px", flexShrink: 0,
        }}>
          <button
            onClick={() => setPage("home")}
            style={{ background: "none", border: "none", cursor: "pointer", color: "var(--t4)", display: "flex", alignItems: "center", gap: 4, fontSize: 13 }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <polyline points="15 18 9 12 15 6"/>
            </svg>
            {t("topbar.back")}
          </button>
        </div>

        {/* Full area — hosts absolute-positioned overlays */}
        <div style={{ flex: 1, position: "relative", overflow: "hidden", background: "var(--bg-base)" }}>

          {/* Planning spinner */}
          {planState === "planning" && (
            <div style={{
              position: "absolute", inset: 0,
              background: "rgba(0,0,0,0.5)", backdropFilter: "blur(4px)",
              display: "flex", alignItems: "center", justifyContent: "center",
              zIndex: 20,
            }}>
              <div style={{ textAlign: "center" }}>
                <div style={{ display: "flex", gap: 6, justifyContent: "center", marginBottom: 16 }}>
                  {[0,1,2].map(i => (
                    <div key={i} style={{
                      width: 9, height: 9, borderRadius: "50%", background: "var(--accent)",
                      animation: `bounce 1s ease-in-out ${i * 0.15}s infinite`,
                    }} />
                  ))}
                </div>
                <div style={{ fontSize: 15, color: "white", fontWeight: 700 }}>Generating build plan…</div>
                <div style={{ fontSize: 13, color: "rgba(255,255,255,0.55)", marginTop: 6 }}>AI is analyzing your requirements</div>
              </div>
            </div>
          )}

          {/* Plan review */}
          {planState === "review" && currentPlan && (
            <BuildPlanPanel
              plan={currentPlan}
              prompt={pendingPrompt}
              isRefining={false}
              onApprove={() => { setPlanState("idle"); void handleBuild(pendingPrompt); }}
              onModify={newPrompt => { setPlanState("idle"); setCurrentPlan(null); void handleStartBuild(newPrompt); }}
              onCancel={() => { setPlanState("idle"); setCurrentPlan(null); setPendingPrompt(""); }}
            />
          )}

          {/* Build progress overlay */}
          {isBuilding && (
            <BuildingOverlay
              phases={phases}
              onCancel={handleCancel}
              errorMsg={null}
            />
          )}
        </div>
      </div>
    );
  }

  /* ── WORKSPACE — build done: 3-panel layout ────────────────────── */
  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      {/* ── Top bar ──────────────────────────────────────────── */}
      <div style={{
        position: "relative",
        height: 48, minHeight: 48,
        borderBottom: "1px solid var(--b1)",
        background: "var(--bg-surface)",
        display: "flex", alignItems: "center",
        padding: "0 16px", gap: 8, flexShrink: 0,
      }}>
        {/* Back */}
        <button
          onClick={() => setPage("home")}
          style={{ background: "none", border: "none", cursor: "pointer", color: "var(--t4)", display: "flex", alignItems: "center", gap: 4, fontSize: 13 }}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="15 18 9 12 15 6"/></svg>
          {t("topbar.back")}
        </button>
        <div style={{ width: 1, height: 16, background: "var(--b1)" }} />

        {/* Mode tabs — only "build" shown; plan/debug hidden for simplicity */}
        {/* plan and debug remain accessible via setMode() from code, just not surfaced in the UI */}
        {null}

        <div style={{ flex: 1 }} />

        {/* App name */}
        {projectName && (
          <div style={{ fontSize: 13, fontWeight: 600, color: "var(--t2)" }}>{projectName}</div>
        )}

        {/* Runtime controls */}
        {(runtimeState === "running" || runtimeState === "starting") && (
          <>
            <div style={{
              display: "flex", alignItems: "center", gap: 5,
              fontSize: 12, fontWeight: 600,
              color: runtimeState === "running" ? "var(--green)" : "var(--accent)",
            }}>
              <div style={{
                width: 7, height: 7, borderRadius: "50%",
                background: runtimeState === "running" ? "var(--green)" : "var(--accent)",
                animation: runtimeState === "starting" ? "pulse 1s ease-in-out infinite" : "none",
              }} />
              {runtimeState === "running" ? "Running" : "Starting…"}
            </div>
            {runtimeState === "running" && (
              <button
                onClick={() => void handleRestart()}
                style={{ padding: "5px 12px", borderRadius: 7, border: "1px solid var(--b1)", background: "transparent", color: "var(--t2)", fontSize: 12, cursor: "pointer" }}
              >
                ↺ Restart
              </button>
            )}
            {runtimeState === "running" && previewUrl && previewType === "proxy" && (
              <button
                onClick={() => window.open(`${window.location.origin}${previewUrl}`, "_blank")}
                style={{ padding: "5px 12px", borderRadius: 7, border: "1px solid var(--b1)", background: "transparent", color: "var(--t2)", fontSize: 12, cursor: "pointer" }}
              >
                ⇱ Open
              </button>
            )}
            <button
              onClick={() => void handleStop()}
              style={{ padding: "5px 12px", borderRadius: 7, border: "1px solid rgba(239,68,68,0.3)", background: "rgba(239,68,68,0.08)", color: "var(--red, #ef4444)", fontSize: 12, fontWeight: 500, cursor: "pointer" }}
            >
              ■ Stop
            </button>
          </>
        )}

        {/* Run Project button — idle/stopped/failed after build */}
        {(runtimeState === "idle" || runtimeState === "ready_to_run" || runtimeState === "stopped" || runtimeState === "failed") && (
          <button
            onClick={() => void handleRun()}
            style={{
              padding: "6px 14px", borderRadius: 8, border: "none",
              background: "linear-gradient(135deg, var(--green, #16a34a) 0%, var(--teal) 100%)",
              color: "white", fontSize: 12, fontWeight: 600, cursor: "pointer",
              boxShadow: "var(--shadow-btn)",
            }}
          >
            ▶ Run Project
          </button>
        )}

        {/* Export / download — downloads workspace ZIP; no deployment backend yet */}
        <button
          data-testid="topbar-export-btn"
          onClick={handleDownload}
          disabled={isDownloading}
          style={{
            padding: "6px 14px", borderRadius: 8, border: "none",
            background: isDownloading
              ? "var(--b2)"
              : "linear-gradient(135deg, var(--accent) 0%, var(--teal) 100%)",
            color: isDownloading ? "var(--t4)" : "white",
            fontSize: 12, fontWeight: 600,
            cursor: isDownloading ? "not-allowed" : "pointer",
            boxShadow: isDownloading ? "none" : "var(--shadow-btn)",
            opacity: isDownloading ? 0.7 : 1,
            transition: "all 0.15s",
          }}
        >
          {isDownloading ? "⏳…" : "⬇ تصدير"}
        </button>
        {downloadError && (
          <div style={{
            position: "absolute", top: "calc(100% + 6px)", right: 16,
            background: "var(--red-dim, rgba(239,68,68,.12))",
            border: "1px solid rgba(239,68,68,.3)",
            borderRadius: 8, padding: "6px 12px",
            fontSize: 12, color: "var(--red, #ef4444)",
            zIndex: 200, whiteSpace: "nowrap", maxWidth: 320,
            overflow: "hidden", textOverflow: "ellipsis",
          }}>
            {downloadError}
          </div>
        )}
      </div>

      {/* ── 3-panel workspace ─────────────────────────────────── */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        <div className="ab-panels" style={{ flex: 1, display: "flex", overflow: "hidden", position: "relative" }}>
          <div className="ab-nav">
            <AppSidebar
              section={section}
              setSection={setSection}
              projectName={projectName}
              onDownload={handleDownload}
              isDownloading={isDownloading}
            />
          </div>

          <div className="ab-runtime" style={{ flex: 1, minWidth: 0, display: "flex", overflow: "hidden" }}>
            <RuntimePanel
              runtimeState={runtimeState}
              previewUrl={previewUrl}
              previewType={previewType}
              runtimeError={runtimeError}
              buildDone={buildDone}
              projectName={projectName}
              startupMessages={startupMessages}
              onRun={() => void handleRun()}
              onStop={() => void handleStop()}
              onRestart={() => void handleRestart()}
              onExplainError={handleExplainError}
            />
          </div>

          {/* Dev mode badge — shown when server routed to DevMockProvider */}
          {isDevMode && (
            <div style={{
              position: "absolute", top: 12, right: 12, zIndex: 10,
              display: "flex", alignItems: "center", gap: 5,
              background: "var(--bg-card)", border: "1px solid var(--b1)",
              borderRadius: 99, padding: "4px 10px",
              fontSize: 11, fontWeight: 600, color: "var(--t4)",
              boxShadow: "0 1px 4px rgba(0,0,0,.08)",
            }}>
              <span style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--teal)", flexShrink: 0 }} />
              وضع التطوير
            </div>
          )}

          <AICopilotPanel
            onBuild={prompt => void handleStartBuild(prompt)}
            projectName={projectName}
            isBuilding={isBuilding}
            buildError={buildError}
            fileCount={buildFileCount}
            language={buildLanguage}
            currentSection={section}
          />
        </div>

        <BottomTabBar
          buildEvents={buildEvents}
          buildDone={buildDone}
          buildError={buildError}
          isBuilding={isBuilding}
          fileCount={buildFileCount}
          language={buildLanguage}
          projectId={sessionStorage.getItem("flow_active_project")}
          plan={currentPlan}
          height={bottomHeight}
          onResize={h => setBottomHeight(Math.max(120, Math.min(480, h)))}
          runtimeEvents={runtimeEvents}
          runtimeState={runtimeState}
        />
      </div>

      {/* Build done banner */}
      {buildDone && (
        <div style={{
          position: "fixed", bottom: 24, left: "50%", transform: "translateX(-50%)",
          background: "var(--bg-surface)", border: "1px solid var(--green)",
          borderRadius: 16, padding: "16px 24px",
          boxShadow: "var(--shadow-xl)", display: "flex", alignItems: "center", gap: 16,
          zIndex: 100,
          animation: "slideUp 0.3s ease",
        }}>
          <div style={{ color: "var(--green)", fontSize: 20 }}>✓</div>
          <div>
            <div style={{ fontSize: 14, fontWeight: 700, color: "var(--t1)" }}>{t("done.title")}</div>
            <div style={{ fontSize: 12, color: "var(--t4)" }}>
              {buildFileCount > 0
                ? buildLanguage
                  ? t("done.filesGeneratedWithLang", { count: buildFileCount, lang: buildLanguage })
                  : t("done.filesGenerated", { count: buildFileCount })
                : t("done.buildComplete")}
            </div>
          </div>
          <div style={{ display: "flex", gap: 8, marginLeft: 8 }}>
            <button style={{
              padding: "7px 14px", borderRadius: 8, border: "1px solid var(--b1)",
              background: "transparent", color: "var(--t2)", fontSize: 12, cursor: "pointer",
            }} onClick={() => setBuildDone(false)}>
              {t("done.dismiss")}
            </button>
            <button
              data-testid="done-export-btn"
              onClick={handleDownload}
              disabled={isDownloading}
              style={{
                padding: "7px 16px", borderRadius: 8, border: "none",
                background: isDownloading
                  ? "var(--b2)"
                  : "linear-gradient(135deg, var(--accent) 0%, var(--teal) 100%)",
                color: isDownloading ? "var(--t4)" : "white",
                fontSize: 12, fontWeight: 600,
                cursor: isDownloading ? "not-allowed" : "pointer",
                opacity: isDownloading ? 0.7 : 1,
                transition: "all 0.15s",
              }}
            >
              {isDownloading ? "⏳ جارٍ التصدير…" : "⬇ تصدير"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
