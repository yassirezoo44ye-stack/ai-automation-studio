/**
 * InstallationPanel — the first actionable section after a successful Generate.
 *
 * Detects the generated project type from its files and renders the correct
 * install + run commands, with a package-manager switcher (npm/pnpm/yarn/bun)
 * for Node projects, one-click copy, command download, and quick actions.
 */
import { useState, useEffect, useMemo, useRef } from "react";
import type { BuildFile } from "../../../shared/types";

// ── Project-type detection ────────────────────────────────────────────────────

export type ProjectKind = "node" | "fastapi" | "python" | "docker" | "static" | "unknown";

export interface DetectedProject {
  kind: ProjectKind;
  label: string;
  icon: string;
  hasDocker: boolean;
}

export function detectProject(files: BuildFile[]): DetectedProject {
  const paths   = files.map(f => f.path.toLowerCase());
  const has     = (p: string) => paths.some(x => x === p || x.endsWith(`/${p}`));
  const content = (p: string) =>
    files.find(f => f.path.toLowerCase() === p || f.path.toLowerCase().endsWith(`/${p}`))?.content ?? "";

  const hasDocker = has("docker-compose.yml") || has("docker-compose.yaml") || has("compose.yml") || has("compose.yaml");

  if (has("package.json"))
    return { kind: "node", label: "Node.js", icon: "📦", hasDocker };

  if (has("requirements.txt") || paths.some(p => p.endsWith(".py"))) {
    const pyText = files.filter(f => f.path.endsWith(".py")).map(f => f.content).join("\n")
                 + content("requirements.txt");
    if (/fastapi|uvicorn/i.test(pyText))
      return { kind: "fastapi", label: "FastAPI", icon: "⚡", hasDocker };
    return { kind: "python", label: "Python", icon: "🐍", hasDocker };
  }

  if (hasDocker || has("dockerfile"))
    return { kind: "docker", label: "Docker", icon: "🐳", hasDocker: true };

  if (paths.some(p => p.endsWith(".html")))
    return { kind: "static", label: "Static HTML", icon: "🌐", hasDocker };

  return { kind: "unknown", label: "Project", icon: "📁", hasDocker };
}

// ── Command sets ──────────────────────────────────────────────────────────────

type PM = "npm" | "pnpm" | "yarn" | "bun";

const PM_COMMANDS: Record<PM, string[]> = {
  npm:  ["npm install", "npm run dev"],
  pnpm: ["pnpm install", "pnpm dev"],
  yarn: ["yarn", "yarn dev"],
  bun:  ["bun install", "bun run dev"],
};

const PM_ICONS: Record<PM, string> = { npm: "📕", pnpm: "🟡", yarn: "🧶", bun: "🥟" };

function commandsFor(project: DetectedProject, pm: PM, entryPy: string): string[] {
  switch (project.kind) {
    case "node":    return PM_COMMANDS[pm];
    case "fastapi": return ["pip install -r requirements.txt", `uvicorn ${entryPy.replace(/\.py$/, "")}:app --reload`];
    case "python":  return ["pip install -r requirements.txt", `python ${entryPy}`];
    case "docker":  return ["docker compose up --build"];
    case "static":  return ["# No installation needed — open in the Preview tab", "# or serve locally:", "npx serve ."];
    default:        return ["# Explore the generated files to get started"];
  }
}

// ── Copy button ───────────────────────────────────────────────────────────────

function CopyBtn({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      onClick={() => {
        navigator.clipboard.writeText(text).then(() => {
          setCopied(true);
          setTimeout(() => setCopied(false), 1600);
        });
      }}
      aria-label="Copy commands"
      style={{
        display: "inline-flex", alignItems: "center", gap: 6,
        padding: "6px 14px", borderRadius: 8, cursor: "pointer",
        fontSize: 12, fontWeight: 600, border: "1px solid",
        borderColor: copied ? "rgba(52,211,153,.45)" : "var(--border)",
        background: copied ? "rgba(52,211,153,.12)" : "rgba(255,255,255,.05)",
        color: copied ? "#34d399" : "var(--t2)",
        transition: "all .2s",
        flexShrink: 0,
      }}
    >
      {copied ? (
        <>
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="20 6 9 17 4 12"/></svg>
          Copied
        </>
      ) : (
        <>
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
          Copy
        </>
      )}
    </button>
  );
}

// ── Quick action button ───────────────────────────────────────────────────────

