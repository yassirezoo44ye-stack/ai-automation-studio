/**
 * DevWorkspace — Developer Workspace shell.
 *
 * Orchestrates shared state across Build / Files / Preview / Run / Package tabs.
 * Tab implementations live in ./tabs/; each is independently focused.
 * The "design" tab has been removed — Design Studio is a first-class nav destination.
 */
import { useState, useEffect, useCallback } from "react";
import { useToast } from "../../contexts/ToastContext";
import { apiFetch, parseJSON, authH } from "../../utils/api";
import { StatusBadge } from "../../components/ui/StatusBadge";
import { S } from "../../styles/theme";
import type { Project, BuildFile, BuildState } from "../../types";

import { BuildTab }   from "./tabs/BuildTab";
import { FilesTab }   from "./tabs/FilesTab";
import { PreviewTab } from "./tabs/PreviewTab";
import { RunTab }     from "./tabs/RunTab";
import { PackageTab } from "./tabs/PackageTab";

type DevTab = "generate" | "files" | "preview" | "run" | "package";
type RunErrorType = Parameters<typeof RunTab>[0]["runError"];

function isHtml(fs: { path: string }[]) {
  return fs.some(f => f.path.endsWith(".html"));
}

export function DevWorkspace() {
  const toast = useToast();
  const [tab, setTab] = useState<DevTab>("generate");

  // ── Project ───────────────────────────────────────────────────────────────
  const [projects, setProjects]   = useState<Project[]>([]);
  const [projectId, setProjectId] = useState("demo");

  // ── Build ─────────────────────────────────────────────────────────────────
  const [buildPrompt, setBuildPrompt]  = useState("");
  const [buildState, setBuildState]    = useState<BuildState>("idle");
  const [buildStatus, setBuildStatus]  = useState("");
  const [description, setDescription] = useState("");
  const [files, setFiles]              = useState<BuildFile[]>([]);
  const [existingFiles, setExistingFiles] = useState<{ path: string; size: number }[]>([]);
  const [activeFile, setActiveFile]    = useState<BuildFile | null>(null);

  // ── Preview / Run ─────────────────────────────────────────────────────────
  const [previewUrl, setPreviewUrl]    = useState<string | null>(null);
  const [runCmd, setRunCmd]            = useState("");
  const [runOutput, setRunOutput]      = useState("");
  const [running, setRunning]          = useState(false);
  const [runError, setRunError]        = useState<RunErrorType>(null);

  useEffect(() => {
    apiFetch("/api/projects")
      .then(r => parseJSON<Project[]>(r, "/api/projects"))
      .then(setProjects)
      .catch(() => {});
  }, []);

  useEffect(() => {
    const path = `/api/projects/${projectId}/files`;
    apiFetch(path)
      .then(r => parseJSON<{ files?: { path: string; size: number }[] }>(r, path))
      .then(d => setExistingFiles(d.files ?? []))
      .catch(() => {});
  }, [projectId]);

  const clearWorkspace = async () => {
    if (!confirm("Clear all files in this workspace?")) return;
    await apiFetch(`/api/projects/${projectId}/files`, { method: "DELETE" });
    setFiles([]); setExistingFiles([]); setActiveFile(null);
    setRunOutput(""); setRunCmd(""); setRunError(null);
    if (previewUrl) { URL.revokeObjectURL(previewUrl); setPreviewUrl(null); }
    toast("Workspace cleared");
  };

  const downloadZip = async () => {
    const r = await apiFetch(`/api/projects/${projectId}/download`);
    if (!r.ok) return;
    const blob = await r.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "project.zip";
    a.click();
  };

  const openHtmlPreview = useCallback((fs: BuildFile[]) => {
    const html = fs.find(f => f.path === "index.html") ?? fs.find(f => f.path.endsWith(".html"));
    if (!html?.content) return;
    const blob = new Blob([html.content], { type: "text/html" });
    const url  = URL.createObjectURL(blob);
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setPreviewUrl(url);
    setTab("preview");
  }, [previewUrl]);

  const handleFileSelect = async (f: { path: string; content?: string }) => {
    if (f.content !== undefined) {
      setActiveFile(f as BuildFile);
      setTab("files");
      return;
    }
    const ep = `/api/projects/${projectId}/files/${f.path}`;
    try {
      const r = await apiFetch(ep);
      const d = await parseJSON<{ path: string; content: string }>(r, ep);
      setActiveFile({ path: d.path, content: d.content });
      setTab("files");
    } catch {}
  };

  const allFiles = buildState === "done"
    ? files
    : existingFiles.map(f => ({ path: f.path, content: "" }));

  const TABS: [DevTab, string][] = [
    ["generate", "Generate"],
    ["files",    `Files${allFiles.length ? ` (${allFiles.length})` : ""}`],
    ["preview",  "Preview"],
    ["run",      "Run"],
    ["package",  "Package"],
  ];

  return (
    <>
      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <header style={S.header}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={S.headerTitle}>Dev Workspace</span>
          {buildState === "building" && <StatusBadge kind="info"    label="Building…"   />}
          {buildState === "done"     && <StatusBadge kind="success"  label="Built"       />}
          {buildState === "error"    && <StatusBadge kind="error"    label="Build failed" />}
          {running                   && <StatusBadge kind="warning"  label="Running"     />}
        </div>

        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <select
            value={projectId}
            onChange={e => setProjectId(e.target.value)}
            style={{ ...S.projectSelect, width: "auto" }}
            aria-label="Active project"
          >
            <option value="demo">Demo Project</option>
            {projects
              .filter(p => p.id !== "00000000-0000-0000-0000-000000000001")
              .map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>

          {allFiles.length > 0 && (
            <>
              <button onClick={downloadZip}   style={{ ...S.btnSecondary, fontSize: 12, padding: "6px 12px" }}>⬇ ZIP</button>
              <button onClick={clearWorkspace} style={{ ...S.btnSecondary, fontSize: 12, padding: "6px 12px" }}>🗑 Clear</button>
            </>
          )}
        </div>
      </header>

      {/* ── Tab bar ────────────────────────────────────────────────────────── */}
      <nav
        style={{ display: "flex", borderBottom: "1px solid rgba(255,255,255,0.06)", background: "rgba(0,0,0,0.2)", padding: "0 16px" }}
        role="tablist"
        aria-label="Dev workspace tabs"
      >
        {TABS.map(([id, label]) => (
          <button
            key={id}
            role="tab"
            aria-selected={tab === id}
            onClick={() => setTab(id)}
            style={{
              padding: "10px 16px", background: "none", border: "none", cursor: "pointer",
              fontSize: 12, fontWeight: 500, transition: "color .15s, border-color .15s",
              borderBottom: tab === id ? "2px solid var(--accent-2)" : "2px solid transparent",
              color: tab === id ? "var(--t1)" : "var(--t4)",
            }}
          >{label}</button>
        ))}
      </nav>

      {/* ── Tab content ────────────────────────────────────────────────────── */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        {tab === "generate" && (
          <BuildTab
            projects={projects}
            projectId={projectId}
            buildPrompt={buildPrompt}
            buildState={buildState}
            status={buildStatus}
            description={description}
            onProjectId={setProjectId}
            onPrompt={setBuildPrompt}
            onStateChange={setBuildState}
            onStatus={setBuildStatus}
            onDescription={setDescription}
            onFileAppend={f => setFiles(p => [...p, f])}
            onBuildDone={fs => { setFiles(fs); setExistingFiles([]); }}
            onSwitchTab={setTab as (t: string) => void}
            onOpenPreview={openHtmlPreview}
            onToast={(m, k) => toast(m, k)}
          />
        )}

        {tab === "files" && (
          <FilesTab
            files={allFiles}
            activeFile={activeFile}
            onSelect={handleFileSelect}
          />
        )}

        {tab === "preview" && (
          <PreviewTab
            previewUrl={previewUrl}
            canOpenPreview={isHtml(allFiles)}
            onOpenPreview={() => openHtmlPreview(files)}
          />
        )}

        {tab === "run" && (
          <RunTab
            projectId={projectId}
            files={files}
            runCmd={runCmd}
            runOutput={runOutput}
            running={running}
            runError={runError}
            onCmd={setRunCmd}
            onOutput={setRunOutput as Parameters<typeof RunTab>[0]["onOutput"]}
            onRunning={setRunning}
            onError={setRunError}
            onPreviewUrl={url => setPreviewUrl(url)}
            onSwitchTab={setTab as (t: string) => void}
            currentPreviewUrl={previewUrl}
          />
        )}

        {tab === "package" && (
          <PackageTab
            projects={projects}
            projectId={projectId}
            onToast={(m, k) => toast(m, k)}
          />
        )}
      </div>
    </>
  );
}
