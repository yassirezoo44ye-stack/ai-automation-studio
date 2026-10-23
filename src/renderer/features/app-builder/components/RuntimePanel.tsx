/**
 * RuntimePanel — center panel of App Builder.
 *
 * Displays the live preview or the appropriate runtime state UI.
 * All state transitions come from real backend events — no fake progress.
 *
 * States:
 *   idle         → empty workspace placeholder (before any build)
 *   ready_to_run → build done, awaiting user to click "Run Project"
 *   starting     → SSE stream open, status events arriving
 *   running      → server_ready or html received; preview visible
 *   stopping     → stop requested, waiting for backend to confirm
 *   stopped      → runtime stopped; "Run Again" available
 *   failed       → error received; AI assistance offered
 *
 * Preview surfaces:
 *   proxy URL  (/api/projects/{id}/proxy/) → iframe (same-origin relative URL)
 *   blob URL   (object URL from html driver) → iframe (blob: URL)
 */
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

export type RuntimeState =
  | "idle"
  | "ready_to_run"
  | "starting"
  | "running"
  | "preview"    // P0-C: static HTML blob URL — not a real running server
  | "stopping"
  | "stopped"
  | "failed";

export type RuntimeError = {
  category: string;
  message: string;
  fix: string[];
  severity?: "low" | "medium" | "high";
};

interface Props {
  runtimeState: RuntimeState;
  previewUrl: string | null;
  previewType: "proxy" | "blob" | null;
  runtimeError: RuntimeError | null;
  buildDone: boolean;
  projectName: string;
  /** Accumulated status messages during startup */
  startupMessages: string[];
  onRun: () => void;
  onStop: () => void;
  onRestart: () => void;
  onExplainError: (err: RuntimeError) => void;
}

/* ── Shared styles ────────────────────────────────────────────────────────── */

const CENTER: React.CSSProperties = {
  flex: 1, display: "flex", flexDirection: "column",
  alignItems: "center", justifyContent: "center",
  gap: 16, padding: 32,
};

const CARD: React.CSSProperties = {
  background: "var(--bg-card)",
  border: "1px solid var(--b1)",
  borderRadius: 16,
  padding: "28px 32px",
  maxWidth: 480,
  width: "100%",
  textAlign: "center",
};

const BTN_PRIMARY: React.CSSProperties = {
  padding: "10px 24px", borderRadius: 10, border: "none",
  background: "linear-gradient(135deg, var(--accent) 0%, var(--teal) 100%)",
  color: "white", fontSize: 13, fontWeight: 700, cursor: "pointer",
  boxShadow: "0 2px 12px rgba(110,50,224,0.35)",
};

const BTN_GHOST: React.CSSProperties = {
  padding: "8px 16px", borderRadius: 8, border: "1px solid var(--b1)",
  background: "transparent", color: "var(--t2)", fontSize: 12,
  fontWeight: 500, cursor: "pointer",
};

const BTN_DANGER: React.CSSProperties = {
  padding: "8px 16px", borderRadius: 8, border: "1px solid rgba(239,68,68,0.3)",
  background: "rgba(239,68,68,0.08)", color: "var(--red, #ef4444)",
  fontSize: 12, fontWeight: 500, cursor: "pointer",
};

/* ── Sub-views ────────────────────────────────────────────────────────────── */

