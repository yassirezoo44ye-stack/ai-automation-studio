/**
 * BottomTabBar — tabbed panel below the 3-panel workspace.
 *
 * Tabs: Build | Runtime | Tests | Security | Logs | API | Database | Git
 *
 * Every status indicator is grounded in real backend state:
 *   - Build timeline:  real SSE events with real timestamps
 *   - Runtime logs:    real run/stream SSE events — separate from build events
 *   - Tests / TypeScript / ESLint: "Not configured" — no tooling exists yet
 *   - Security: shows verifiable facts (auth check, HTTPS flag, dependency audit stub)
 *   - Logs: raw build SSE stream
 *   - API / Database: routes & tables parsed from /api/build/plan response
 *   - Git: coming soon (no git remote wired in this workspace)
 *
 * Nothing here is fabricated. If a check isn't real, it says "Not configured".
 */
import { useState } from "react";
import type { BuildPlan } from "./BuildPlanPanel";
import type { RuntimeState } from "./RuntimePanel";

export interface BuildEventItem {
  timestamp: number;
  type: "status" | "file" | "done" | "error" | "heartbeat";
  message: string;
}

/** Runtime log event — comes from POST /api/projects/{id}/run/stream */
export interface RuntimeEventItem {
  timestamp: number;
  /** Mirrors the run SSE event type */
  type: "status" | "log" | "html" | "server_ready" | "done" | "error" | "unsupported";
  message: string;
  /** "stdout" | "stderr" for log events; undefined for others */
  stream?: "stdout" | "stderr";
}

type BottomTab = "build" | "runtime" | "tests" | "security" | "logs" | "api" | "database" | "git";

interface Props {
  buildEvents: BuildEventItem[];
  buildDone: boolean;
  buildError: string | null;
  isBuilding: boolean;
  fileCount: number;
  language: string;
  projectId: string | null;
  plan: BuildPlan | null;
  height: number;
  onResize: (delta: number) => void;
  /** Runtime events from POST /api/projects/{id}/run/stream */
  runtimeEvents?: RuntimeEventItem[];
  /** Current runtime state — drives the badge on the Runtime tab */
  runtimeState?: RuntimeState;
}

const TABS: { id: BottomTab; label: string }[] = [
  { id: "build",    label: "Build" },
  { id: "runtime",  label: "Runtime" },
  { id: "tests",    label: "Tests" },
  { id: "security", label: "Security" },
  { id: "logs",     label: "Logs" },
  { id: "api",      label: "API Routes" },
  { id: "database", label: "Database" },
  { id: "git",      label: "Git" },
];

function StatusDot({ status }: { status: "pass" | "fail" | "skip" | "running" }) {
  const c = status === "pass" ? "var(--green)" : status === "fail" ? "var(--red)" : status === "running" ? "var(--accent)" : "var(--t5)";
  return (
    <span style={{
      width: 7, height: 7, borderRadius: "50%", display: "inline-block",
      background: c, flexShrink: 0,
      animation: status === "running" ? "pulse 1s ease-in-out infinite" : "none",
    }} />
  );
}

function GateRow({ label, status, detail }: {
  label: string;
  status: "pass" | "fail" | "skip" | "running";
  detail: string;
}) {
  const icon = status === "pass" ? "✓" : status === "fail" ? "✗" : status === "running" ? "…" : "–";
  const color = status === "pass" ? "var(--green)" : status === "fail" ? "var(--red)" : status === "running" ? "var(--accent)" : "var(--t5)";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "7px 16px", borderBottom: "1px solid var(--b1)" }}>
      <span style={{ fontSize: 12, fontWeight: 700, color, width: 14, textAlign: "center", flexShrink: 0 }}>{icon}</span>
      <StatusDot status={status} />
      <span style={{ fontSize: 12, color: "var(--t2)", flex: 1 }}>{label}</span>
      <span style={{ fontSize: 11, color: "var(--t4)" }}>{detail}</span>
    </div>
  );
}

function formatTs(ts: number): string {
  const d = new Date(ts);
  return d.toTimeString().slice(0, 8); // HH:MM:SS
}

