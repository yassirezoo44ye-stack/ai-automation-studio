/**
 * DevWorkspace — Developer Workspace shell.
 *
 * Orchestrates shared state across Build / Files / Preview / Run / Package tabs.
 * Tab implementations live in ./tabs/; each is independently focused.
 * The "design" tab has been removed — Design Studio is a first-class nav destination.
 */
import { useState, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { useToast } from "../../contexts/toast";
import { apiFetch, parseJSON } from "../../utils/api";
import { StatusBadge } from "../../components/ui/StatusBadge";
import { S } from "../../styles/theme";
import { GoldButton } from "../../shared/ui/gold";
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
  const { t } = useTranslation("dev");
  const toast = useToast();
  const [tab, setTab] = useState<DevTab>("generate");

  // ── Project ───────────────────────────────────────────────────────────────
  const [projects, setProjects]   = useState<Project[]>([]);
  // Prefer the last project used by AppBuilderPage (stored on project create).
  // Fall back to "demo" so the workspace still mounts when no project exists yet.
  const [projectId, setProjectId] = useState(
    () => sessionStorage.getItem("flow_active_project") ?? "demo",
  );

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
      .then(list => {
        setProjects(list);
        // If the sessionStorage id doesn't match any real project, fall back
        // to the most-recently-created one so the workspace isn't stuck on
        // a stale or deleted project.
        const stored = sessionStorage.getItem("flow_active_project");
        if (stored && !list.find(p => p.id === stored)) {
          const fallback = list[0]?.id ?? "demo";
          setProjectId(fallback);
          if (fallback !== "demo") {
            sessionStorage.setItem("flow_active_project", fallback);
          } else {
            sessionStorage.removeItem("flow_active_project");
          }
        }
      })
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
    if (!confirm(t("header.confirmClear"))) return;
    await apiFetch(`/api/projects/${projectId}/files`, { method: "DELETE" });
    setFiles([]); setExistingFiles([]); setActiveFile(null);
    setRunOutput(""); setRunCmd(""); setRunError(null);
    if (previewUrl) { URL.revokeObjectURL(previewUrl); setPreviewUrl(null); }
    toast(t("header.toastCleared"));
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
    // content stays undefined (not "") — handleFileSelect's `f.content !==
    // undefined` guard uses this to tell "already loaded" from "needs a
    // fetch"; an empty string satisfied that check too, so every file from
    // a previously-generated project showed permanently blank on click.
    : existingFiles.map(f => ({ path: f.path, content: undefined as string | undefined }));

  // Flow order: Generate → Preview → Files → Terminal → Package
  const TABS: [DevTab, string][] = [
    ["generate", t("tabs.generate")],
    ["preview",  t("tabs.preview")],
    ["files",    allFiles.length ? t("tabs.filesWithCount", { count: allFiles.length }) : t("tabs.files")],
    ["run",      t("tabs.run")],
    ["package",  t("tabs.package")],
  ];

  return (
    <>
      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <header style={S.header}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={S.headerTitle}>{t("header.title")}</span>
          {buildState === "building" && <StatusBadge kind="info"    label={t("header.status.building")}   />}
          {buildState === "done"     && <StatusBadge kind="success"  label={t("header.status.built")}       />}
          {buildState === "error"    && <StatusBadge kind="error"    label={t("header.status.buildFailed")} />}
          {running                   && <StatusBadge kind="warning"  label={t("header.status.running")}     />}
        </div>

        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <select
            value={projectId}
            onChange={e => {
              const id = e.target.value;
              setProjectId(id);
              // Keep the global "active project" in sync so that AgentOS
              // CommandTerminal automatically picks up the project context.
              if (id && id !== "demo") {
                sessionStorage.setItem("flow_active_project", id);
              } else {
                sessionStorage.removeItem("flow_active_project");
              }
            }}
            className="g-input" style={{ width: "auto" }}
            aria-label={t("header.activeProjectLabel")}
          >
            <option value="demo">{t("header.demoProject")}</option>
            {projects
              .filter(p => p.id !== "00000000-0000-0000-0000-000000000001")
              .map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>

          {allFiles.length > 0 && (
            <>
              <GoldButton variant="ghost" onClick={downloadZip}   style={{ fontSize: 12, padding: "6px 12px" }}>{t("header.downloadZip")}</GoldButton>
              <GoldButton variant="ghost" onClick={clearWorkspace} style={{ fontSize: 12, padding: "6px 12px" }}>{t("header.clearWorkspace")}</GoldButton>
            </>
          )}
        </div>
      </header>

      {/* ── Tab bar ────────────────────────────────────────────────────────── */}
      {/* <nav> carrying role="tablist" is intentional — a landmark element
          grouping the role="tab" buttons below; not a real a11y issue. */}
      <nav
        style={{ display: "flex", borderBottom: "1px solid var(--border)", background: "var(--bg-hover)", padding: "0 16px" }}
        // eslint-disable-next-line jsx-a11y/no-noninteractive-element-to-interactive-role
        role="tablist"
        aria-label={t("tabsAriaLabel")}
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
            files={files}
            onProjectId={setProjectId}
            onPrompt={setBuildPrompt}
            onStateChange={setBuildState}
            onStatus={setBuildStatus}
            onDescription={setDescription}
            onFileAppend={f => setFiles(p => [...p, f])}
            onBuildDone={fs => { setFiles(fs); setExistingFiles([]); }}
            onSwitchTab={setTab as (t: string) => void}
            onOpenPreview={openHtmlPreview}
            onExportZip={downloadZip}
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
            hasFiles={allFiles.length > 0}
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