function IdleView({ buildDone, onRun }: { buildDone: boolean; onRun: () => void }) {
  const { t } = useTranslation("dev");
  if (!buildDone) {
    return (
      <div style={CENTER}>
        <div style={{ fontSize: 40, opacity: 0.15 }}>▶</div>
        <div style={{ fontSize: 15, fontWeight: 600, color: "var(--t2)" }}>
          {t("runtimePanel.livePreview")}
        </div>
        <p style={{ fontSize: 13, color: "var(--t4)", lineHeight: 1.6, textAlign: "center", maxWidth: 300, margin: 0 }}>
          {t("runtimePanel.buildFirst")}
        </p>
      </div>
    );
  }
  return (
    <div style={CENTER}>
      <div style={CARD}>
        <div style={{ fontSize: 36, marginBottom: 12 }}>🚀</div>
        <div style={{ fontSize: 16, fontWeight: 700, color: "var(--t1)", marginBottom: 8 }}>
          {t("runtimePanel.readyToRun")}
        </div>
        <div style={{ fontSize: 13, color: "var(--t4)", lineHeight: 1.6, marginBottom: 20 }}>
          {t("runtimePanel.appBuilt")}
        </div>
        <button className="rp-btn-primary" style={BTN_PRIMARY} onClick={onRun}>
          {t("runtimePanel.runProject")}
        </button>
        <div style={{ fontSize: 11, color: "var(--t5)", marginTop: 12 }}>
          {t("runtimePanel.runNote")}
        </div>
      </div>
    </div>
  );
}

function StartingView({ messages }: { messages: string[] }) {
  const { t } = useTranslation("dev");
  const logRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  return (
    <div style={CENTER}>
      <div style={{ ...CARD, maxWidth: 560 }}>
        {/* Spinner */}
        <div style={{ display: "flex", gap: 6, justifyContent: "center", marginBottom: 16 }}>
          {[0,1,2].map(i => (
            <div key={i} style={{
              width: 9, height: 9, borderRadius: "50%",
              background: "var(--accent)",
              animation: `bounce 1s ease-in-out ${i * 0.15}s infinite`,
            }} />
          ))}
        </div>
        <div style={{ fontSize: 15, fontWeight: 700, color: "var(--t1)", marginBottom: 4 }}>
          {t("runtimePanel.startingRuntime")}
        </div>
        <div style={{ fontSize: 12, color: "var(--t4)", marginBottom: 16 }}>
          {t("runtimePanel.installingDeps")}
        </div>
        {/* Live status log — 220px shows ~12 lines; enough for npm install output */}
        <div
          ref={logRef}
          style={{
            background: "#040506", borderRadius: 8, padding: "10px 14px",
            maxHeight: 220, overflowY: "auto",
            fontFamily: "var(--font-mono, monospace)", fontSize: 11,
            color: "var(--green, #4ade80)", textAlign: "start",
            lineHeight: 1.6,
          }}
        >
          {messages.length === 0
            ? <span style={{ color: "var(--t5)" }}>{t("runtimePanel.detectingType")}</span>
            : messages.map((m, i) => <div key={i}>{m}</div>)
          }
        </div>
      </div>
    </div>
  );
}

function RunningView({
  previewUrl,
  previewType,
  onStop,
  onRestart,
  label,
}: {
  previewUrl: string;
  previewType: "proxy" | "blob";
  onStop: () => void;
  onRestart: () => void;
  /** Status label shown in the toolbar. "Running" = real server; "Preview" = static blob. */
  label: string;
}) {
  // proxy URL is relative (/api/projects/.../proxy/) → same-origin iframe is safe
  // blob URL is object URL → also safe in iframe
  const iframeSrc = previewType === "proxy"
    ? `${window.location.origin}${previewUrl}`
    : previewUrl;

  const { t } = useTranslation("dev");
  const isPreview = label !== t("runtimePanel.stop").replace("■ ", "") && label === t("runtimePanel.livePreview");
  const dotColor  = isPreview ? "var(--teal, #0ea5e9)" : "var(--green)";
  const lblColor  = isPreview ? "var(--teal, #0ea5e9)" : "var(--green)";

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
      {/* Preview toolbar */}
      <div style={{
        display: "flex", alignItems: "center", gap: 8,
        padding: "4px 12px", background: "var(--bg-base)",
        borderBottom: "1px solid var(--b1)", flexShrink: 0,
      }}>
        <div style={{
          display: "flex", alignItems: "center", gap: 6,
          fontSize: 11, color: lblColor, fontWeight: 600,
        }}>
          <div style={{ width: 6, height: 6, borderRadius: "50%", background: dotColor }} />
          {label}
        </div>
        <div style={{ flex: 1, overflow: "hidden" }}>
          <div style={{
            fontSize: 11, color: "var(--t5)", overflow: "hidden",
            textOverflow: "ellipsis", whiteSpace: "nowrap",
            fontFamily: "var(--font-mono, monospace)",
          }}>
            {previewUrl}
          </div>
        </div>
        <button className="rp-btn-ghost" style={BTN_GHOST} onClick={onRestart}>
          {t("runtimePanel.restart")}
        </button>
        <button className="rp-btn-danger" style={BTN_DANGER} onClick={onStop}>
          {t("runtimePanel.stop")}
        </button>
        {previewType === "proxy" && (
          <button
            className="rp-btn-ghost"
            style={BTN_GHOST}
            onClick={() => window.open(iframeSrc, "_blank")}
          >
            {t("runtimePanel.open")}
          </button>
        )}
      </div>
      {/* Iframe preview */}
      <iframe
        src={iframeSrc}
        title={t("runtimePanel.iframeTitle")}
        style={{ flex: 1, border: "none", width: "100%", height: "100%" }}
        sandbox="allow-scripts allow-forms allow-same-origin allow-popups allow-modals"
      />
    </div>
  );
}

