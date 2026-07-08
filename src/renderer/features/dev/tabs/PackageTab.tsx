/**
 * PackageTab — app packaging / distribution.
 * Replaces the legacy AppPackager.tsx with a clean, service-backed implementation.
 * Uses /api/package/* endpoints and renders streaming build logs.
 */
import { useState, useRef, useEffect } from "react";
import { apiFetch, parseJSON, authH, API } from "../../../shared/utils/api";
import { S } from "../../../styles/theme";
import type { Project } from "../../../shared/types";

type PackTarget = "exe" | "apk" | "zip";
type PackLang   = "python" | "web" | "electron" | "docker";
type PackState  = "idle" | "building" | "done" | "error";

interface LogEntry { text: string; kind: "info" | "ok" | "err" | "cmd" }

const LANGS: { id: PackLang; label: string; icon: string; desc: string }[] = [
  { id: "python",   label: "Python",      icon: "🐍", desc: "PyInstaller / Briefcase"       },
  { id: "web",      label: "Web App",     icon: "🌐", desc: "Capacitor + Gradle"             },
  { id: "electron", label: "Electron",    icon: "⚡", desc: "Electron Builder NSIS"          },
  { id: "docker",   label: "Full-Stack",  icon: "🐳", desc: "Docker Compose — deploy-ready ZIP" },
];

const LOG_COLOR: Record<string, string> = { ok: "#34d399", err: "#f87171", cmd: "#a78bfa", info: "#94a3b8" };

interface PackageTabProps {
  projects:  Project[];
  projectId: string;
  onToast:   (m: string, k?: "ok" | "err" | "info") => void;
}

