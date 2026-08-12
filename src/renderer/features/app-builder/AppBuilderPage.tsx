/**
 * AI Business App Builder — main page.
 *
 * Three panels:
 *  1. PromptPanel   — chat input + examples
 *  2. BuildProgress — live progress bar + steps (polled from the server)
 *  3. AppPreview    — build result summary with open/edit/publish actions
 *  4. AppList       — list of existing apps in the org
 */
import { useState, useRef, useCallback, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { useAppContext } from "../../contexts/app";
import { useToast } from "../../contexts/toast";
import * as api from "./api";
import { APIError } from "../../shared/utils/api";
import type {
  AppSpec, BuildResult, AppRecord, AppDetail,
  BuildPhase, BuildStep,
} from "./types";

/** How often to poll GET /apps/{id} during an active build (ms). */
const POLL_INTERVAL_MS = 2000;

/** Build_status values that indicate a completed (terminal) build. */
const TERMINAL_STATUSES = new Set(["ready", "partial", "failed"]);

// ── Build step icons ──────────────────────────────────────────────────────────

function StepIcon({ status }: { status: BuildStep["status"] }) {
  if (status === "ok") {
    return (
      <span style={{ color: "var(--success, #22c55e)", fontSize: 16 }}>✓</span>
    );
  }
  if (status === "warning") {
    return (
      <span style={{ color: "var(--warning, #f59e0b)", fontSize: 16 }}>⚠</span>
    );
  }
  if (status === "error") {
    return (
      <span style={{ color: "var(--error, #ef4444)", fontSize: 16 }}>✗</span>
    );
  }
  // pending — spinning ring
  return (
    <span
      style={{
        display: "inline-block",
        width: 14,
        height: 14,
        border: "2px solid var(--accent)",
        borderTopColor: "transparent",
        borderRadius: "50%",
        animation: "spin 0.8s linear infinite",
      }}
    />
  );
}

// ── Progress bar ──────────────────────────────────────────────────────────────

function ProgressBar({ pct, label }: { pct: number; label: string }) {
  return (
    <div style={{ marginBottom: 16 }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          fontSize: 12,
          color: "var(--t3)",
          marginBottom: 6,
        }}
      >
        <span style={{ textTransform: "capitalize" }}>{label}</span>
        <span style={{ fontVariantNumeric: "tabular-nums" }}>{pct}%</span>
      </div>
      <div
        style={{
          height: 6,
          background: "var(--bg-hover)",
          borderRadius: 3,
          overflow: "hidden",
        }}
      >
        <div
          style={{
            height: "100%",
            width: `${pct}%`,
            background: "var(--accent)",
            borderRadius: 3,
            transition: "width 0.4s ease",
          }}
        />
      </div>
    </div>
  );
}

// ── Build progress panel ──────────────────────────────────────────────────────

