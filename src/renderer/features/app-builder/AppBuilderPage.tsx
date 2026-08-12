/**
 * AI Business App Builder — main page.
 *
 * Three panels:
 *  1. PromptPanel   — chat input + examples
 *  2. BuildProgress — live build steps (shown during/after build)
 *  3. AppPreview    — build result summary with open/edit/publish actions
 *  4. AppList       — list of existing apps in the org
 */
import { useState, useRef, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { useAppContext } from "../../contexts/app";
import { useToast } from "../../contexts/toast";
import * as api from "./api";
import type { AppSpec, BuildResult, AppRecord, BuildPhase, BuildStep } from "./types";

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
  // pending
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

// ── Progress panel ─────────────────────────────────────────────────────────────

function BuildProgressPanel({
  steps,
  phase,
}: {
  steps: BuildStep[];
  phase: BuildPhase;
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
          marginBottom: 18,
        }}
      >
        {phase === "building" ? t("building") : t("steps.validating")}
      </p>
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
}: {
  spec: AppSpec;
  result: BuildResult;
  onOpenDesign: () => void;
  onModify: (prompt: string) => void;
  onNewApp: () => void;
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
            {isPartial ? t("warnings.title") : t("preview.title")}
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
      </div>

      {/* Inline modify input */}
      {showModify && (
        <div style={{ display: "flex", gap: 8 }}>
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
          <BuildProgressPanel steps={result.steps} phase="done" />
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
          {t(`status.${app.build_status}` as Parameters<typeof t>[0], app.build_status)}
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
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const examples = t("examplesList", { returnObjects: true }) as string[];

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

      // Simulate progressive steps while the real build runs
      const defaultLabels = [
        t("steps.understanding"),
        t("steps.database"),
        t("steps.backend"),
        t("steps.pages"),
        t("steps.permissions"),
        t("steps.workflows"),
        t("steps.validating"),
      ];
      const simulatedSteps: BuildStep[] = defaultLabels.map((label) => ({
        label,
        status: "pending",
        detail: "",
      }));
      setBuildSteps([...simulatedSteps]);

      // Animate each step as "running" then wait for API
      let stepIdx = 0;
      const stepTimer = setInterval(() => {
        if (stepIdx < simulatedSteps.length) {
          simulatedSteps[stepIdx].status = "ok";
          setBuildSteps([...simulatedSteps]);
          stepIdx++;
        } else {
          clearInterval(stepTimer);
        }
      }, 600);

      try {
        const data = await api.createApp(p, includeAutomation);
        clearInterval(stepTimer);
        setSpec(data.spec);
        setResult(data.result);
        setCurrentAppId(data.result.app_id);
        // Replace simulated steps with real ones
        if (data.result.steps.length > 0) {
          setBuildSteps(data.result.steps);
        } else {
          simulatedSteps.forEach((s) => (s.status = "ok"));
          setBuildSteps([...simulatedSteps]);
        }
        setPhase("done");
      } catch (err) {
        clearInterval(stepTimer);
        setPhase("error");
        toast(t("error.buildFailed"), "err");
        setBuildSteps((prev) =>
          prev.map((s, i) =>
            i === stepIdx
              ? { ...s, status: "error" }
              : s.status === "pending"
              ? s
              : s,
          ),
        );
      }
    },
    [prompt, t, toast],
  );

  const handleModify = useCallback(
    async (modPrompt: string) => {
      if (!currentAppId) return;
      setPhase("building");
      try {
        const data = await api.modifyApp(currentAppId, modPrompt);
        setResult(data.result);
        if (data.result.steps.length > 0) {
          setBuildSteps(data.result.steps);
        }
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
    setPhase("idle");
    setSpec(null);
    setResult(null);
    setBuildSteps([]);
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

      {/* Prompt panel — always visible when idle or error */}
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

      {/* Build progress */}
      {(phase === "building" || (phase === "done" && buildSteps.length > 0 && !result)) && (
        <BuildProgressPanel steps={buildSteps} phase={phase} />
      )}

      {/* App preview after successful build */}
      {phase === "done" && spec && result && (
        <AppPreviewPanel
          spec={spec}
          result={result}
          onOpenDesign={handleOpenDesign}
          onModify={handleModify}
          onNewApp={handleNewApp}
        />
      )}

      {/* Existing apps list */}
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
                    // Navigate to the app detail (for now, show it)
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