function StoppedView({ onRun }: { onRun: () => void }) {
  const { t } = useTranslation("dev");
  return (
    <div style={CENTER}>
      <div style={CARD}>
        <div style={{ fontSize: 32, marginBottom: 12, opacity: 0.4 }}>■</div>
        <div style={{ fontSize: 15, fontWeight: 600, color: "var(--t2)", marginBottom: 8 }}>
          {t("runtimePanel.runtimeStopped")}
        </div>
        <div style={{ fontSize: 13, color: "var(--t4)", marginBottom: 20 }}>
          {t("runtimePanel.previewStopped")}
        </div>
        <button className="rp-btn-primary" style={BTN_PRIMARY} onClick={onRun}>
          {t("runtimePanel.runAgain")}
        </button>
      </div>
    </div>
  );
}

function FailedView({
  error,
  projectName,
  onRetry,
  onExplain,
}: {
  error: RuntimeError;
  projectName: string;
  onRetry: () => void;
  onExplain: (err: RuntimeError) => void;
}) {
  const { t } = useTranslation("dev");
  const [copied, setCopied] = useState(false);

  const SEVERITY_COLOR: Record<string, string> = {
    high:   "var(--red, #ef4444)",
    medium: "var(--yellow, #eab308)",
    low:    "var(--t4)",
  };
  // Use the severity field when present; fall back to category-based heuristic.
  const severity = error.severity ?? (error.category === "unsupported" ? "medium" : "high");
  const col = SEVERITY_COLOR[severity] ?? SEVERITY_COLOR.high;

  const copyError = async () => {
    const text = [error.message, ...error.fix].join("\n");
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      // Fallback for browsers that block clipboard API
      const el = document.createElement("textarea");
      el.value = text;
      el.style.cssText = "position:fixed;opacity:0;pointer-events:none";
      document.body.appendChild(el);
      el.select();
      document.execCommand("copy");
      document.body.removeChild(el);
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div style={CENTER}>
      <div style={{ ...CARD, maxWidth: 520, textAlign: "start" }}>
        <div style={{
          fontSize: 12, fontWeight: 700, textTransform: "uppercase",
          letterSpacing: "0.08em", color: col, marginBottom: 8,
          display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap",
        }}>
          <span>{t("runtimePanel.runFailed")}</span>
          {projectName && (
            <span style={{
              color: "var(--t4)", fontWeight: 400,
              textTransform: "none", letterSpacing: 0, fontSize: 11,
            }}>
              — {projectName}
            </span>
          )}
        </div>
        <div style={{
          fontSize: 13, fontWeight: 600, color: "var(--t1)",
          marginBottom: 12, lineHeight: 1.5,
          fontFamily: error.category !== "unsupported" ? "var(--font-mono, monospace)" : undefined,
          whiteSpace: "pre-wrap", wordBreak: "break-word",
        }}>
          {error.message}
        </div>

        {error.fix.length > 0 && (
          <div style={{ marginBottom: 16 }}>
            <div style={{
              fontSize: 11, fontWeight: 600, color: "var(--t5)",
              textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 8,
            }}>
              {t("runtimePanel.suggestions")}
            </div>
            {error.fix.map((step, i) => (
              <div key={i} style={{ display: "flex", gap: 8, marginBottom: 6, fontSize: 12, color: "var(--t2)" }}>
                <span style={{ color: "var(--accent)", minWidth: 18, fontWeight: 600 }}>{i + 1}.</span>
                <span style={{ lineHeight: 1.5 }}>{step}</span>
              </div>
            ))}
          </div>
        )}

        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <button className="rp-btn-primary" style={BTN_PRIMARY} onClick={onRetry}>
            ↺ {t("runtimePanel.retry")}
          </button>
          <button className="rp-btn-ghost" style={BTN_GHOST} onClick={() => onExplain(error)}>
            🤖 {t("runtimePanel.explainWithAI")}
          </button>
          <button
            className="rp-btn-ghost"
            style={{ ...BTN_GHOST, marginInlineStart: "auto" }}
            onClick={copyError}
            aria-label={t("runtimePanel.copyError")}
          >
            {copied ? `✓ ${t("runtimePanel.copied")}` : `⎘ ${t("runtimePanel.copyError")}`}
          </button>
        </div>
        <div style={{ marginTop: 10, fontSize: 11, color: "var(--t5)" }}>
          {t("runtimePanel.explainNote")}
        </div>
      </div>
    </div>
  );
}