function BuildProgressPanel({
  steps,
  phase,
  progress,
  currentStep,
}: {
  steps: BuildStep[];
  phase: BuildPhase;
  progress: number;
  currentStep: string;
}) {
  const { t } = useTranslation("appBuilder");

  const defaultSteps = [
    t("steps.understanding"),
    t("steps.database"),
    t("steps.backend"),
    t("steps.pages"),
    t("steps.permissions"),
    t("steps.workflows"),
    t("steps.validating"),
  ];

  const displaySteps =
    steps.length > 0
      ? steps
      : defaultSteps.map((label) => ({ label, status: "pending" as const, detail: "" }));

  return (
    <div
      style={{
        background: "var(--bg-card)",
        border: "1px solid var(--b1)",
        borderRadius: 12,
        padding: "24px 28px",
        marginTop: 24,
      }}
    >
      <p
        style={{
          fontSize: 14,
          fontWeight: 600,
          color: "var(--t2)",
          marginBottom: 12,
        }}
      >
        {phase === "building" ? t("building") : t("steps.validating")}
      </p>

      {/* Real progress bar — only shown during an active build */}
      {phase === "building" && (
        <ProgressBar pct={progress} label={currentStep || "initializing"} />
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {displaySteps.map((step, i) => (
          <div
            key={i}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 12,
              fontSize: 14,
              color: step.status === "pending" ? "var(--t3)" : "var(--t1)",
            }}
          >
            <StepIcon status={step.status} />
            <span style={{ flex: 1 }}>{step.label}</span>
            {step.detail && (
              <span style={{ fontSize: 12, color: "var(--t3)" }}>{step.detail}</span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Preview panel ─────────────────────────────────────────────────────────────

function AppPreviewPanel({
  spec,
  result,
  onOpenDesign,
  onModify,
  onNewApp,
  onRetry,
}: {
  spec: AppSpec;
  result: BuildResult;
  onOpenDesign: () => void;
  onModify: (prompt: string) => void;
  onNewApp: () => void;
  onRetry?: () => void;
}) {
  const { t } = useTranslation("appBuilder");
  const [modifyPrompt, setModifyPrompt] = useState("");
  const [modifying, setModifying] = useState(false);
  const [showModify, setShowModify] = useState(false);
  const toast = useToast();

  const handleModify = async () => {
    if (!modifyPrompt.trim()) return;
    setModifying(true);
    try {
      onModify(modifyPrompt.trim());
      setModifyPrompt("");
      setShowModify(false);
    } catch {
      toast(t("error.modifyFailed"), "err");
    } finally {
      setModifying(false);
    }
  };

  const isPartial = result.status === "partial";
  const isFailed = result.status === "failed";
  const statusColor =
    result.status === "ready"
      ? "var(--success, #22c55e)"
      : result.status === "partial"
      ? "var(--warning, #f59e0b)"
      : "var(--error, #ef4444)";

  const summaryItems = [
    { count: result.summary.tables, label: t("preview.tables"), show: result.summary.tables > 0 },
    { count: result.summary.pages, label: t("preview.pages"), show: result.summary.pages > 0 },
    { count: result.summary.roles, label: t("preview.roles"), show: result.summary.roles > 0 },
    { count: result.summary.api_operations, label: t("preview.apiOps"), show: result.summary.api_operations > 0 },
    { count: result.summary.workflows, label: t("preview.workflows"), show: result.summary.workflows > 0 },
    { count: result.summary.agents, label: t("preview.agents"), show: result.summary.agents > 0 },
  ].filter((item) => item.show);

  return (
    <div
      style={{
        background: "var(--bg-card)",
        border: "1px solid var(--b1)",
        borderRadius: 12,
        padding: "28px 32px",
        marginTop: 24,
      }}
    >
      {/* Header */}
      <div
        style={{
          display: "flex",
          alignItems: "flex-start",
          justifyContent: "space-between",
          gap: 16,
          marginBottom: 24,
        }}
      >
        <div>
          <div
            style={{
              fontSize: 11,
              fontWeight: 600,
              textTransform: "uppercase",
              letterSpacing: "0.08em",
              color: statusColor,
              marginBottom: 4,
            }}
          >
            {isFailed
              ? t("status.failed")
              : isPartial
              ? t("warnings.title")
              : t("preview.title")}
          </div>
          <h2 style={{ fontSize: 22, fontWeight: 700, color: "var(--t1)", margin: 0 }}>
            {spec.name}
          </h2>
          {spec.description && (
            <p style={{ fontSize: 13, color: "var(--t2)", marginTop: 4 }}>
              {spec.description}
            </p>
          )}
        </div>
        <button
          onClick={onNewApp}
          style={{
            fontSize: 13,
            color: "var(--t3)",
            background: "none",
            border: "1px solid var(--b1)",
            borderRadius: 8,
            padding: "6px 14px",
            cursor: "pointer",
          }}
        >
          {t("newApp")}
        </button>
      </div>

      {/* Summary stats */}
      {summaryItems.length > 0 && (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(120px, 1fr))",
            gap: 12,
            marginBottom: 24,
          }}
        >
          {summaryItems.map(({ count, label }) => (
            <div
              key={label}
              style={{
                background: "var(--bg-hover)",
                borderRadius: 8,
                padding: "12px 16px",
                textAlign: "center",
              }}
            >
              <div style={{ fontSize: 24, fontWeight: 700, color: "var(--accent)" }}>
                {count}
              </div>
              <div style={{ fontSize: 11, color: "var(--t3)", marginTop: 2 }}>{label}</div>
            </div>
          ))}
        </div>
      )}

      {/* Warnings */}
      {result.warnings.length > 0 && (
        <div
          style={{
            background: "color-mix(in srgb, var(--warning, #f59e0b) 10%, transparent)",
            border: "1px solid color-mix(in srgb, var(--warning, #f59e0b) 30%, transparent)",
            borderRadius: 8,
            padding: "12px 16px",
            marginBottom: 20,
          }}
        >
          {result.warnings.map((w, i) => (
            <div key={i} style={{ fontSize: 13, color: "var(--t2)", display: "flex", gap: 8 }}>
              <span style={{ color: "var(--warning, #f59e0b)" }}>⚠</span>
              {w}
            </div>
          ))}
        </div>
      )}

      {/* Action buttons */}
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 20 }}>
        {!isFailed && (
          <button
            onClick={onOpenDesign}
            style={{
              padding: "10px 20px",
              background: "var(--accent)",
              color: "#fff",
              border: "none",
              borderRadius: 8,
              fontSize: 14,
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            {t("preview.editDesign")}
          </button>
        )}
        {!isFailed && (
          <button
            onClick={() => setShowModify((v) => !v)}
            style={{
              padding: "10px 20px",
              background: "var(--bg-hover)",
              color: "var(--t1)",
              border: "1px solid var(--b1)",
              borderRadius: 8,
              fontSize: 14,
              cursor: "pointer",
            }}
          >
            {t("modify.title")}
          </button>
        )}
        {(isPartial || isFailed) && onRetry && (
          <button
            onClick={onRetry}
            style={{
              padding: "10px 20px",
              background: "var(--bg-hover)",
              color: "var(--warning, #f59e0b)",
              border: "1px solid var(--warning, #f59e0b)",
              borderRadius: 8,
              fontSize: 14,
              cursor: "pointer",
            }}
          >
            {t("retry", "Retry build")}
          </button>
        )}
      </div>

      {/* Inline modify input */}
      {showModify && (
        <div style={{ display: "flex", gap: 8, marginBottom: 20 }}>
          <input
            type="text"
            value={modifyPrompt}
            onChange={(e) => setModifyPrompt(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void handleModify();
              }
            }}
            placeholder={t("modify.placeholder")}
            disabled={modifying}
            style={{
              flex: 1,
              padding: "10px 14px",
              border: "1px solid var(--b1)",
              borderRadius: 8,
              background: "var(--bg-input)",
              color: "var(--t1)",
              fontSize: 14,
              outline: "none",
            }}
          />
          <button
            onClick={handleModify}
            disabled={modifying || !modifyPrompt.trim()}
            style={{
              padding: "10px 18px",
              background: "var(--accent)",
              color: "#fff",
              border: "none",
              borderRadius: 8,
              fontSize: 14,
              cursor: modifying ? "wait" : "pointer",
              opacity: modifying || !modifyPrompt.trim() ? 0.6 : 1,
            }}
          >
            {modifying ? "…" : t("modify.button")}
          </button>
        </div>
      )}

      {/* Build steps */}
      <details style={{ marginTop: 20 }}>
        <summary
          style={{
            fontSize: 13,
            color: "var(--t3)",
            cursor: "pointer",
            userSelect: "none",
          }}
        >
          Build log ({result.steps.length} steps)
        </summary>
        <div style={{ marginTop: 10 }}>
          <BuildProgressPanel
            steps={result.steps}
            phase="done"
            progress={100}
            currentStep=""
          />
        </div>
      </details>
    </div>
  );
}

// ── App list card ─────────────────────────────────────────────────────────────

function AppCard({
  app,
  onSelect,
}: {
  app: AppRecord;
  onSelect: (id: string) => void;
}) {
  const { t } = useTranslation("appBuilder");

  const statusColor: Record<string, string> = {
    ready: "var(--success, #22c55e)",
    partial: "var(--warning, #f59e0b)",
    building: "var(--accent)",
    planning: "var(--accent)",
    failed: "var(--error, #ef4444)",
    pending: "var(--t3)",
  };

  return (
    <button
      onClick={() => onSelect(app.id)}
      style={{
        background: "var(--bg-card)",
        border: "1px solid var(--b1)",
        borderRadius: 10,
        padding: "16px 20px",
        textAlign: "left",
        cursor: "pointer",
        transition: "border-color 0.15s",
        width: "100%",
      }}
      onMouseEnter={(e) =>
        ((e.currentTarget as HTMLButtonElement).style.borderColor = "var(--accent)")
      }
      onMouseLeave={(e) =>
        ((e.currentTarget as HTMLButtonElement).style.borderColor = "var(--b1)")
      }
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div style={{ fontSize: 15, fontWeight: 600, color: "var(--t1)" }}>{app.name}</div>
        <span
          style={{
            fontSize: 10,
            fontWeight: 700,
            textTransform: "uppercase",
            letterSpacing: "0.06em",
            color: statusColor[app.build_status] ?? "var(--t3)",
            background: `color-mix(in srgb, ${statusColor[app.build_status] ?? "var(--t3)"} 15%, transparent)`,
            borderRadius: 4,
            padding: "2px 7px",
          }}
        >
          {t(`status.${app.build_status}`, { defaultValue: app.build_status })}
        </span>
      </div>
      {app.description && (
        <p
          style={{
            fontSize: 12,
            color: "var(--t3)",
            marginTop: 4,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {app.description}
        </p>
      )}
      <div style={{ display: "flex", gap: 12, marginTop: 8, fontSize: 11, color: "var(--t3)" }}>
        {app.workflow_count > 0 && <span>{app.workflow_count} workflows</span>}
        {app.agent_count > 0 && <span>{app.agent_count} agents</span>}
        <span style={{ marginLeft: "auto" }}>
          {new Date(app.created_at).toLocaleDateString()}
        </span>
      </div>
    </button>
  );
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Convert an AppDetail (from GET /apps/{id}) into a BuildResult for AppPreviewPanel. */
function detailToBuildResult(detail: AppDetail): BuildResult {
  const br = detail.build_result as Record<string, unknown> | null ?? {};
  const steps = Array.isArray(br["steps"]) ? (br["steps"] as BuildStep[]) : [];
  return {
    app_id: detail.id,
    app_name: detail.name,
    status: (detail.build_status as "ready" | "partial" | "failed") ?? "failed",
    summary: {
      tables: typeof br["tables"] === "number" ? br["tables"] : 0,
      pages: typeof br["pages"] === "number" ? br["pages"] : 0,
      roles: typeof br["roles"] === "number" ? br["roles"] : 0,
      api_operations: typeof br["api_operations"] === "number" ? br["api_operations"] : 0,
      workflows: typeof br["workflows"] === "number" ? br["workflows"] : 0,
      agents: typeof br["agents"] === "number" ? br["agents"] : 0,
      canvas_id: detail.canvas_id,
    },
    steps,
    warnings: detail.build_warnings ?? [],
  };
}

// ── Main page ─────────────────────────────────────────────────────────────────

export function AppBuilderPage() {
  const { t } = useTranslation("appBuilder");
  const { setPage } = useAppContext();
  const toast = useToast();

  const [phase, setPhase] = useState<BuildPhase>("idle");
  const [prompt, setPrompt] = useState("");
  const [spec, setSpec] = useState<AppSpec | null>(null);
  const [result, setResult] = useState<BuildResult | null>(null);
  const [apps, setApps] = useState<AppRecord[] | null>(null);
  const [loadingApps, setLoadingApps] = useState(false);
  const [currentAppId, setCurrentAppId] = useState<string | null>(null);
  const [buildSteps, setBuildSteps] = useState<BuildStep[]>([]);
  const [buildProgress, setBuildProgress] = useState(0);
  const [buildCurrentStep, setBuildCurrentStep] = useState("initializing");

  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  /**
   * Tracks whether the component is still mounted.
   * The async setInterval callback may fire after unmount — every state
   * setter call is guarded by isMountedRef.current to prevent the
   * "Can't perform a React state update on an unmounted component" warning
   * and any related memory-leak / double-update bugs.
   */
  const isMountedRef = useRef(true);

  const examples = t("examplesList", { returnObjects: true }) as string[];

  // Track mount state so polling callbacks can bail out after unmount
  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  // Cleanup polling on unmount
  useEffect(() => {
    return () => {
      if (pollRef.current !== null) {
        clearInterval(pollRef.current);
      }
    };
  }, []);

  // Start polling GET /apps/{id} until build is terminal
  const startPolling = useCallback(
    (appId: string) => {
      if (pollRef.current !== null) {
        clearInterval(pollRef.current);
      }
      pollRef.current = setInterval(async () => {
        try {
          const detail: AppDetail = await api.getApp(appId);

          // Guard: component may have unmounted while the request was in flight
          if (!isMountedRef.current) return;

          const pct = detail.progress ?? 0;
          const stepName = detail.current_step ?? "";
          setBuildProgress(pct);
          setBuildCurrentStep(stepName);

          // Update step list if the server has real steps
          const serverSteps = Array.isArray(
            (detail.build_result as Record<string, unknown> | null)?.["steps"],
          )
            ? ((detail.build_result as Record<string, unknown>)["steps"] as BuildStep[])
            : [];
          if (serverSteps.length > 0) {
            setBuildSteps(serverSteps);
          }

          if (TERMINAL_STATUSES.has(detail.build_status)) {
            clearInterval(pollRef.current!);
            pollRef.current = null;

            if (detail.build_status === "ready" || detail.build_status === "partial") {
              setSpec(detail.spec);
              setResult(detailToBuildResult(detail));
              setPhase("done");
            } else {
              // failed
              setPhase("error");
              const errMsg = detail.error ?? t("error.buildFailed");
              toast(errMsg, "err");
            }
          }
        } catch (err) {
          // Guard: component may have unmounted while the request was in flight
          if (!isMountedRef.current) return;

          // Determine if this is a permanent error (stop polling) or a
          // transient one (network glitch / 5xx — keep retrying silently).
          const status = err instanceof APIError ? err.details.status : 0;

          if (status === 401 || status === 403) {
            // Auth failure — no point continuing; user must re-authenticate.
            clearInterval(pollRef.current!);
            pollRef.current = null;
            setPhase("error");
            toast(t("error.authRequired", "Session expired — please refresh the page"), "err");
          } else if (status === 404) {
            // App was deleted while polling — stop silently and reset.
            clearInterval(pollRef.current!);
            pollRef.current = null;
            setPhase("idle");
          }
          // Any other status (0 = network error, 429, 500, 503) → transient;
          // keep the interval running and retry on the next tick.
        }
      }, POLL_INTERVAL_MS);
    },
    [t, toast],
  );

  // Load app list
  const loadApps = useCallback(async () => {
    setLoadingApps(true);
    try {
      const data = await api.listApps();
      setApps(data.apps);
    } catch {
      // Show nothing — user may not have any apps yet
      setApps([]);
    } finally {
      setLoadingApps(false);
    }
  }, []);

  const handleBuild = useCallback(
    async (includeAutomation: boolean) => {
      const p = prompt.trim();
      if (!p) return;

      setPhase("building");
      setBuildSteps([]);
      setSpec(null);
      setResult(null);
      setBuildProgress(0);
      setBuildCurrentStep("initializing");

      try {
        // POST /apps returns immediately with {id, status, progress, current_step}
        const resp = await api.createApp(p, includeAutomation);
        setCurrentAppId(resp.id);
        // Start polling for real progress
        startPolling(resp.id);
      } catch (err) {
        setPhase("error");
        toast(t("error.buildFailed"), "err");
      }
    },
    [prompt, t, toast, startPolling],
  );

  const handleRetry = useCallback(async () => {
    if (!currentAppId) return;
    setPhase("building");
    setBuildSteps([]);
    setSpec(null);
    setResult(null);
    setBuildProgress(0);
    setBuildCurrentStep("initializing");

    try {
      await api.retryApp(currentAppId);
      startPolling(currentAppId);
    } catch (err) {
      setPhase("error");
      toast(t("error.buildFailed"), "err");
    }
  }, [currentAppId, t, toast, startPolling]);

  const handleModify = useCallback(
    async (modPrompt: string) => {
      if (!currentAppId) return;
      setPhase("building");
      setBuildProgress(0);
      setBuildCurrentStep("applying changes");
      try {
        const data = await api.modifyApp(currentAppId, modPrompt);
        setResult(data.result);
        if (data.result.steps.length > 0) {
          setBuildSteps(data.result.steps);
        }
        setBuildProgress(100);
        setPhase("done");
        toast("App updated successfully", "ok");
      } catch {
        setPhase("done");
        toast(t("error.modifyFailed"), "err");
      }
    },
    [currentAppId, t, toast],
  );

  const handleOpenDesign = useCallback(() => {
    setPage("design");
  }, [setPage]);

  const handleNewApp = useCallback(() => {
    if (pollRef.current !== null) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    setPhase("idle");
    setSpec(null);
    setResult(null);
    setBuildSteps([]);
    setBuildProgress(0);
    setBuildCurrentStep("initializing");
    setPrompt("");
    setCurrentAppId(null);
  }, []);

  // Load app list on first render
  if (apps === null && !loadingApps) {
    void loadApps();
  }

  return (
    <div
      style={{
        maxWidth: 860,
        margin: "0 auto",
        padding: "40px 24px 80px",
        minHeight: "100%",
      }}
    >
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>

      {/* Page header */}
      <div style={{ marginBottom: 32 }}>
        <h1
          style={{
            fontSize: 28,
            fontWeight: 800,
            color: "var(--t1)",
            margin: 0,
            letterSpacing: "-0.02em",
          }}
        >
          {t("title")}
        </h1>
        <p style={{ fontSize: 15, color: "var(--t2)", marginTop: 6 }}>
          {t("subtitle")}
        </p>
      </div>

      {/* Prompt panel — visible when idle or after an error */}
      {(phase === "idle" || phase === "error") && (
        <div
          style={{
            background: "var(--bg-card)",
            border: "1px solid var(--b1)",
            borderRadius: 16,
            padding: "28px 28px 24px",
          }}
        >
          <p
            style={{
              fontSize: 13,
              fontWeight: 600,
              color: "var(--t2)",
              marginBottom: 12,
              textTransform: "uppercase",
              letterSpacing: "0.06em",
            }}
          >
            {t("inputPlaceholder").split(".")[0]}
          </p>

          <textarea
            ref={textareaRef}
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
                e.preventDefault();
                void handleBuild(false);
              }
            }}
            placeholder={t("inputPlaceholder")}
            rows={4}
            style={{
              width: "100%",
              padding: "14px 16px",
              border: "1px solid var(--b1)",
              borderRadius: 10,
              background: "var(--bg-input)",
              color: "var(--t1)",
              fontSize: 15,
              resize: "vertical",
              outline: "none",
              fontFamily: "inherit",
              boxSizing: "border-box",
              transition: "border-color 0.15s",
            }}
            onFocus={(e) => (e.target.style.borderColor = "var(--accent)")}
            onBlur={(e) => (e.target.style.borderColor = "var(--b1)")}
          />

          <div
            style={{
              display: "flex",
              gap: 10,
              marginTop: 14,
              flexWrap: "wrap",
              alignItems: "center",
            }}
          >
            <button
              onClick={() => void handleBuild(false)}
              disabled={!prompt.trim()}
              style={{
                padding: "11px 24px",
                background: "var(--accent)",
                color: "#fff",
                border: "none",
                borderRadius: 9,
                fontSize: 14,
                fontWeight: 600,
                cursor: prompt.trim() ? "pointer" : "not-allowed",
                opacity: prompt.trim() ? 1 : 0.5,
              }}
            >
              {t("buildApp")}
            </button>
            <button
              onClick={() => void handleBuild(true)}
              disabled={!prompt.trim()}
              style={{
                padding: "11px 24px",
                background: "transparent",
                color: "var(--accent)",
                border: "1.5px solid var(--accent)",
                borderRadius: 9,
                fontSize: 14,
                fontWeight: 600,
                cursor: prompt.trim() ? "pointer" : "not-allowed",
                opacity: prompt.trim() ? 1 : 0.5,
              }}
            >
              {t("buildAutomate")}
            </button>
            <span style={{ fontSize: 12, color: "var(--t3)" }}>
              Ctrl+Enter to build
            </span>
          </div>

          {/* Examples */}
          <div style={{ marginTop: 20 }}>
            <p
              style={{
                fontSize: 11,
                fontWeight: 600,
                color: "var(--t3)",
                textTransform: "uppercase",
                letterSpacing: "0.08em",
                marginBottom: 8,
              }}
            >
              {t("examples")}
            </p>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
              {Array.isArray(examples) &&
                examples.map((ex, i) => (
                  <button
                    key={i}
                    onClick={() => setPrompt(ex)}
                    style={{
                      padding: "6px 14px",
                      fontSize: 12,
                      background: "var(--bg-hover)",
                      border: "1px solid var(--b1)",
                      borderRadius: 20,
                      color: "var(--t2)",
                      cursor: "pointer",
                      transition: "all 0.15s",
                    }}
                    onMouseEnter={(e) => {
                      const el = e.currentTarget;
                      el.style.borderColor = "var(--accent)";
                      el.style.color = "var(--accent)";
                    }}
                    onMouseLeave={(e) => {
                      const el = e.currentTarget;
                      el.style.borderColor = "var(--b1)";
                      el.style.color = "var(--t2)";
                    }}
                  >
                    {ex}
                  </button>
                ))}
            </div>
          </div>
        </div>
      )}

      {/* Build progress — shown while polling or after completion before result renders */}
      {phase === "building" && (
        <BuildProgressPanel
          steps={buildSteps}
          phase={phase}
          progress={buildProgress}
          currentStep={buildCurrentStep}
        />
      )}

      {/* App preview after a successful (ready/partial) build */}
      {phase === "done" && spec && result && (
        <AppPreviewPanel
          spec={spec}
          result={result}
          onOpenDesign={handleOpenDesign}
          onModify={handleModify}
          onNewApp={handleNewApp}
          onRetry={
            result.status === "partial" || result.status === "failed"
              ? handleRetry
              : undefined
          }
        />
      )}

      {/* Existing apps list — shown in idle / error state */}
      {(phase === "idle" || phase === "error") && (
        <div style={{ marginTop: 40 }}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              marginBottom: 16,
            }}
          >
            <h2 style={{ fontSize: 16, fontWeight: 600, color: "var(--t1)", margin: 0 }}>
              {t("myApps")}
            </h2>
            {apps && apps.length > 0 && (
              <button
                onClick={loadApps}
                style={{
                  fontSize: 12,
                  color: "var(--t3)",
                  background: "none",
                  border: "none",
                  cursor: "pointer",
                }}
              >
                Refresh
              </button>
            )}
          </div>

          {loadingApps ? (
            <div style={{ color: "var(--t3)", fontSize: 14, padding: "20px 0" }}>
              Loading apps…
            </div>
          ) : apps && apps.length > 0 ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {apps.map((app) => (
                <AppCard
                  key={app.id}
                  app={app}
                  onSelect={(id) => {
                    setCurrentAppId(id);
                  }}
                />
              ))}
            </div>
          ) : (
            <div
              style={{
                textAlign: "center",
                padding: "40px 20px",
                color: "var(--t3)",
                fontSize: 14,
                border: "1px dashed var(--b1)",
                borderRadius: 12,
              }}
            >
              <div style={{ fontSize: 32, marginBottom: 12 }}>🏗️</div>
              <p style={{ margin: 0 }}>
                No apps yet — describe what you want to build above!
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
