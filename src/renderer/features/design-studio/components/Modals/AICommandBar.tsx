/**
 * AICommandBar — "✦ Build with AI" modal inside Flow App Builder.
 *
 * Reuses the app-builder API (POST /api/app-builder/apps + polling)
 * without duplicating polling logic — the same createApp/getApp calls
 * from features/app-builder/api.ts are imported directly.
 *
 * On a successful build, `onAppReady(appId, canvasId)` is called so the
 * parent (DesignStudio) can open the generated canvas. The full build
 * history remains accessible via the App Builder page for power users.
 */
import { useState, useRef, useCallback, useEffect } from "react";
import * as appBuilderApi from "../../../app-builder/api";
import type { BuildStep, BuildPhase } from "../../../app-builder/types";
import { APIError } from "../../../../shared/utils/api";

const POLL_INTERVAL_MS = 2000;
const TERMINAL_STATUSES = new Set(["ready", "partial", "failed"]);

const EXAMPLES = [
  "AI customer support SaaS with tickets, agents and Stripe billing",
  "Project management tool with teams, tasks and Kanban board",
  "E-commerce dashboard with products, orders and analytics",
  "CRM with contacts, deals, pipeline and email integration",
];

interface Props {
  onClose: () => void;
  /** Called when build finishes with ready/partial status */
  onAppReady: (appId: string, canvasId: string | null) => void;
}

