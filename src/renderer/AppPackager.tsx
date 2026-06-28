import { useState, useRef, useEffect, useCallback } from "react";

const API = import.meta.env.VITE_API_URL ?? "";

type PackTarget = "exe" | "apk";
type PackState  = "idle" | "building" | "done" | "error";
type Project    = { id: string; name: string; description: string; status: string };

const LANGS = [
  { id: "python",   label: "Python",   icon: "🐍", ext: ".exe / .apk", desc: "PyInstaller / Briefcase" },
  { id: "web",      label: "Web App",  icon: "🌐", ext: ".apk",        desc: "Capacitor + Gradle" },
  { id: "electron", label: "Electron", icon: "⚡", ext: ".exe",        desc: "Electron Builder NSIS" },
];

export default function AppPackager({ toast }: { toast: (m: string, k?: "ok"|"err"|"info") => void }) {
  const [projects, setProjects]     = useState<Project[]>([]);
  const [projectId, setProjectId]   = useState("demo");
  const [target, setTarget]         = useState<PackTarget>("exe");
  const [lang, setLang]             = useState("python");
  const [appName, setAppName]       = useState("MyApp");
  const [appIcon, setAppIcon]       = useState("");
  const [appVersion, setAppVersion] = useState("1.0.0");
  const [oneFile, setOneFile]       = useState(true);
  const [state, setState]           = useState<PackState>("idle");
  const [logs, setLogs]             = useState<{ text: string; type: "info"|"ok"|"err"|"cmd" }[]>([]);
  const [downloadUrl, setDownload]  = useState("");
  const [extraFiles, setExtraFiles] = useState<{name:string;url:string}[]>([]);
  const [files, setFiles]           = useState<{ path: string; size: number }[]>([]);
  const [uploading, setUploading]   = useState(false);
  const logsEndRef  = useRef<HTMLDivElement>(null);
  const abortRef    = useRef<AbortController | null>(null);
  const uploadRef   = useRef<HTMLInputElement>(null);

  useEffect(() => { logsEndRef.current?.scrollIntoView({ behavior: "smooth" }); }, [logs]);

  useEffect(() => {
    fetch(`${API}/api/projects`).then(r => r.json()).then(setProjects).catch(() => {});
  }, []);

  useEffect(() => {
    if (projectId) {
      fetch(`${API}/api/projects/${projectId}/files`).then(r => r.json())
        .then(d => setFiles(d.files ?? [])).catch(() => {});
    }
  }, [projectId]);

  function addLog(text: string, type: "info"|"ok"|"err"|"cmd" = "info") {
    setLogs(p => [...p, { text, type }]);
  }

  async function uploadFiles(ev: React.ChangeEvent<HTMLInputElement>) {
    const picked = Array.from(ev.target.files ?? []);
    if (!picked.length) return;
    setUploading(true);
    try {
      const fd = new FormData();
      picked.forEach(f => fd.append("files", f));
      const r = await fetch(`${API}/api/projects/${projectId}/upload`, { method: "POST", body: fd });
      if (!r.ok) throw new Error(`Upload failed (${r.status})`);
      const data = await r.json();
      toast(`✅ رُفع ${data.count} ملف`, "ok");
      // refresh file list
      const fl = await fetch(`${API}/api/projects/${projectId}/files`).then(x => x.json());
      setFiles(fl.files ?? []);
    } catch (e: any) { toast(e.message, "err"); }
    finally { setUploading(false); ev.target.value = ""; }
  }

  async function startBuild() {
    if (state === "building") { abortRef.current?.abort(); return; }
    setState("building"); setLogs([]); setDownload(""); setExtraFiles([]);
    addLog(`▶ Starting ${target.toUpperCase()} build for "${appName}"…`, "cmd");
    addLog(`  Project: ${projectId} | Lang: ${lang} | Version: ${appVersion}`, "info");

    const ctrl = new AbortController();
    abortRef.current = ctrl;

    try {
      const res = await fetch(`${API}/api/package/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project_id: projectId, target, lang, app_name: appName, app_version: appVersion, one_file: oneFile }),
        signal: ctrl.signal,
      });
      if (!res.ok || !res.body) {
        const err = await res.json().catch(() => ({ detail: "Server error" }));
        throw new Error(err.detail);
      }
      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let buf = "";
      while (true) {
        const { done, value } = await reader.read(); if (done) break;
        buf += dec.decode(value, { stream: true });
        const lines = buf.split("\n"); buf = lines.pop() ?? "";
        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          try {
            const ev = JSON.parse(line.slice(6));
            if (ev.type === "log")        addLog(ev.text, ev.level ?? "info");
            else if (ev.type === "done")  { setState("done"); setDownload(ev.download_url ?? ""); setExtraFiles(ev.extra_files ?? []); addLog(`✅ Build successful! Output: ${ev.output_file}`, "ok"); toast("تم البناء بنجاح! 🎉"); }
            else if (ev.type === "error") { setState("error"); addLog(`❌ ${ev.message}`, "err"); toast(ev.message, "err"); }
          } catch { /* malformed SSE line, skip */ }
        }
      }
    } catch (err: unknown) {
      if ((err as Error).name !== "AbortError") {
        setState("error"); addLog(`❌ ${(err as Error).message}`, "err");
      } else {
        setState("idle"); addLog("⏹ Build cancelled.", "info");
      }
    }
  }

  function download() {
    if (!downloadUrl) return;
    const a = document.createElement("a"); a.href = `${API}${downloadUrl}`; a.click();
    toast("Downloading…", "info");
  }

  const logColor = { info: "rgba(148,163,184,.7)", ok: "#34d399", err: "#f87171", cmd: "#a78bfa" };
  const hasMainPy = files.some(f => f.path === "main.py" || f.path.endsWith("/main.py"));

  return (
    <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>
      {/* Left: config */}
      <div style={{ width: 300, borderRight: "1px solid rgba(255,255,255,.05)", overflowY: "auto", background: "rgba(8,10,20,.7)", flexShrink: 0, padding: 20, display: "flex", flexDirection: "column", gap: 16 }}>

        {/* Target */}
        <div>
          <label style={F.label}>نوع الملف الناتج</label>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
            {(["exe","apk"] as PackTarget[]).map(t => (
              <button key={t} onClick={() => setTarget(t)}
                style={{ padding: "14px 8px", borderRadius: 12, border: "none", cursor: "pointer", display: "flex", flexDirection: "column", alignItems: "center", gap: 6, transition: "all .18s",
                  background: target === t ? "linear-gradient(135deg,rgba(139,92,246,.3),rgba(99,102,241,.2))" : "rgba(255,255,255,.04)",
                  boxShadow: target === t ? "inset 0 0 0 1px rgba(139,92,246,.4)" : "inset 0 0 0 1px rgba(255,255,255,.06)" }}>
                <span style={{ fontSize: 28 }}>{t === "exe" ? "🖥" : "📱"}</span>
                <span style={{ fontSize: 13, fontWeight: 600, color: target === t ? "#e2e8f0" : "rgba(148,163,184,.6)" }}>
                  .{t.toUpperCase()}
                </span>
                <span style={{ fontSize: 11, color: "rgba(148,163,184,.4)" }}>
                  {t === "exe" ? "Windows" : "Android"}
                </span>
              </button>
            ))}
          </div>
        </div>

        {/* Language */}
        <div>
          <label style={F.label}>تقنية البناء</label>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {LANGS.filter(l => l.id === "python" || (target === "exe" && l.id === "electron") || (target === "apk" && l.id === "web")).map(l => (
              <button key={l.id} onClick={() => setLang(l.id)}
                style={{ padding: "10px 14px", borderRadius: 10, border: "none", cursor: "pointer", textAlign: "left", display: "flex", alignItems: "center", gap: 10, transition: "all .18s",
                  background: lang === l.id ? "rgba(139,92,246,.2)" : "rgba(255,255,255,.04)",
                  boxShadow: `inset 0 0 0 1px ${lang === l.id ? "rgba(139,92,246,.35)" : "rgba(255,255,255,.06)"}` }}>
                <span style={{ fontSize: 20 }}>{l.icon}</span>
                <div>
                  <div style={{ fontSize: 13, fontWeight: 600, color: lang === l.id ? "#e2e8f0" : "rgba(148,163,184,.7)" }}>{l.label}</div>
                  <div style={{ fontSize: 11, color: "rgba(148,163,184,.4)" }}>{l.desc}</div>
                </div>
              </button>
            ))}
          </div>
        </div>

        {/* Project */}
        <div>
          <label style={F.label}>المشروع (من Build)</label>
          <select value={projectId} onChange={e => setProjectId(e.target.value)} style={F.input}>
            <option value="demo">Demo Project</option>
            {projects.filter(p => p.id !== "00000000-0000-0000-0000-000000000001").map(p => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
          {/* Upload your own files */}
          <input ref={uploadRef} type="file" multiple accept=".py,.txt,.json,.toml,.cfg,.ini,.png,.ico"
            style={{ display: "none" }} onChange={uploadFiles} />
          <button onClick={() => uploadRef.current?.click()} disabled={uploading}
            style={{ marginTop: 8, width: "100%", padding: "8px", borderRadius: 8, border: "1px dashed rgba(139,92,246,.4)",
              background: "rgba(139,92,246,.07)", color: "#a78bfa", cursor: "pointer", fontSize: 12, fontWeight: 500 }}>
            {uploading ? "⏳ جاري الرفع…" : "📂 ارفع ملفاتك (.py وغيرها)"}
          </button>
          {files.length > 0 && (
            <div style={{ marginTop: 6, fontSize: 11, color: hasMainPy ? "#34d399" : "#f59e0b" }}>
              {hasMainPy ? `✅ ${files.length} ملف، main.py موجود` : `⚠️ ${files.length} ملف — لا يوجد main.py`}
            </div>
          )}
          {files.length > 0 && (
            <div style={{ marginTop: 4, maxHeight: 80, overflowY: "auto", fontSize: 11, color: "rgba(148,163,184,.5)", lineHeight: 1.8 }}>
              {files.map(f => <div key={f.path}>📄 {f.path} ({(f.size/1024).toFixed(1)} KB)</div>)}
            </div>
          )}
        </div>

        {/* App info */}
        <div>
          <label style={F.label}>اسم التطبيق</label>
          <input value={appName} onChange={e => setAppName(e.target.value)} style={F.input} placeholder="MyApp" />
        </div>
        <div>
          <label style={F.label}>الإصدار</label>
          <input value={appVersion} onChange={e => setAppVersion(e.target.value)} style={F.input} placeholder="1.0.0" />
        </div>

        {target === "exe" && lang === "python" && (
          <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer", fontSize: 13, color: "rgba(148,163,184,.7)" }}>
            <input type="checkbox" checked={oneFile} onChange={e => setOneFile(e.target.checked)} />
            ملف واحد (--onefile)
          </label>
        )}

        <button onClick={startBuild} style={{ ...F.btnPrimary, padding: "13px", fontSize: 14, marginTop: 4 }}>
          {state === "building" ? "⏹ إيقاف البناء" : target === "exe" ? "🔨 بناء .EXE" : "📱 بناء .APK"}
        </button>

        {state === "done" && downloadUrl && (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <button onClick={download} style={{ ...F.btnPrimary, padding: "14px", fontSize: 14, background: "linear-gradient(135deg,#10b981,#059669)", boxShadow: "0 4px 20px rgba(16,185,129,.4)" }}>
              ⬇ تحميل المُثبِّت
            </button>
            <div style={{ fontSize: 11, color: "rgba(52,211,153,.7)", lineHeight: 1.8, padding: "8px 10px", background: "rgba(16,185,129,.06)", border: "1px solid rgba(16,185,129,.15)", borderRadius: 8, textAlign: "center" }}>
              🖱️ نقرة واحدة على الملف<br/>= تثبيت + اختصار سطح المكتب<br/>+ قائمة ابدأ + تشغيل فوري
            </div>
          </div>
        )}

        {/* Info note */}
        <div style={{ background: "rgba(16,185,129,.05)", border: "1px solid rgba(16,185,129,.2)", borderRadius: 10, padding: "10px 12px", fontSize: 12, color: "rgba(16,185,129,.8)", lineHeight: 1.7 }}>
          {target === "exe" && lang === "python"   && <><strong>✅ مُثبِّت Windows</strong><br/>ينتج <code>Install_*.bat</code> + <code>.exe</code> — شغِّل المُثبِّت لتثبيت البرنامج مع اختصار سطح المكتب وقائمة ابدأ.</>}
          {target === "apk" && lang === "python"   && <><strong>📲 تثبيت مباشر</strong><br/>ينتج ملف <code>.apk</code> حقيقي — حمِّله على Android وثبِّته مباشرة (فعِّل "مصادر غير معروفة").</>}
          {target === "apk" && lang === "web"      && <><strong>📲 تثبيت مباشر</strong><br/>ينتج ملف <code>.apk</code> عبر Capacitor + Gradle — يتطلب Node.js و Android SDK.</>}
          {target === "exe" && lang === "electron" && <><strong>✅ مُثبِّت Windows</strong><br/>ينتج مُثبِّت NSIS — انقر عليه لتثبيت التطبيق كأي برنامج عادي. يتطلب Node.js.</>}
        </div>
      </div>

      {/* Right: terminal logs */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", background: "#040608" }}>
        {/* Status bar */}
        <div style={{ padding: "10px 20px", borderBottom: "1px solid rgba(255,255,255,.05)", display: "flex", alignItems: "center", gap: 12, background: "rgba(8,10,20,.8)" }}>
          <div style={{ width: 8, height: 8, borderRadius: "50%", background: state === "building" ? "#f59e0b" : state === "done" ? "#10b981" : state === "error" ? "#f87171" : "rgba(148,163,184,.3)", boxShadow: state === "building" ? "0 0 8px #f59e0b" : "none", animation: state === "building" ? "pulse 1s infinite" : "none" }} />
          <span style={{ fontSize: 13, color: "rgba(148,163,184,.6)", fontFamily: "monospace" }}>
            {state === "idle" ? "جاهز للبناء" : state === "building" ? `⚙️  جاري البناء…` : state === "done" ? "✅  اكتمل البناء" : "❌  فشل البناء"}
          </span>
          {logs.length > 0 && <span style={{ marginLeft: "auto", fontSize: 11, color: "rgba(148,163,184,.3)" }}>{logs.length} سطر</span>}
        </div>

        {/* Logs */}
        <div style={{ flex: 1, overflowY: "auto", padding: "16px 20px", fontFamily: "'JetBrains Mono','Consolas',monospace", fontSize: 13, lineHeight: 1.7 }}>
          {logs.length === 0 ? (
            <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "100%", color: "rgba(148,163,184,.2)", gap: 12 }}>
              <span style={{ fontSize: 48 }}>{target === "exe" ? "🖥" : "📱"}</span>
              <span style={{ fontSize: 16, fontFamily: "inherit" }}>
                {target === "exe" ? "Build to .EXE" : "Build to .APK"}
              </span>
              <span style={{ fontSize: 13, color: "rgba(148,163,184,.15)", fontFamily: "Inter,sans-serif" }}>
                اضبط الإعدادات واضغط بناء
              </span>
            </div>
          ) : (
            logs.map((l, i) => (
              <div key={i} style={{ color: logColor[l.type], marginBottom: 2, whiteSpace: "pre-wrap", wordBreak: "break-all" }}>
                {l.type === "cmd" && <span style={{ color: "rgba(139,92,246,.6)", marginLeft: 4 }}>$ </span>}
                {l.text}
              </div>
            ))
          )}
          <div ref={logsEndRef} />
        </div>
      </div>
    </div>
  );
}

const F: Record<string, React.CSSProperties> = {
  label:     { fontSize: 12, color: "rgba(148,163,184,.5)", display: "block", marginBottom: 6, fontWeight: 500 },
  input:     { width: "100%", background: "rgba(255,255,255,.04)", border: "1px solid rgba(255,255,255,.08)", borderRadius: 9, padding: "9px 13px", color: "#e2e8f0", fontSize: 13, fontFamily: "inherit" },
  btnPrimary:{ background: "linear-gradient(135deg,#8b5cf6,#6366f1)", border: "none", borderRadius: 10, color: "#fff", fontWeight: 600, cursor: "pointer", boxShadow: "0 4px 16px rgba(139,92,246,.35)", width: "100%", fontFamily: "inherit" },
};
