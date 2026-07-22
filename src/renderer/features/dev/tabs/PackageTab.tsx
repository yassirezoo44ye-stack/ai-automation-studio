/**
 * PackageTab — app packaging / distribution.
 * Replaces the legacy AppPackager.tsx with a clean, service-backed implementation.
 * Uses /api/package/* endpoints and renders streaming build logs.
 */
import { useState, useRef, useEffect, useCallback } from "react";
import { apiFetch, parseJSON, authH, API } from "../../../shared/utils/api";
import { GoldButton } from "../../../shared/ui/gold";
import type { Project } from "../../../shared/types";

type PackTarget = "exe" | "apk" | "zip";
type PackLang   = "python" | "web" | "electron" | "docker";
type PackState  = "idle" | "building" | "done" | "error";

interface LogEntry { text: string; kind: "info" | "ok" | "err" | "cmd" }

interface ToolCheckDTO {
  name: string; display: string; available: boolean;
  version: string | null; required_for: string; fix_hint: string;
}
interface PreflightDTO { ok: boolean; checks: ToolCheckDTO[]; missing: string[] }

const LANGS: { id: PackLang; label: string; icon: string; desc: string }[] = [
  { id: "python",   label: "Python",      icon: "🐍", desc: "PyInstaller / Briefcase"       },
  { id: "web",      label: "Web App",     icon: "🌐", desc: "Electron wrap (.exe) / Capacitor (.apk)" },
  { id: "electron", label: "Electron",    icon: "⚡", desc: "Electron Builder NSIS"          },
  { id: "docker",   label: "Full-Stack",  icon: "🐳", desc: "Docker Compose — deploy-ready ZIP" },
];

// Valid runtime → target matrix (mirrors /api/package/stream support)
const TARGETS_FOR: Record<PackLang, { id: PackTarget; label: string }[]> = {
  python:   [{ id: "exe", label: "Windows .exe" }, { id: "apk", label: "Android .apk" }],
  web:      [{ id: "exe", label: "Windows .exe" }, { id: "apk", label: "Android .apk" }],
  electron: [{ id: "exe", label: "Windows .exe" }],
  docker:   [{ id: "zip", label: "Deploy ZIP" }],
};

const LOG_COLOR: Record<string, string> = { ok: "var(--green)", err: "var(--red)", cmd: "var(--ta)", info: "var(--t4)" };

interface PackageTabProps {
  projects:  Project[];
  projectId: string;
  onToast:   (m: string, k?: "ok" | "err" | "info") => void;
}

