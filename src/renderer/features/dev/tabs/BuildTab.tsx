/**
 * BuildTab — AI-driven code generation panel.
 * Handles streaming build via /api/build/stream.
 * All API calls go through the shared apiFetch/parseJSON layer.
 */
import { useRef } from "react";
import { authH, API, parseJSON } from "../../../shared/utils/api";
import { StatusBadge } from "../../../components/ui/StatusBadge";
import { S } from "../../../styles/theme";
import { BUILD_TEMPLATES } from "../../../constants";
import type { BuildFile, BuildState, Project } from "../../../shared/types";

interface BuildTabProps {
  projects:       Project[];
  projectId:      string;
  buildPrompt:    string;
  buildState:     BuildState;
  status:         string;
  description:    string;
  onProjectId:    (id: string) => void;
  onPrompt:       (p: string) => void;
  onStateChange:  (s: BuildState) => void;
  onStatus:       (s: string) => void;
  onDescription:  (d: string) => void;
  onFileAppend:   (f: BuildFile) => void;
  onBuildDone:    (files: BuildFile[]) => void;
  onSwitchTab:    (tab: string) => void;
  onOpenPreview:  (files: BuildFile[]) => void;
  onToast:        (m: string, k?: "ok" | "err" | "info") => void;
}

export function BuildTab({
  projectId, buildPrompt, buildState, status, description,
  onPrompt, onStateChange, onStatus, onDescription,
  onFileAppend, onBuildDone, onSwitchTab, onOpenPreview, onToast,
}: BuildTabProps) {
  const abortRef = useRef<AbortController | null>(null);

  const build = async () => {
    if (!buildPrompt.trim() || buildState === "building") return;
    onStateChange("building");
    onStatus("Connecting to Claude…");
    onDescription("");
    const accumulated: BuildFile[] = [];

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const res = await fetch(`${API}/api/build/stream`, {
        method: "POST",
        headers: authH(),
        body: JSON.stringify({ project_id: projectId, prompt: buildPrompt }),
        signal: controller.signal,
      });

      if (!res.ok || !res.body) {
        const errBody = await parseJSON<{ detail?: string }>(res, "/api/build/stream").catch(() => ({}));
        throw new Error((errBody as { detail?: string }).detail ?? `HTTP ${res.status}`);
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split("\n");
        buf = lines.pop() ?? "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          let ev: Record<string, unknown>;
          try { ev = JSON.parse(line.slice(6)); } catch { continue; }

          if (ev.type === "status") {
            onStatus(ev.message as string);
          } else if (ev.type === "file") {
            const f = { path: ev.path as string, content: ev.content as string };
            accumulated.push(f);
            onFileAppend(f);
            onStatus(`Writing ${ev.path}…`);
          } else if (ev.type === "done") {
            onDescription(ev.description as string);
            onStateChange("done");
            onStatus(`Built ${(ev.files as unknown[]).length} files`);
            onBuildDone(accumulated);
            onToast(`Built: ${(ev.description as string) || `${(ev.files as unknown[]).length} files`}`);
            onSwitchTab("files");
            if (accumulated.some(f => f.path.endsWith(".html"))) {
              setTimeout(() => onOpenPreview(accumulated), 100);
            }
          } else if (ev.type === "error") {
            onStateChange("error");
            onStatus(`Error: ${ev.message}`);
            onToast(ev.message as string, "err");
          }
          // heartbeat: no-op
        }
      }
    } catch (err: unknown) {
      if ((err as Error).name !== "AbortError") {
        onStateChange("error");
        onStatus(`Error: ${(err as Error).message}`);
      } else {
        onStateChange("idle");
        onStatus("");
      }
    }
  };

  const stop = () => abortRef.current?.abort();

  return (
    <div style={{ flex: 1, overflowY: "auto", padding: 24 }}>
      <div style={{ maxWidth: 640, display: "flex", flexDirection: "column", gap: 14 }}>
        <div>
          <label style={S.label}>What do you want to build?</label>
          <textarea
            value={buildPrompt}
            onChange={e => onPrompt(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter" && e.ctrlKey) void build(); }}
            placeholder={"Describe your app in detail…\n\nCtrl+Enter to build"}
            style={{ ...S.textInput, minHeight: 140, resize: "vertical", fontFamily: "inherit" }}
            aria-label="Build prompt"
          />
        </div>

        <button
          onClick={buildState === "building" ? stop : () => void build()}
          disabled={!buildPrompt.trim() && buildState !== "building"}
          style={{ ...S.btnPrimary, flex: 1 }}
          aria-label={buildState === "building" ? "Stop build" : "Generate app"}
        >
          {buildState === "building" ? "⏹ Stop" : "✦ Generate"}
        </button>

        {buildState === "error" && status && (
          <div style={S.errorPanel}>
            <div style={S.errorPanelTitle}>⚠ Build error</div>
            {status.replace(/^Error:\s*/, "")}
          </div>
        )}

        {buildState === "building" && status && (
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <StatusBadge kind="info" label="Building" />
            <span style={{ fontSize: 12, color: "#34d399" }}>{status}</span>
          </div>
        )}

        {description && (
          <div style={{ ...S.muted, background: "rgba(255,255,255,.03)", borderRadius: 10, padding: 12 }}>
            {description}
          </div>
        )}

        <div>
          <label style={S.label}>TEMPLATES</label>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 8 }}>
            {BUILD_TEMPLATES.map(t => (
              <button
                key={t.label}
                onClick={() => onPrompt(t.prompt)}
                style={{ ...S.btnSecondary, fontSize: 12 }}
              >{t.label}</button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