export function AICommandBar({ onClose, onAppReady }: Props) {
  const [prompt, setPrompt]         = useState("");
  const [phase, setPhase]           = useState<BuildPhase>("idle");
  const [progress, setProgress]     = useState(0);
  const [currentStep, setCurrentStep] = useState("initializing");
  const [steps, setSteps]           = useState<BuildStep[]>([]);
  const [errorMsg, setErrorMsg]     = useState<string | null>(null);

  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const pollRef     = useRef<ReturnType<typeof setInterval> | null>(null);
  const mountedRef  = useRef(true);

  // Focus textarea on mount; clean up on unmount
  useEffect(() => {
    textareaRef.current?.focus();
    return () => {
      mountedRef.current = false;
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  const stopPolling = () => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
  };

  const startPolling = useCallback((appId: string) => {
    stopPolling();
    pollRef.current = setInterval(async () => {
      try {
        const detail = await appBuilderApi.getApp(appId);
        if (!mountedRef.current) return;

        setProgress(detail.progress ?? 0);
        setCurrentStep(detail.current_step ?? "");

        // Extract step list from build_result if available
        const br = detail.build_result as Record<string, unknown> | null ?? {};
        const serverSteps = Array.isArray(br["steps"])
          ? (br["steps"] as BuildStep[])
          : [];
        if (serverSteps.length > 0) setSteps(serverSteps);

        if (TERMINAL_STATUSES.has(detail.build_status)) {
          stopPolling();
          if (detail.build_status === "ready" || detail.build_status === "partial") {
            setPhase("done");
            onAppReady(detail.id, detail.canvas_id);
          } else {
            setPhase("error");
            setErrorMsg(detail.error ?? "Build failed — please retry.");
          }
        }
      } catch (err) {
        if (!mountedRef.current) return;
        const status = err instanceof APIError ? err.details.status : 0;
        // Permanent client errors — stop polling and surface a message
        if (status === 401 || status === 403) {
          stopPolling();
          setPhase("error");
          setErrorMsg("Session error — please refresh and try again.");
        } else if (status === 402) {
          // Billing required — permanent, tell the user explicitly
          stopPolling();
          setPhase("error");
          setErrorMsg("Build limit reached. Upgrade your plan to continue building apps.");
        } else if (status === 404) {
          // App deleted while polling — reset silently
          stopPolling();
          setPhase("idle");
        }
        // 429 / 5xx / network errors are transient — keep retrying
      }
    }, POLL_INTERVAL_MS);
  }, [onAppReady]);

  const handleBuild = useCallback(async (includeAutomation = false) => {
    const p = prompt.trim();
    if (!p) return;
    setPhase("building");
    setProgress(0);
    setCurrentStep("initializing");
    setSteps([]);
    setErrorMsg(null);
    try {
      const resp = await appBuilderApi.createApp(p, includeAutomation);
      startPolling(resp.id);
    } catch (err) {
      const status = err instanceof APIError ? err.details.status : 0;
      setPhase("error");
      if (status === 402) {
        setErrorMsg("Build limit reached. Upgrade your plan to continue building apps.");
      } else {
        setErrorMsg("Could not start build. Check your connection and try again.");
      }
    }
  }, [prompt, startPolling]);

  // ── Render ──────────────────────────────────────────────────────────────────

  return (
    <>
      {/* Scrim */}
      <div
        aria-hidden="true"
        onClick={onClose}
        style={{
          position: "fixed", inset: 0,
          background: "rgba(0,0,0,0.45)",
          zIndex: 1000,
        }}
      />

      {/* Dialog */}
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Build with AI"
        style={{
          position: "fixed",
          top: "50%", left: "50%",
          transform: "translate(-50%,-50%)",
          width: 560, maxWidth: "calc(100vw - 40px)",
          background: "var(--surface-2)",
          border: "1px solid var(--border-strong)",
          borderRadius: 16,
          padding: "28px 32px",
          zIndex: 1001,
          boxShadow: "0 24px 64px rgba(0,0,0,0.22)",
          boxSizing: "border-box",
        }}
      >
        {/* Header row */}
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 20, gap: 16 }}>
          <div>
            <p style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.09em", color: "var(--text-accent)", margin: "0 0 4px" }}>
              ✦ Build with AI
            </p>
            <h2 style={{ fontSize: 18, fontWeight: 700, color: "var(--text-primary)", margin: 0, lineHeight: 1.25 }}>
              What do you want to build?
            </h2>
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            style={{
              width: 32, height: 32, flexShrink: 0,
              border: "1px solid var(--border)", borderRadius: "50%",
              background: "var(--surface-1)", color: "var(--text-secondary)",
              fontSize: 18, lineHeight: 1, cursor: "pointer",
              display: "flex", alignItems: "center", justifyContent: "center",
            }}
          >
            ×
          </button>
        </div>

        {/* ── IDLE / ERROR: prompt input ── */}
        {(phase === "idle" || phase === "error") && (
          <>
            <textarea
              ref={textareaRef}
              value={prompt}
              onChange={e => setPrompt(e.target.value)}
              onKeyDown={e => {
                if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
                  e.preventDefault();
                  void handleBuild();
                }
              }}
              placeholder="Build me an AI customer support SaaS with authentication, dashboard, tickets, AI agent and Stripe billing."
              rows={4}
              style={{
                width: "100%", padding: "12px 14px",
                border: "1px solid var(--border)", borderRadius: 10,
                background: "var(--surface-1)", color: "var(--text-primary)",
                fontSize: 14, lineHeight: 1.5, resize: "vertical",
                outline: "none", fontFamily: "inherit",
                boxSizing: "border-box", transition: "border-color 0.15s",
              }}
              onFocus={e  => { e.target.style.borderColor = "var(--border-accent)"; }}
              onBlur={e   => { e.target.style.borderColor = "var(--border)"; }}
            />

            {errorMsg && (
              <p style={{ fontSize: 13, color: "var(--text-danger)", margin: "8px 0 0" }}>
                ⚠ {errorMsg}
              </p>
            )}

            <div style={{ display: "flex", gap: 8, marginTop: 12, alignItems: "center", flexWrap: "wrap" }}>
              <button
                onClick={() => void handleBuild()}
                disabled={!prompt.trim()}
                style={{
                  padding: "10px 22px",
                  background: prompt.trim() ? "var(--fill-accent)" : "var(--surface-0)",
                  color: prompt.trim() ? "#fff" : "var(--text-muted)",
                  border: "none", borderRadius: 8,
                  fontSize: 14, fontWeight: 600,
                  cursor: prompt.trim() ? "pointer" : "not-allowed",
                  transition: "background 0.15s",
                }}
              >
                Build App
              </button>
              <button
                onClick={() => void handleBuild(true)}
                disabled={!prompt.trim()}
                style={{
                  padding: "10px 22px",
                  background: "transparent",
                  color: prompt.trim() ? "var(--text-accent)" : "var(--text-muted)",
                  border: `1.5px solid ${prompt.trim() ? "var(--border-accent)" : "var(--border)"}`,
                  borderRadius: 8,
                  fontSize: 14, fontWeight: 600,
                  cursor: prompt.trim() ? "pointer" : "not-allowed",
                }}
                title="Include automation workflows"
              >
                + Automation
              </button>
              <span style={{ fontSize: 12, color: "var(--text-muted)", marginLeft: 4 }}>
                Ctrl+Enter to build
              </span>
            </div>

            {/* Example prompts */}
            <div style={{ marginTop: 18 }}>
              <p style={{ fontSize: 11, fontWeight: 700, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.09em", margin: "0 0 8px" }}>
                Examples
              </p>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {EXAMPLES.map((ex, i) => (
                  <button
                    key={i}
                    onClick={() => setPrompt(ex)}
                    style={{
                      padding: "5px 12px", fontSize: 12,
                      background: "var(--surface-1)",
                      border: "1px solid var(--border)",
                      borderRadius: 20,
                      color: "var(--text-secondary)",
                      cursor: "pointer",
                      transition: "all 0.12s",
                    }}
                    onMouseEnter={e => {
                      const el = e.currentTarget as HTMLButtonElement;
                      el.style.borderColor = "var(--border-accent)";
                      el.style.color = "var(--text-accent)";
                    }}
                    onMouseLeave={e => {
                      const el = e.currentTarget as HTMLButtonElement;
                      el.style.borderColor = "var(--border)";
                      el.style.color = "var(--text-secondary)";
                    }}
                  >
                    {ex}
                  </button>
                ))}
              </div>
            </div>
          </>
        )}

        {/* ── BUILDING: live progress ── */}
        {phase === "building" && (
          <div>
            <div style={{ marginBottom: 16 }}>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, color: "var(--text-secondary)", marginBottom: 6 }}>
                <span style={{ textTransform: "capitalize" }}>{currentStep || "initializing"}</span>
                <span style={{ fontVariantNumeric: "tabular-nums" }}>{progress}%</span>
              </div>
              <div style={{ height: 6, background: "var(--surface-1)", borderRadius: 3, overflow: "hidden" }}>
                <div style={{
                  height: "100%", width: `${progress}%`,
                  background: "var(--fill-accent)", borderRadius: 3,
                  transition: "width 0.4s ease",
                }} />
              </div>
            </div>

            {steps.length > 0 && (
              <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 8 }}>
                {steps.map((step, i) => (
                  <div
                    key={i}
                    style={{
                      display: "flex", alignItems: "center", gap: 8,
                      fontSize: 13,
                      color: step.status === "pending" ? "var(--text-muted)" : "var(--text-primary)",
                    }}
                  >
                    <span style={{
                      fontSize: 14,
                      color: step.status === "ok"      ? "var(--text-success)"
                           : step.status === "error"   ? "var(--text-danger)"
                           : step.status === "warning" ? "var(--text-warning)"
                           : "var(--text-muted)",
                    }}>
                      {step.status === "ok" ? "✓" : step.status === "error" ? "✗" : step.status === "warning" ? "⚠" : "·"}
                    </span>
                    <span>{step.label}</span>
                    {step.detail && (
                      <span style={{ fontSize: 11, color: "var(--text-muted)", marginLeft: "auto" }}>
                        {step.detail}
                      </span>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* ── DONE ── */}
        {phase === "done" && (
          <div style={{ textAlign: "center", padding: "16px 0 4px" }}>
            <div style={{ fontSize: 40, marginBottom: 12 }}>✓</div>
            <p style={{ fontSize: 15, fontWeight: 600, color: "var(--text-primary)", margin: "0 0 6px" }}>
              App built successfully!
            </p>
            <p style={{ fontSize: 13, color: "var(--text-secondary)", margin: "0 0 20px", lineHeight: 1.5 }}>
              Your app structure has been generated. Open it in the canvas to start designing.
            </p>
            <button
              onClick={onClose}
              style={{
                padding: "10px 24px",
                background: "var(--fill-accent)", color: "#fff",
                border: "none", borderRadius: 8,
                fontSize: 14, fontWeight: 600, cursor: "pointer",
              }}
            >
              Open in Canvas
            </button>
          </div>
        )}
      </div>
    </>
  );
}