export function PackageTab({ projects, projectId: defaultProjectId, onToast }: PackageTabProps) {
  const [projectId, setProjectId] = useState(defaultProjectId);
  const [target, setTarget]       = useState<PackTarget>("exe");
  const [lang, setLang]           = useState<PackLang>("python");

  // When switching to docker lang, force target to zip
  const handleLangChange = (l: PackLang) => {
    setLang(l);
    if (l === "docker") setTarget("zip");
    else if (target === "zip") setTarget("exe");
  };
  const [appName, setAppName]     = useState("MyApp");
  const [appVersion, setVersion]  = useState("1.0.0");
  const [oneFile, setOneFile]     = useState(true);
  const [state, setState]         = useState<PackState>("idle");
  const [logs, setLogs]           = useState<LogEntry[]>([]);
  const [downloadUrl, setDownload] = useState("");
  const [files, setFiles]         = useState<{ path: string; size: number }[]>([]);
  const [uploading, setUploading] = useState(false);
  const logsEndRef  = useRef<HTMLDivElement>(null);
  const abortRef    = useRef<AbortController | null>(null);
  const uploadRef   = useRef<HTMLInputElement>(null);

  useEffect(() => { logsEndRef.current?.scrollIntoView({ behavior: "smooth" }); }, [logs]);

  useEffect(() => {
    if (!projectId) return;
    const path = `/api/projects/${projectId}/files`;
    apiFetch(path)
      .then(r => parseJSON<{ files?: { path: string; size: number }[] }>(r, path))
      .then(d => setFiles(d.files ?? []))
      .catch(() => {});
  }, [projectId]);

  const addLog = (text: string, kind: LogEntry["kind"] = "info") =>
    setLogs(p => [...p, { text, kind }]);

  const uploadFiles = async (ev: React.ChangeEvent<HTMLInputElement>) => {
    const picked = Array.from(ev.target.files ?? []);
    if (!picked.length) return;
    setUploading(true);
    try {
      const fd = new FormData();
      picked.forEach(f => fd.append("files", f));
      const r = await fetch(`${API}/api/projects/${projectId}/upload`, { method: "POST", body: fd });
      const data = await parseJSON<{ count: number }>(r, `/api/projects/${projectId}/upload`);
      onToast(`Uploaded ${data.count} file(s)`, "ok");
      const path = `/api/projects/${projectId}/files`;
      const fr = await apiFetch(path);
      const fd2 = await parseJSON<{ files?: { path: string; size: number }[] }>(fr, path);
      setFiles(fd2.files ?? []);
    } catch (e) {
      onToast(`Upload failed: ${(e as Error).message}`, "err");
    } finally {
      setUploading(false);
      if (uploadRef.current) uploadRef.current.value = "";
    }
  };

  const pack = async () => {
    if (state === "building") return;
    setState("building");
    setLogs([]);
    setDownload("");
    addLog("Connecting to build server…");

    const ctrl = new AbortController();
    abortRef.current = ctrl;

    try {
      const res = await fetch(`${API}/api/package/stream`, {
        method: "POST",
        headers: authH(),
        body: JSON.stringify({ project_id: projectId, target, lang, app_name: appName, version: appVersion, one_file: oneFile }),
        signal: ctrl.signal,
      });

      if (!res.ok || !res.body) {
        addLog(`HTTP ${res.status} — check backend logs`, "err");
        setState("error");
        return;
      }

      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let buf = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const lines = buf.split("\n");
        buf = lines.pop() ?? "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          let ev: Record<string, unknown>;
          try { ev = JSON.parse(line.slice(6)); } catch { continue; }

          if (ev.type === "log")   addLog(ev.text as string, (ev.level as LogEntry["kind"]) ?? "info");
          if (ev.type === "done")  { setState("done"); setDownload(ev.download_url as string); addLog("✓ Package ready", "ok"); }
          if (ev.type === "error") { setState("error"); addLog(ev.text as string ?? ev.message as string, "err"); }
        }
      }
    } catch (e: unknown) {
      if ((e as Error).name !== "AbortError") {
        addLog(`Error: ${(e as Error).message}`, "err");
        setState("error");
      } else {
        setState("idle");
      }
    }
  };

  return (
    <div style={{ flex: 1, overflowY: "auto", padding: 24 }}>
      <div style={{ maxWidth: 640, display: "flex", flexDirection: "column", gap: 16 }}>

        {/* Project */}
        <div>
          <label style={S.label}>Project</label>
          <select
            value={projectId}
            onChange={e => setProjectId(e.target.value)}
            style={{ ...S.textInput, marginTop: 4 }}
            aria-label="Select project"
          >
            <option value="demo">Demo Project</option>
            {projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </div>

        {/* Language + Target */}
        <div style={{ display: "flex", gap: 12 }}>
          <div style={{ flex: 1 }}>
            <label style={S.label}>Runtime</label>
            <div style={{ display: "flex", gap: 6, marginTop: 4 }}>
              {LANGS.map(l => (
                <button
                  key={l.id}
                  onClick={() => handleLangChange(l.id)}
                  style={{
                    ...S.btnSecondary, flex: 1, fontSize: 12,
                    borderColor: lang === l.id ? "var(--accent)" : undefined,
                    background:  lang === l.id ? "rgba(124,58,237,.2)" : undefined,
                    color:       lang === l.id ? "#c4b5fd" : undefined,
                  }}
                  title={l.desc}
                >{l.icon} {l.label}</button>
              ))}
            </div>
          </div>
          {lang !== "docker" && (
            <div style={{ flex: "0 0 auto" }}>
              <label style={S.label}>Target</label>
              <select
                value={target}
                onChange={e => setTarget(e.target.value as PackTarget)}
                style={{ ...S.textInput, marginTop: 4 }}
                aria-label="Package target"
              >
                <option value="exe">Windows .exe</option>
                <option value="apk">Android .apk</option>
              </select>
            </div>
          )}
        </div>

        {lang === "docker" && (
          <div style={{ padding: "10px 14px", background: "rgba(56,189,248,.08)", borderRadius: 8,
                        border: "1px solid rgba(56,189,248,.2)", fontSize: 12, color: "var(--t2)", lineHeight: 1.6 }}>
            🐳 <strong>Full-Stack Deploy Package</strong> — يجمع كل ملفات المشروع مع سكربتات النشر وملف
            {" "}<code>.env.example</code> وتعليمات Docker Compose كاملة.
          </div>
        )}

        {/* App metadata */}
        <div style={{ display: "flex", gap: 12 }}>
          <div style={{ flex: 2 }}>
            <label style={S.label}>App Name</label>
            <input value={appName} onChange={e => setAppName(e.target.value)}
              style={{ ...S.textInput, marginTop: 4 }} aria-label="App name" />
          </div>
          <div style={{ flex: 1 }}>
            <label style={S.label}>Version</label>
            <input value={appVersion} onChange={e => setVersion(e.target.value)}
              style={{ ...S.textInput, marginTop: 4 }} aria-label="App version" />
          </div>
          {lang !== "docker" && (
            <div style={{ display: "flex", flexDirection: "column", gap: 4, justifyContent: "flex-end" }}>
              <label style={S.label}>One-file</label>
              <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer" }}>
                <input type="checkbox" checked={oneFile} onChange={e => setOneFile(e.target.checked)} aria-label="Bundle as one file" />
                <span style={{ fontSize: 12, color: "var(--t3)" }}>Bundle</span>
              </label>
            </div>
          )}
        </div>

        {/* Files */}
        <div>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 6 }}>
            <label style={S.label}>Files ({files.length})</label>
            <button
              onClick={() => uploadRef.current?.click()}
              disabled={uploading}
              style={{ ...S.btnSecondary, fontSize: 12, padding: "4px 10px" }}
            >{uploading ? "Uploading…" : "⬆ Upload"}</button>
            <input ref={uploadRef} type="file" multiple style={{ display: "none" }} onChange={uploadFiles} aria-label="Upload files" />
          </div>
          {files.length > 0 && (
            <div style={{ background: "rgba(255,255,255,.02)", borderRadius: 8, border: "1px solid rgba(255,255,255,.06)", maxHeight: 120, overflowY: "auto", padding: "4px 0" }}>
              {files.map(f => (
                <div key={f.path} style={{ padding: "4px 12px", fontSize: 11, color: "var(--t3)", display: "flex", justifyContent: "space-between" }}>
                  <span>{f.path}</span>
                  <span style={{ color: "var(--t5)" }}>{(f.size / 1024).toFixed(1)} KB</span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Actions */}
        <div style={{ display: "flex", gap: 8 }}>
          <button
            onClick={state === "building" ? () => abortRef.current?.abort() : () => void pack()}
            style={{ ...S.btnPrimary, flex: 1 }}
            aria-label={state === "building" ? "Stop packaging" : "Package app"}
          >
            {state === "building" ? "⏹ Stop" : "⚙ Package App"}
          </button>
          {downloadUrl && (
            <a href={downloadUrl} download style={{ ...S.btnSecondary, padding: "0 18px", display: "flex", alignItems: "center", textDecoration: "none" }}>
              ⬇ Download
            </a>
          )}
        </div>

        {/* Logs */}
        {logs.length > 0 && (
          <div style={{
            background: "#040506", borderRadius: 8, border: "1px solid rgba(255,255,255,.06)",
            maxHeight: 240, overflowY: "auto", padding: "12px 16px",
          }}>
            {logs.map((l, i) => (
              <div key={i} style={{ fontSize: 12, color: LOG_COLOR[l.kind], fontFamily: "var(--font-mono)", lineHeight: 1.5 }}>
                {l.kind === "cmd" ? `$ ${l.text}` : l.text}
              </div>
            ))}
            <div ref={logsEndRef} />
          </div>
        )}
      </div>
    </div>
  );
}