function QuickAction({ icon, label, onClick }: { icon: React.ReactNode; label: string; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      style={{
        display: "flex", flexDirection: "column", alignItems: "center", gap: 7,
        padding: "14px 8px", borderRadius: 12, cursor: "pointer",
        border: "1px solid var(--border)",
        background: "rgba(255,255,255,.03)",
        color: "var(--t2)", fontSize: 12, fontWeight: 500,
        transition: "transform .15s, border-color .15s, background .15s",
        flex: 1, minWidth: 90,
      }}
      className="card-hover"
    >
      <span style={{ fontSize: 20, lineHeight: 1 }}>{icon}</span>
      {label}
    </button>
  );
}

// ── Main panel ────────────────────────────────────────────────────────────────

interface InstallationPanelProps {
  files: BuildFile[];
  onOpenPreview:  () => void;
  onViewFiles:    () => void;
  onOpenTerminal: () => void;
  onOpenPackage:  () => void;
  onExportZip:    () => void;
}

export function InstallationPanel({
  files, onOpenPreview, onViewFiles, onOpenTerminal, onOpenPackage, onExportZip,
}: InstallationPanelProps) {
  const project = useMemo(() => detectProject(files), [files]);
  const [pm, setPm] = useState<PM>("npm");
  const [entered, setEntered] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);

  const entryPy = useMemo(() => {
    const py = files.map(f => f.path).filter(p => p.endsWith(".py"));
    return py.find(p => /(^|\/)main\.py$/.test(p))
        ?? py.find(p => /(^|\/)app\.py$/.test(p))
        ?? py[0] ?? "main.py";
  }, [files]);

  const commands = commandsFor(project, pm, entryPy);
  const isNode   = project.kind === "node";

  // Auto-scroll + entrance animation on mount
  useEffect(() => {
    const t = requestAnimationFrame(() => {
      setEntered(true);
      panelRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
    return () => cancelAnimationFrame(t);
  }, []);

  const downloadCommands = () => {
    const all = [
      `# ${project.label} — installation & run`,
      "",
      ...(isNode
        ? (Object.keys(PM_COMMANDS) as PM[]).flatMap(p => [`## ${p}`, ...PM_COMMANDS[p], ""])
        : [...commands, ""]),
      ...(project.hasDocker && project.kind !== "docker" ? ["## Docker", "docker compose up --build", ""] : []),
    ].join("\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([all], { type: "text/plain" }));
    a.download = "INSTALL.md";
    a.click();
    URL.revokeObjectURL(a.href);
  };

  return (
    <div
      ref={panelRef}
      style={{
        borderRadius: 16,
        border: "1px solid rgba(52,211,153,.28)",
        background: "linear-gradient(160deg, rgba(52,211,153,.06), rgba(108,142,247,.05) 55%, rgba(255,255,255,.02))",
        backdropFilter: "blur(14px)",
        WebkitBackdropFilter: "blur(14px)",
        boxShadow: "0 8px 32px rgba(0,0,0,.25), inset 0 1px 0 rgba(255,255,255,.06)",
        overflow: "hidden",
        opacity: entered ? 1 : 0,
        transform: entered ? "translateY(0) scale(1)" : "translateY(14px) scale(.98)",
        transition: "opacity .45s ease, transform .45s cubic-bezier(.2,.9,.3,1.2)",
      }}
    >
      {/* Header with success badge */}
      <div style={{
        padding: "16px 20px 14px",
        borderBottom: "1px solid rgba(255,255,255,.06)",
        display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap",
      }}>
        <span style={{ fontSize: 15, fontWeight: 700, color: "var(--t1)", display: "flex", alignItems: "center", gap: 8 }}>
          📦 Installation
        </span>
        <span style={{
          display: "inline-flex", alignItems: "center", gap: 6,
          fontSize: 11, fontWeight: 700, padding: "3px 10px", borderRadius: 99,
          background: "rgba(52,211,153,.14)", color: "#34d399",
          border: "1px solid rgba(52,211,153,.35)",
          animation: entered ? "pulseOnce .9s ease" : undefined,
        }}>
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3"><polyline points="20 6 9 17 4 12"/></svg>
          Project Generated Successfully
        </span>
        <span style={{
          marginLeft: "auto", fontSize: 11, fontWeight: 600,
          padding: "3px 10px", borderRadius: 99,
          background: "rgba(108,142,247,.12)", color: "#8fa8f8",
          border: "1px solid rgba(108,142,247,.28)",
        }}>
          {project.icon} {project.label}
        </span>
      </div>

      <div style={{ padding: 20, display: "flex", flexDirection: "column", gap: 16 }}>

        {/* Package-manager tabs (Node only) */}
        {isNode && (
          <div role="tablist" aria-label="Package manager" style={{
            display: "flex", gap: 4, padding: 4, borderRadius: 12,
            background: "rgba(0,0,0,.28)", width: "fit-content", maxWidth: "100%", flexWrap: "wrap",
          }}>
            {(Object.keys(PM_COMMANDS) as PM[]).map(p => (
              <button
                key={p}
                role="tab"
                aria-selected={pm === p}
                onClick={() => setPm(p)}
                style={{
                  display: "inline-flex", alignItems: "center", gap: 6,
                  padding: "7px 16px", borderRadius: 9, border: "none", cursor: "pointer",
                  fontSize: 13, fontWeight: 600, transition: "all .18s",
                  background: pm === p ? "linear-gradient(135deg,#34d399,#22c55e)" : "transparent",
                  color: pm === p ? "#052e1b" : "var(--t4)",
                  boxShadow: pm === p ? "0 2px 12px rgba(52,211,153,.3)" : "none",
                }}
              >
                {PM_ICONS[p]} {p}
              </button>
            ))}
          </div>
        )}

        {/* Command block */}
        <div style={{
          borderRadius: 12, border: "1px solid var(--border)",
          background: "rgba(0,0,0,.35)", overflow: "hidden",
        }}>
          <div style={{
            padding: "8px 14px", display: "flex", alignItems: "center", justifyContent: "space-between",
            borderBottom: "1px solid rgba(255,255,255,.05)", background: "rgba(255,255,255,.02)",
          }}>
            <span style={{ fontSize: 11, fontWeight: 600, color: "var(--t4)", letterSpacing: "0.5px" }}>
              {isNode ? pm.toUpperCase() : project.label.toUpperCase()} · TERMINAL
            </span>
            <CopyBtn text={commands.filter(c => !c.startsWith("#")).join("\n")} />
          </div>
          <pre style={{
            margin: 0, padding: "14px 16px",
            fontFamily: "ui-monospace, 'Cascadia Code', monospace", fontSize: 13, lineHeight: 1.8,
            color: "var(--t1)", overflowX: "auto",
          }}>
            {commands.map((c, i) => (
              <div key={i} style={{ color: c.startsWith("#") ? "var(--t5)" : undefined }}>
                {!c.startsWith("#") && <span style={{ color: "#34d399", userSelect: "none" }}>$ </span>}
                {c}
              </div>
            ))}
          </pre>
        </div>

        {/* Docker alternative when available alongside a non-Docker project */}
        {project.hasDocker && project.kind !== "docker" && (
          <div style={{
            borderRadius: 12, border: "1px solid rgba(59,130,246,.25)",
            background: "rgba(59,130,246,.06)", overflow: "hidden",
          }}>
            <div style={{
              padding: "8px 14px", display: "flex", alignItems: "center", justifyContent: "space-between",
              borderBottom: "1px solid rgba(59,130,246,.15)",
            }}>
              <span style={{ fontSize: 11, fontWeight: 600, color: "#60a5fa", letterSpacing: "0.5px" }}>
                🐳 DOCKER (ALTERNATIVE)
              </span>
              <CopyBtn text="docker compose up --build" />
            </div>
            <pre style={{
              margin: 0, padding: "12px 16px",
              fontFamily: "ui-monospace, 'Cascadia Code', monospace", fontSize: 13,
              color: "var(--t1)",
            }}>
              <span style={{ color: "#60a5fa", userSelect: "none" }}>$ </span>docker compose up --build
            </pre>
          </div>
        )}

        {/* Download commands */}
        <button
          onClick={downloadCommands}
          style={{
            alignSelf: "flex-start",
            display: "inline-flex", alignItems: "center", gap: 8,
            padding: "8px 16px", borderRadius: 9, cursor: "pointer",
            fontSize: 12, fontWeight: 600,
            border: "1px solid var(--border)", background: "rgba(255,255,255,.04)",
            color: "var(--t2)", transition: "border-color .15s",
          }}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
          Download Commands (INSTALL.md)
        </button>

        {/* Quick actions */}
        <div>
          <div style={{ fontSize: 11, fontWeight: 700, color: "var(--t4)", letterSpacing: "0.8px", marginBottom: 10 }}>
            QUICK ACTIONS
          </div>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            <QuickAction icon="👁"  label="Open Preview"  onClick={onOpenPreview} />
            <QuickAction icon="✏️" label="Open Editor"   onClick={onViewFiles} />
            <QuickAction icon="📂" label="View Files"    onClick={onViewFiles} />
            <QuickAction icon="⌨️" label="Open Terminal" onClick={onOpenTerminal} />
            <QuickAction icon="🗜" label="Export ZIP"    onClick={onExportZip} />
            <QuickAction icon="📦" label="Package"       onClick={onOpenPackage} />
          </div>
        </div>
      </div>
    </div>
  );
}
