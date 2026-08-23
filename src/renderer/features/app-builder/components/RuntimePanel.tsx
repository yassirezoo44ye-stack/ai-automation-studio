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
import { useEffect, useRef } from "react";

export type RuntimeState =
  | "idle"
  | "ready_to_run"
  | "starting"
  | "running"
  | "stopping"
  | "stopped"
  | "failed";

export type RuntimeError = {
  category: string;
  message: string;
  fix: string[];
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
  if (!buildDone) {
    return (
      <div style={CENTER}>
        <div style={{ fontSize: 40, opacity: 0.15 }}>▶</div>
        <div style={{ fontSize: 15, fontWeight: 600, color: "var(--t2)" }}>
          Live Preview
        </div>
        <div style={{ fontSize: 13, color: "var(--t4)", lineHeight: 1.6, textAlign: "center", maxWidth: 300 }}>
          Build your app first, then click <strong>Run Project</strong> to see it here.
        </div>
      </div>
    );
  }
  return (
    <div style={CENTER}>
      <div style={CARD}>
        <div style={{ fontSize: 36, marginBottom: 12 }}>🚀</div>
        <div style={{ fontSize: 16, fontWeight: 700, color: "var(--t1)", marginBottom: 8 }}>
          Ready to Run
        </div>
        <div style={{ fontSize: 13, color: "var(--t4)", lineHeight: 1.6, marginBottom: 20 }}>
          Your app has been built. Click <strong>Run Project</strong> to start the runtime
          and preview it live.
        </div>
        <button style={BTN_PRIMARY} onClick={onRun}>
          ▶ Run Project
        </button>
        <div style={{ fontSize: 11, color: "var(--t5)", marginTop: 12 }}>
          Run = local preview · not a production deployment
        </div>
      </div>
    </div>
  );
}

function StartingView({ messages }: { messages: string[] }) {
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
          Starting Runtime…
        </div>
        <div style={{ fontSize: 12, color: "var(--t4)", marginBottom: 16 }}>
          Installing dependencies and launching your app
        </div>
        {/* Live status log */}
        <div
          ref={logRef}
          style={{
            background: "#040506", borderRadius: 8, padding: "10px 14px",
            maxHeight: 140, overflowY: "auto",
            fontFamily: "var(--font-mono, monospace)", fontSize: 11,
            color: "var(--green, #4ade80)", textAlign: "left",
            lineHeight: 1.6,
          }}
        >
          {messages.length === 0
            ? <span style={{ color: "var(--t5)" }}>Detecting project type…</span>
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
}: {
  previewUrl: string;
  previewType: "proxy" | "blob";
  onStop: () => void;
  onRestart: () => void;
}) {
  // proxy URL is relative (/api/projects/.../proxy/) → same-origin iframe is safe
  // blob URL is object URL → also safe in iframe
  const iframeSrc = previewType === "proxy"
    ? `${window.location.origin}${previewUrl}`
    : previewUrl;

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
          fontSize: 11, color: "var(--green)", fontWeight: 600,
        }}>
          <div style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--green)" }} />
          Running
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
        <button style={BTN_GHOST} onClick={onRestart}>↺ Restart</button>
        <button style={BTN_DANGER} onClick={onStop}>■ Stop</button>
        {previewType === "proxy" && (
          <button
            style={BTN_GHOST}
            onClick={() => window.open(iframeSrc, "_blank")}
          >
            ⇱ Open
          </button>
        )}
      </div>
      {/* Iframe preview */}
      <iframe
        src={iframeSrc}
        title="App Preview"
        style={{ flex: 1, border: "none", width: "100%", height: "100%" }}
        sandbox="allow-scripts allow-forms allow-same-origin allow-popups allow-modals"
      />
    </div>
  );
}

function StoppedView({ onRun }: { onRun: () => void }) {
  return (
    <div style={CENTER}>
      <div style={CARD}>
        <div style={{ fontSize: 32, marginBottom: 12, opacity: 0.4 }}>■</div>
        <div style={{ fontSize: 15, fontWeight: 600, color: "var(--t2)", marginBottom: 8 }}>
          Runtime Stopped
        </div>
        <div style={{ fontSize: 13, color: "var(--t4)", marginBottom: 20 }}>
          The preview server has been stopped.
        </div>
        <button style={BTN_PRIMARY} onClick={onRun}>
          ▶ Run Again
        </button>
      </div>
    </div>
  );
}

function FailedView({
  error,
  onRetry,
  onExplain,
}: {
  error: RuntimeError;
  onRetry: () => void;
  onExplain: (err: RuntimeError) => void;
}) {
  const SEVERITY_COLOR: Record<string, string> = {
    high:   "var(--red, #ef4444)",
    medium: "var(--yellow, #eab308)",
    low:    "var(--t4)",
  };
  const col = SEVERITY_COLOR[error.category === "unsupported" ? "medium" : "high"];

  return (
    <div style={CENTER}>
      <div style={{ ...CARD, maxWidth: 520, textAlign: "left" }}>
        <div style={{
          fontSize: 12, fontWeight: 700, textTransform: "uppercase",
          letterSpacing: "0.08em", color: col, marginBottom: 8,
        }}>
          Run Failed
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
            <div style={{ fontSize: 11, fontWeight: 600, color: "var(--t5)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 8 }}>
              Suggestions
            </div>
            {error.fix.map((step, i) => (
              <div key={i} style={{ display: "flex", gap: 8, marginBottom: 6, fontSize: 12, color: "var(--t2)" }}>
                <span style={{ color: "var(--accent)", minWidth: 18, fontWeight: 600 }}>{i + 1}.</span>
                <span style={{ lineHeight: 1.5 }}>{step}</span>
              </div>
            ))}
          </div>
        )}

        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button style={BTN_PRIMARY} onClick={onRetry}>↺ Retry</button>
          <button style={BTN_GHOST} onClick={() => onExplain(error)}>
            🤖 Explain with AI
          </button>
        </div>
        <div style={{ marginTop: 10, fontSize: 11, color: "var(--t5)" }}>
          "Fix with AI" will propose changes — you review before applying.
        </div>
      </div>
    </div>
  );
}

function StoppingView() {
  return (
    <div style={CENTER}>
      <div style={{ fontSize: 13, color: "var(--t4)", display: "flex", alignItems: "center", gap: 8 }}>
        <div style={{
          width: 14, height: 14, borderRadius: "50%",
          border: "2px solid var(--accent)",
          borderTopColor: "transparent",
          animation: "spin 0.8s linear infinite",
        }} />
        Stopping runtime…
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
  projectName: _projectName,
  startupMessages,
  onRun,
  onStop,
  onRestart,
  onExplainError,
}: Props) {
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
        />
      )}
      {runtimeState === "stopping" && <StoppingView />}
      {runtimeState === "stopped" && (
        <StoppedView onRun={onRun} />
      )}
      {runtimeState === "failed" && runtimeError && (
        <FailedView
          error={runtimeError}
          onRetry={onRun}
          onExplain={onExplainError}
        />
      )}
    </div>
  );
}