export function PackageTab({ projects, projectId: defaultProjectId, onToast }: PackageTabProps) {
  const [projectId, setProjectId] = useState(defaultProjectId);
  const [target, setTarget]       = useState<PackTarget>("exe");
  const [lang, setLang]           = useState<PackLang>("python");

  // Snap target to a valid option whenever the runtime changes
  const handleLangChange = (l: PackLang) => {
    setLang(l);
    const valid = TARGETS_FOR[l];
    if (!valid.some(t => t.id === target)) setTarget(valid[0].id);
  };
  const [appName, setAppName]     = useState("MyApp");
  const [appVersion, setVersion]  = useState("1.0.0");
  const [oneFile, setOneFile]     = useState(true);
  const [state, setState]         = useState<PackState>("idle");
  const [logs, setLogs]           = useState<LogEntry[]>([]);
  const [downloadUrl, setDownload] = useState("");
  const [files, setFiles]         = useState<{ path: string; size: number }[]>([]);
  const [uploading, setUploading] = useState(false);
  const [preflight, setPreflight] = useState<PreflightDTO | null>(null);
  const [pfLoading, setPfLoading] = useState(false);
  const logsEndRef  = useRef<HTMLDivElement>(null);
  const abortRef    = useRef<AbortController | null>(null);
  const uploadRef   = useRef<HTMLInputElement>(null);

  useEffect(() => { logsEndRef.current?.scrollIntoView({ behavior: "smooth" }); }, [logs]);

  const checkPreflight = useCallback(() => {
    if (lang === "docker") { setPreflight(null); return; }
    setPfLoading(true);
    apiFetch(`/api/package/preflight?lang=${lang}&target=${target}`)
      .then(r => parseJSON<PreflightDTO>(r, "/api/package/preflight"))
      .then(setPreflight)
      .catch(() => setPreflight(null))
      .finally(() => setPfLoading(false));
  }, [lang, target]);

  useEffect(() => { void Promise.resolve().then(checkPreflight); }, [checkPreflight]);

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
          <div className="g-label">Project</div>
          <select
            value={projectId}
            onChange={e => setProjectId(e.target.value)}
            className="g-input" style={{ marginTop: 4 }}
            aria-label="Select project"
          >
            <option value="demo">Demo Project</option>
            {projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </div>

        {/* Language + Target */}
        <div style={{ display: "flex", gap: 12 }}>
          <div style={{ flex: 1 }}>
            <div className="g-label">Runtime</div>
            <div style={{ display: "flex", gap: 6, marginTop: 4 }}>
              {LANGS.map(l => (
                <GoldButton
                  key={l.id}
                  variant={lang === l.id ? "primary" : "ghost"}
                  onClick={() => handleLangChange(l.id)}
                  style={{ flex: 1, fontSize: 12 }}
                  title={l.desc}
                >{l.icon} {l.label}</GoldButton>
              ))}
            </div>
          </div>
          {lang !== "docker" && (
            <div style={{ flex: "0 0 auto" }}>
              <div className="g-label">Target</div>
              <select
                value={target}
                onChange={e => setTarget(e.target.value as PackTarget)}
                className="g-input" style={{ marginTop: 4 }}
                aria-label="Package target"
              >
                {TARGETS_FOR[lang].map(t => (
                  <option key={t.id} value={t.id}>{t.label}</option>
                ))}
              </select>
            </div>
          )}
        </div>

        {lang === "web" && target === "exe" && (
          <div style={{ padding: "10px 14px", background: "var(--accent-dim)", borderRadius: 8,
                        border: "1px solid var(--accent-border)", fontSize: 12, color: "var(--t2)", lineHeight: 1.6 }}>
            ⚡ <strong>Web → Windows .exe</strong> — يتم تغليف تطبيق الويب داخل Electron
            ثم بناؤه كمثبِّت NSIS قابل للتوزيع.
          </div>
        )}

        {lang === "docker" && (
          <div style={{ padding: "10px 14px", background: "var(--blue-dim)", borderRadius: 8,
                        border: "1px solid rgba(108,142,247,0.25)", fontSize: 12, color: "var(--t2)", lineHeight: 1.6 }}>
            🐳 <strong>Full-Stack Deploy Package</strong> — يجمع كل ملفات المشروع مع سكربتات النشر وملف
            {" "}<code>.env.example</code> وتعليمات Docker Compose كاملة.
          </div>
        )}

        {/* Pre-flight environment check — surfaced BEFORE the build attempt */}
        {pfLoading && (
          <div style={{ fontSize: 12, color: "var(--t4)", display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ width: 8, height: 8, borderRadius: "50%", background: "var(--ta)", animation: "fadeIn .6s ease-in-out infinite alternate" }} />
            Checking build environment…
          </div>
        )}

        {!pfLoading && preflight && preflight.checks.length > 0 && (
          <div style={{
            borderRadius: 8, border: `1px solid ${preflight.ok ? "rgba(52,211,153,.25)" : "rgba(248,113,113,.3)"}`,
            background: preflight.ok ? "var(--green-dim)" : "var(--red-dim)",
            padding: "10px 14px",
          }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: preflight.checks.length ? 8 : 0 }}>
              <span style={{ fontSize: 12, fontWeight: 600, color: preflight.ok ? "var(--green)" : "var(--red)" }}>
                {preflight.ok ? "✓ Build environment ready" : "⚠ Build environment not ready"}
              </span>
              <button
                onClick={checkPreflight}
                style={{ background: "none", border: "none", cursor: "pointer", fontSize: 11, color: "var(--t4)", padding: "2px 6px" }}
                aria-label="Recheck environment"
                title="Recheck"
              >↻ Recheck</button>
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              {preflight.checks.map(c => (
                <span key={c.name} title={c.version ?? undefined} style={{
                  fontSize: 11, padding: "2px 8px", borderRadius: 20,
                  color: c.available ? "var(--green)" : "var(--red)",
                  background: c.available ? "var(--green-dim)" : "var(--red-dim)",
                  border: `1px solid ${c.available ? "rgba(52,211,153,.25)" : "rgba(248,113,113,.3)"}`,
                }}>
                  {c.available ? "✓" : "✗"} {c.display}
                </span>
              ))}
            </div>
            {!preflight.ok && (
              <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 4 }}>
                {preflight.checks.filter(c => !c.available).map(c => (
                  <div key={c.name} style={{ fontSize: 11, color: "var(--t3)", lineHeight: 1.5 }}>
                    <strong style={{ color: "var(--red)" }}>{c.display}</strong> — {c.fix_hint}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* App metadata */}
        <div style={{ display: "flex", gap: 12 }}>
          <div style={{ flex: 2 }}>
            <div className="g-label">App Name</div>
            <input value={appName} onChange={e => setAppName(e.target.value)}
              className="g-input" style={{ marginTop: 4 }} aria-label="App name" />
          </div>
          <div style={{ flex: 1 }}>
            <div className="g-label">Version</div>
            <input value={appVersion} onChange={e => setVersion(e.target.value)}
              className="g-input" style={{ marginTop: 4 }} aria-label="App version" />
          </div>
          {lang !== "docker" && (
            <div style={{ display: "flex", flexDirection: "column", gap: 4, justifyContent: "flex-end" }}>
              <div className="g-label">One-file</div>
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
            <label className="g-label">Files ({files.length})</label>
            <GoldButton
              variant="ghost"
              onClick={() => uploadRef.current?.click()}
              disabled={uploading}
              style={{ fontSize: 12, padding: "4px 10px" }}
            >{uploading ? "Uploading…" : "⬆ Upload"}</GoldButton>
            <input ref={uploadRef} type="file" multiple style={{ display: "none" }} onChange={uploadFiles} aria-label="Upload files" />
          </div>
          {files.length > 0 && (
            <div style={{ background: "var(--bg-hover)", borderRadius: 8, border: "1px solid var(--border)", maxHeight: 120, overflowY: "auto", padding: "4px 0" }}>
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
        {(() => {
          const envBlocked = state !== "building" && !!preflight && !preflight.ok;
          return (
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <div style={{ display: "flex", gap: 8 }}>
                <GoldButton
                  onClick={state === "building" ? () => abortRef.current?.abort() : () => void pack()}
                  disabled={envBlocked}
                  style={{ flex: 1 }}
                  title={envBlocked ? "Fix the missing tools above, or Recheck once installed" : (state === "building" ? "Stop packaging" : "Package app")}
                >
                  {state === "building" ? "⏹ Stop" : envBlocked ? "⚠ Environment Not Ready" : "⚙ Package App"}
                </GoldButton>
                {downloadUrl && (
                  <a href={downloadUrl} download className="g-btn g-btn--ghost" style={{ padding: "0 18px", display: "flex", alignItems: "center", textDecoration: "none" }}>
                    ⬇ Download
                  </a>
                )}
              </div>
              {envBlocked && (
                <span style={{ fontSize: 11, color: "var(--t4)" }}>
                  Install the missing tools on the build server, then hit Recheck above.
                </span>
              )}
            </div>
          );
        })()}

        {/* Logs — terminal-style build log, same fixed-dark convention as
            RunTab's console output. */}
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