function StoppingView() {
  const { t } = useTranslation("dev");
  return (
    <div style={CENTER}>
      <div style={{ fontSize: 13, color: "var(--t4)", display: "flex", alignItems: "center", gap: 8 }}>
        <div style={{
          width: 14, height: 14, borderRadius: "50%",
          border: "2px solid var(--accent)",
          borderTopColor: "transparent",
          animation: "spin 0.8s linear infinite",
        }} />
        {t("runtimePanel.stopping")}
      </div>
    </div>
  );
}

/* ── Main component ──────────────────────────────────────────────────────── */

export function RuntimePanel({
  runtimeState,
  previewUrl,
  previewType,
  runtimeError,
  buildDone,
  projectName,
  startupMessages,
  onRun,
  onStop,
  onRestart,
  onExplainError,
}: Props) {
  const { t } = useTranslation("dev");
  return (
    <div style={{
      flex: 1, display: "flex", flexDirection: "column",
      borderLeft: "1px solid var(--b1)",
      borderRight: "1px solid var(--b1)",
      background: "var(--bg-base)",
      overflow: "hidden",
      position: "relative",
    }}>
      {runtimeState === "idle" && (
        <IdleView buildDone={buildDone} onRun={onRun} />
      )}
      {runtimeState === "ready_to_run" && (
        <IdleView buildDone={true} onRun={onRun} />
      )}
      {runtimeState === "starting" && (
        <StartingView messages={startupMessages} />
      )}
      {runtimeState === "running" && previewUrl && previewType && (
        <RunningView
          previewUrl={previewUrl}
          previewType={previewType}
          onStop={onStop}
          onRestart={onRestart}
          label="Running"
        />
      )}
      {runtimeState === "preview" && previewUrl && previewType && (
        <RunningView
          previewUrl={previewUrl}
          previewType={previewType}
          onStop={onStop}
          onRestart={onRestart}
          label={t("runtimePanel.livePreview")}
        />
      )}
      {runtimeState === "stopping" && <StoppingView />}
      {runtimeState === "stopped" && (
        <StoppedView onRun={onRun} />
      )}
      {runtimeState === "failed" && runtimeError && (
        <FailedView
          error={runtimeError}
          projectName={projectName}
          onRetry={onRun}
          onExplain={onExplainError}
        />
      )}
    </div>
  );
}
