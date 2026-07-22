/**
 * RunTab — streaming execution console.
 * Handles run/stop lifecycle, error display, and server-preview detection.
 */
import { useRef } from "react";
import { apiFetch, authH } from "../../../shared/utils/api";
import { GoldButton } from "../../../shared/ui/gold";
import type { BuildFile } from "../../../shared/types";

interface RunError {
  category: string;
  message:  string;
  fix:      string[];
  severity: "low" | "medium" | "high";
}

interface RunTabProps {
  projectId:    string;
  files:        BuildFile[];
  hasFiles:     boolean;
  runCmd:       string;
  runOutput:    string;
  running:      boolean;
  runError:     RunError | null;
  onCmd:        (c: string) => void;
  onOutput:     (o: string | ((p: string) => string)) => void;
  onRunning:    (r: boolean) => void;
  onError:      (e: RunError | null) => void;
  onPreviewUrl: (url: string) => void;
  onSwitchTab:  (tab: string) => void;
  currentPreviewUrl: string | null;
}

const SEVERITY_COLOR: Record<string, string> = {
  high:   "var(--red)",
  medium: "var(--yellow)",
  low:    "var(--t4)",
};

export function RunTab({
  projectId, files, hasFiles, runCmd, runOutput, running, runError,
  onCmd, onOutput, onRunning, onError, onPreviewUrl, onSwitchTab, currentPreviewUrl,
}: RunTabProps) {
  const abortRef = useRef<AbortController | null>(null);

  const run = async () => {
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    onRunning(true);
    onOutput("▶ Starting…\n");
    onError(null);
    onSwitchTab("run");

    try {
      if (files.length > 0) {
        await apiFetch(`/api/projects/${projectId}/sync`, {
          method: "POST",
          headers: authH(),
          body: JSON.stringify({ files }),
        });
      }

      const res = await apiFetch(`/api/projects/${projectId}/run/stream`, {
        method: "POST",
        headers: authH(),
        body: JSON.stringify({ command: runCmd || null }),
        signal: ctrl.signal,
      });

      if (!res.ok || !res.body) {
        onOutput(`Error: HTTP ${res.status}`);
        onRunning(false);
        return;
      }

      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let buf = "";
      const append = (line: string) => onOutput(prev => (typeof prev === "string" ? prev : "") + line + "\n");

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const lines = buf.split("\n");
        buf = lines.pop() ?? "";

        for (const raw of lines) {
          if (!raw.startsWith("data: ")) continue;
          let ev: Record<string, unknown>;
          try { ev = JSON.parse(raw.slice(6)); } catch { continue; }

          switch (ev.type) {
            case "status": append(ev.message as string); break;
            case "log":    append(`${ev.stream === "stderr" ? "⚠ " : ""}${ev.line}`); break;
            case "html": {
              const blob = new Blob([ev.html_content as string], { type: "text/html" });
              const url = URL.createObjectURL(blob);
              onPreviewUrl(url);
              onSwitchTab("preview");
              onRunning(false);
              return;
            }
            case "server_ready": {
              const proxyUrl = ev.preview_url as string;
              onPreviewUrl(proxyUrl);
              append(`✓ ${ev.message}\n🌐 Preview: ${proxyUrl}`);
              onSwitchTab("preview");
              onRunning(false);
              return;
            }
            case "done": {
              const parts: string[] = [];
              if (ev.command) parts.push(`$ ${ev.command}`);
              if (ev.stdout)  parts.push(String(ev.stdout).trimEnd());
              if (ev.stderr)  parts.push(`\nstderr:\n${String(ev.stderr).trimEnd()}`);
              parts.push(`\n[exit ${ev.exit_code}]  (${ev.duration}s)`);
              onOutput(parts.join("\n"));
              onRunning(false);
              return;
            }
            case "error": {
              const fix: string[] = Array.isArray(ev.fix) ? ev.fix : ev.hint ? [ev.hint as string] : [];
              onError({
                category: String(ev.category ?? "execution"),
                message:  String(ev.message ?? ev.error ?? "Unknown error"),
                fix,
                severity: (ev.severity as "low" | "medium" | "high") ?? "high",
              });
              onRunning(false);
              return;
            }
            case "unsupported": {
              const hint = ev.local_run_hint ?? ev.details ?? "";
              onError({
                category: "unsupported",
                message:  String(ev.message ?? ev.error ?? "Project type not supported"),
                fix:      [String(hint), "Download the ZIP to run locally"].filter(Boolean),
                severity: "medium",
              });
              onRunning(false);
              return;
            }
          }
        }
      }
    } catch (e: unknown) {
      if ((e as Error).name !== "AbortError") {
        onOutput(`Error: ${(e as Error).message}`);
      }
    } finally {
      onRunning(false);
    }
  };

  const stop = () => abortRef.current?.abort();

  // Empty workspace — guide the user to Generate instead of letting Run fail
  if (!hasFiles && !running && !runOutput) {
    return (
      <div style={{
        flex: 1, display: "flex", flexDirection: "column",
        alignItems: "center", justifyContent: "center", gap: 14, padding: 24,
      }}>
        <svg width="44" height="44" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.4" style={{ color: "var(--ta)" }}>
          <polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/>
        </svg>
        <div style={{ fontSize: 15, fontWeight: 600, color: "var(--t1)" }}>Nothing to run yet</div>
        <p style={{ fontSize: 13, color: "var(--t4)", maxWidth: 320, textAlign: "center", margin: 0, lineHeight: 1.6 }}>
          This workspace is empty. Generate a project first — the Terminal will
          auto-detect the right command and run it here.
        </p>
        <GoldButton onClick={() => onSwitchTab("generate")} style={{ padding: "9px 22px" }}>
          ✦ Go to Generate
        </GoldButton>
      </div>
    );
  }

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
      {/* Toolbar */}
      <div style={{
        padding: "8px 16px", borderBottom: "1px solid var(--border)",
        display: "flex", gap: 8, alignItems: "center", flexShrink: 0,
      }}>
        <span style={{ fontSize: 11, color: "var(--t5)", flexShrink: 0, fontFamily: "var(--font-mono)" }}>$</span>
        <input
          value={runCmd}
          onChange={e => onCmd(e.target.value)}
          onKeyDown={e => { if (e.key === "Enter") void run(); }}
          placeholder="auto-detect (or: python main.py)"
          style={{
            flex: 1, background: "none", border: "none",
            color: "var(--t2)", fontSize: 13, fontFamily: "var(--font-mono)", outline: "none",
          }}
          aria-label="Run command"
        />
        {running
          ? (
            <GoldButton variant="ghost" onClick={stop} style={{ padding: "5px 14px", fontSize: 12 }}>
              ⏹ Stop
            </GoldButton>
          ) : (
            <GoldButton onClick={() => void run()} style={{ padding: "5px 14px", fontSize: 12 }}>
              Run ▶
            </GoldButton>
          )
        }
        {currentPreviewUrl && !running && (
          <GoldButton
            variant="ghost"
            onClick={() => onSwitchTab("preview")}
            style={{ padding: "5px 12px", fontSize: 12 }}
          >🌐 Preview</GoldButton>
        )}
      </div>

      {/* Output — a terminal pane stays black-on-monospace regardless of app
          theme, matching every IDE/terminal convention (VS Code, iTerm, etc.);
          this is the same "fixed surface" exception as a code viewer or an
          arbitrary thumbnail, just for a different reason (terminal readability). */}
      <div style={{ flex: 1, overflow: "hidden", display: "flex", flexDirection: "column" }}>
        <pre style={{
          flex: 1, margin: 0, padding: "14px 18px", overflowY: "auto",
          fontSize: 12, color: "var(--green)", fontFamily: "var(--font-mono)",
          lineHeight: 1.5, whiteSpace: "pre-wrap", wordBreak: "break-all",
          background: "#040506",
        }}>
          {runOutput || "Output will appear here…"}
        </pre>

        {runError && (
          <div style={{
            borderTop: `2px solid ${SEVERITY_COLOR[runError.severity] ?? "var(--t4)"}`,
            background: "#0f0a0a", padding: "14px 18px", flexShrink: 0,
          }}>
            <div style={{ color: SEVERITY_COLOR[runError.severity], fontWeight: 600, fontSize: 13, marginBottom: 6 }}>
              ✗ {runError.message}
            </div>
            {runError.fix.length > 0 && (
              <div>
                <div style={{ color: "var(--t4)", fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 6 }}>
                  Fix Suggestions
                </div>
                {runError.fix.map((step, i) => (
                  <div key={i} style={{ display: "flex", gap: 8, marginBottom: 4, fontSize: 12, color: "var(--t2)" }}>
                    <span style={{ color: "var(--blue)", minWidth: 18 }}>{i + 1}.</span>
                    <span>{step}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