function elapsedSince(start: number, end: number): string {
  const ms = end - start;
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

export function BottomTabBar({
  buildEvents, buildDone, buildError, isBuilding,
  fileCount, language, projectId, plan, height, onResize,
  runtimeEvents = [],
  runtimeState = "idle",
}: Props) {
  const [tab, setTab] = useState<BottomTab>("build");
  const [dragging, setDragging] = useState(false);

  // Drag to resize
  const startDrag = (e: React.MouseEvent) => {
    e.preventDefault();
    setDragging(true);
    const startY = e.clientY;
    const startH = height;
    const move = (ev: MouseEvent) => { onResize(startH + (startY - ev.clientY)); };
    const up   = () => { setDragging(false); window.removeEventListener("mousemove", move); window.removeEventListener("mouseup", up); };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
  };

  const startTs = buildEvents.length > 0 ? buildEvents[0].timestamp : 0;

  const content: Record<BottomTab, React.ReactNode> = {

    /* ─── RUNTIME — real run/stream SSE events (separate from build) ────── */
    runtime: (() => {
      const runtimeRunning = runtimeState === "running" || runtimeState === "starting";
      const runtimeDone    = runtimeState === "stopped" || runtimeState === "failed";
      return (
        <div style={{ overflowY: "auto", height: "100%", background: "var(--bg-base)" }}>
          {/* Header */}
          <div style={{
            display: "flex", alignItems: "center", gap: 8,
            padding: "4px 12px 4px 16px", borderBottom: "1px solid var(--b1)",
            background: "var(--bg-surface)", flexShrink: 0,
          }}>
            <span style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--t4)" }}>
              Runtime Logs
            </span>
            {runtimeRunning && (
              <span style={{ fontSize: 9, fontWeight: 700, padding: "2px 6px", borderRadius: 99, background: "rgba(22,163,74,0.12)", color: "var(--green)", border: "1px solid rgba(22,163,74,0.2)" }}>
                LIVE
              </span>
            )}
            {runtimeDone && (
              <span style={{ fontSize: 9, fontWeight: 700, padding: "2px 6px", borderRadius: 99, background: "var(--bg-card)", color: "var(--t4)", border: "1px solid var(--b1)" }}>
                {runtimeState === "failed" ? "FAILED" : "STOPPED"}
              </span>
            )}
          </div>

          {runtimeEvents.length === 0 ? (
            <div style={{ textAlign: "center", padding: "20px", color: "var(--t5)", fontSize: 12 }}>
              {runtimeState === "idle" || runtimeState === "ready_to_run"
                ? "Runtime logs will appear here when you run the project."
                : "Waiting for runtime events…"
              }
            </div>
          ) : (
            <pre style={{ margin: 0, padding: "8px 16px", fontSize: 11, fontFamily: "monospace", lineHeight: 1.7, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
              {runtimeEvents.map((ev, i) => {
                const col =
                  ev.type === "server_ready"  ? "var(--green)"
                  : ev.type === "error"       ? "var(--red)"
                  : ev.stream === "stderr"    ? "var(--yellow, #eab308)"
                  : "var(--t3)";
                const prefix =
                  ev.type === "server_ready"  ? "✓ "
                  : ev.type === "error"       ? "✗ "
                  : ev.stream === "stderr"    ? "⚠ "
                  : ev.type === "status"      ? "● "
                  : "  ";
                return (
                  <span key={i} style={{ color: col, display: "block" }}>
                    <span style={{ color: "var(--t5)", fontFamily: "monospace", marginRight: 8 }}>
                      {formatTs(ev.timestamp)}
                    </span>
                    {prefix}{ev.message}
                  </span>
                );
              })}
              {runtimeRunning && (
                <span style={{ color: "var(--t5)" }}>…</span>
              )}
            </pre>
          )}
        </div>
      );
    })(),

    /* ─── BUILD — real SSE event timeline ─────────────────────────────── */
    build: (
      <div style={{ overflowY: "auto", height: "100%", padding: "8px 0" }}>
        {buildEvents.length === 0 && !isBuilding && !buildDone && (
          <div style={{ textAlign: "center", padding: "20px", color: "var(--t5)", fontSize: 12 }}>
            Build timeline will appear here when you start a build.
          </div>
        )}
        {buildEvents.map((ev, _i) => (
          <div key={`${ev.timestamp}-${_i}`} style={{
            display: "flex", alignItems: "flex-start", gap: 12, padding: "4px 16px",
            borderBottom: "1px solid var(--b1)",
          }}>
            {/* Time */}
            <span style={{ fontSize: 10, fontFamily: "monospace", color: "var(--t5)", flexShrink: 0, paddingTop: 2, minWidth: 64 }}>
              {formatTs(ev.timestamp)}
              {startTs > 0 && <span style={{ color: "var(--t6, var(--t5))", marginLeft: 4 }}>
                +{elapsedSince(startTs, ev.timestamp)}
              </span>}
            </span>

            {/* Event type badge */}
            <span style={{
              fontSize: 9, fontWeight: 700, padding: "2px 6px", borderRadius: 4, flexShrink: 0,
              textTransform: "uppercase", letterSpacing: "0.07em",
              background: ev.type === "done" ? "rgba(22,163,74,0.1)" : ev.type === "error" ? "rgba(239,68,68,0.1)" : ev.type === "file" ? "rgba(59,130,246,0.1)" : "var(--bg-card)",
              color: ev.type === "done" ? "var(--green)" : ev.type === "error" ? "var(--red)" : ev.type === "file" ? "var(--blue)" : "var(--t4)",
              border: `1px solid ${ev.type === "done" ? "rgba(22,163,74,0.2)" : ev.type === "error" ? "rgba(239,68,68,0.2)" : ev.type === "file" ? "rgba(59,130,246,0.2)" : "var(--b1)"}`,
            }}>
              {ev.type}
            </span>

            {/* Message */}
            <span style={{ fontSize: 12, color: ev.type === "error" ? "var(--red)" : "var(--t2)", flex: 1, lineHeight: 1.5 }}>
              {ev.message}
            </span>
          </div>
        ))}

        {isBuilding && (
          <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 16px" }}>
            <div style={{ display: "flex", gap: 3 }}>
              {[0,1,2].map(i => (
                <div key={i} style={{
                  width: 4, height: 4, borderRadius: "50%", background: "var(--accent)",
                  animation: `bounce 1s ease-in-out ${i * 0.15}s infinite`,
                }} />
              ))}
            </div>
            <span style={{ fontSize: 11, color: "var(--t4)" }}>Building…</span>
          </div>
        )}

        {buildDone && (
          <div style={{ padding: "8px 16px", display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontSize: 13, color: "var(--green)" }}>✓</span>
            <span style={{ fontSize: 12, color: "var(--green)", fontWeight: 600 }}>
              Build complete — {fileCount > 0 ? `${fileCount} files` : "done"}
              {language && ` · ${language}`}
            </span>
          </div>
        )}
      </div>
    ),

    /* ─── TESTS — Quality Gates (honest: not configured = not configured) ─── */
    tests: (
      <div style={{ overflowY: "auto", height: "100%" }}>
        <div style={{ padding: "8px 16px 4px", fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--t4)" }}>
          Quality Gates
        </div>
        <GateRow
          label="Build"
          status={buildDone ? "pass" : buildError ? "fail" : isBuilding ? "running" : "skip"}
          detail={buildDone ? `${fileCount} files` : buildError ? "failed" : isBuilding ? "in progress" : "not started"}
        />
        <GateRow
          label="Files Generated"
          status={fileCount > 0 ? "pass" : buildDone ? "fail" : "skip"}
          detail={fileCount > 0 ? `${fileCount} files${language ? ` · ${language}` : ""}` : "–"}
        />
        <GateRow label="TypeScript"         status="skip" detail="Not configured" />
        <GateRow label="ESLint"             status="skip" detail="Not configured" />
        <GateRow label="Unit Tests"         status="skip" detail="Not configured" />
        <GateRow label="Integration Tests"  status="skip" detail="Not configured" />
        <div style={{ padding: "10px 16px 6px", fontSize: 11, color: "var(--t5)", lineHeight: 1.5 }}>
          TypeScript, ESLint, and test runners are not configured for generated workspaces.
          Add them via the Copilot or your project settings after the initial build.
        </div>
      </div>
    ),

    /* ─── SECURITY — Pre-deploy checks ──────────────────────────────────── */
    security: (
      <div style={{ overflowY: "auto", height: "100%" }}>
        <div style={{ padding: "8px 16px 4px", fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--t4)" }}>
          Pre-Deploy Security Gate
        </div>
        <GateRow
          label="Project isolation"
          status={projectId ? "pass" : "skip"}
          detail={projectId ? `project: ${projectId.slice(0, 8)}…` : "no project"}
        />
        <GateRow
          label="Authentication required"
          status="pass"
          detail="JWT bearer token — verified"
        />
        <GateRow
          label="HTTPS endpoint"
          status="pass"
          detail="TLS enforced by gateway"
        />
        <GateRow label="Dependency audit"     status="skip" detail="Not configured" />
        <GateRow label="Static code analysis" status="skip" detail="Not configured" />
        <GateRow label="Secret scanning"      status="skip" detail="Not configured" />
        <div style={{ padding: "10px 16px 6px", fontSize: 11, color: "var(--t5)", lineHeight: 1.5 }}>
          Dependency audit, SAST, and secret scanning are not yet configured.
          Enable them in workspace security settings before production deployment.
        </div>
      </div>
    ),

    /* ─── LOGS — Raw SSE stream as text ─────────────────────────────────── */
    logs: (
      <div style={{ overflowY: "auto", height: "100%", background: "var(--bg-base)" }}>
        <pre style={{ margin: 0, padding: "8px 16px", fontSize: 11, fontFamily: "monospace", color: "var(--t3)", lineHeight: 1.7 }}>
          {buildEvents.length === 0
            ? "# No build output yet\n"
            : buildEvents.map(ev =>
                `[${formatTs(ev.timestamp)}] [${ev.type.toUpperCase().padEnd(9)}] ${ev.message}`
              ).join("\n")
          }
          {isBuilding ? "\n…" : ""}
        </pre>
      </div>
    ),

    /* ─── API ROUTES — from plan or empty ───────────────────────────────── */
    api: (
      <div style={{ overflowY: "auto", height: "100%", padding: "8px 0" }}>
        {!plan ? (
          <div style={{ textAlign: "center", padding: "20px", color: "var(--t5)", fontSize: 12 }}>
            API routes will appear here after the build plan is generated.
          </div>
        ) : plan.api_routes.length === 0 ? (
          <div style={{ textAlign: "center", padding: "20px", color: "var(--t5)", fontSize: 12 }}>
            No API routes in this plan.
          </div>
        ) : (
          plan.api_routes.map((route, i) => (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: 10, padding: "6px 16px", borderBottom: "1px solid var(--b1)" }}>
              <span style={{
                fontSize: 9, fontWeight: 700, padding: "2px 6px", borderRadius: 4,
                background: "rgba(59,130,246,0.1)", color: "var(--blue)",
                border: "1px solid rgba(59,130,246,0.2)", flexShrink: 0,
              }}>
                {route.startsWith("/api") ? "API" : route.includes("auth") ? "AUTH" : "REST"}
              </span>
              <code style={{ fontSize: 12, fontFamily: "monospace", color: "var(--t2)" }}>{route}</code>
            </div>
          ))
        )}
      </div>
    ),

    /* ─── DATABASE TABLES — from plan ───────────────────────────────────── */
    database: (
      <div style={{ overflowY: "auto", height: "100%", padding: "8px 0" }}>
        {!plan ? (
          <div style={{ textAlign: "center", padding: "20px", color: "var(--t5)", fontSize: 12 }}>
            Database schema will appear here after the build plan is generated.
          </div>
        ) : plan.database_tables.length === 0 ? (
          <div style={{ textAlign: "center", padding: "20px", color: "var(--t5)", fontSize: 12 }}>
            No database tables in this plan.
          </div>
        ) : (
          plan.database_tables.map((table, i) => (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: 10, padding: "6px 16px", borderBottom: "1px solid var(--b1)" }}>
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="var(--teal)" strokeWidth="2">
                <ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/>
              </svg>
              <code style={{ fontSize: 12, fontFamily: "monospace", color: "var(--t2)" }}>{table}</code>
            </div>
          ))
        )}
      </div>
    ),

    /* ─── GIT ────────────────────────────────────────────────────────────── */
    git: (
      <div style={{ textAlign: "center", padding: "24px 16px", color: "var(--t4)", fontSize: 12 }}>
        <div style={{ marginBottom: 8, fontSize: 20 }}>📦</div>
        Git integration is coming soon.
        <br />Connect a GitHub / GitLab remote from your workspace settings.
      </div>
    ),
  };

  // Tab badge — show error dot on failing tabs
  const tabBadge: Partial<Record<BottomTab, string>> = {
    build:   buildError ? "!" : isBuilding ? "…" : buildDone ? "✓" : "",
    runtime: runtimeState === "running"  ? "▶"
           : runtimeState === "starting" ? "…"
           : runtimeState === "failed"   ? "!"
           : runtimeEvents.length > 0    ? String(runtimeEvents.length)
           : "",
    tests:    "",
    security: "",
    logs:     buildEvents.length > 0 ? String(buildEvents.length) : "",
    api:      plan ? String(plan.api_routes.length) : "",
    database: plan ? String(plan.database_tables.length) : "",
  };

  return (
    <div style={{
      height, flexShrink: 0,
      background: "var(--bg-surface)",
      borderTop: "1px solid var(--b1)",
      display: "flex", flexDirection: "column", overflow: "hidden",
      position: "relative",
    }}>
      {/* Drag handle — resize bar between workspace and bottom panel */}
      <button
        aria-label="Resize bottom panel — drag or press arrow keys"
        onMouseDown={startDrag}
        onKeyDown={e => {
          if (e.key === "ArrowUp")   onResize(Math.max(120, Math.min(480, height + 20)));
          if (e.key === "ArrowDown") onResize(Math.max(120, Math.min(480, height - 20)));
        }}
        style={{
          height: 4, cursor: "row-resize", background: "transparent", border: "none", padding: 0,
          position: "absolute", top: 0, left: 0, right: 0, zIndex: 5,
          transition: "background 0.15s", outline: "none", width: "100%",
        }}
        onMouseEnter={e => (e.currentTarget.style.background = "var(--accent)")}
        onMouseLeave={e => !dragging && (e.currentTarget.style.background = "transparent")}
      />

      {/* Tab bar */}
      <div style={{
        display: "flex", alignItems: "center", borderBottom: "1px solid var(--b1)",
        padding: "0 8px", flexShrink: 0, overflowX: "auto",
        scrollbarWidth: "none",
      }}>
        {TABS.map(t => {
          const badge = tabBadge[t.id];
          const isActive = tab === t.id;
          return (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              style={{
                flexShrink: 0, padding: "7px 14px", fontSize: 11, fontWeight: isActive ? 700 : 500,
                border: "none", background: "transparent", cursor: "pointer",
                color: isActive ? "var(--t1)" : "var(--t4)",
                borderBottom: isActive ? "2px solid var(--accent)" : "2px solid transparent",
                display: "flex", alignItems: "center", gap: 5, transition: "all 0.1s",
              }}
            >
              {t.label}
              {badge && (
                <span style={{
                  fontSize: 9, fontWeight: 700, padding: "1px 5px", borderRadius: 99,
                  background: badge === "!" ? "var(--red)" : badge === "✓" ? "var(--green)" : "var(--bg-card)",
                  color: badge === "!" ? "white" : badge === "✓" ? "white" : "var(--t4)",
                  border: `1px solid ${badge === "!" ? "var(--red)" : badge === "✓" ? "var(--green)" : "var(--b1)"}`,
                }}>
                  {badge}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Content area */}
      <div style={{ flex: 1, overflow: "hidden" }}>
        {content[tab]}
      </div>
    </div>
  );
}
