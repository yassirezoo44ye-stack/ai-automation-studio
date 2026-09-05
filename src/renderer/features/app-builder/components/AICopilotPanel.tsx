/**
 * AICopilotPanel — context-aware AI engineering copilot for the App Builder.
 *
 * Replaces the basic AIBuilderPanel chat with a structured action panel:
 *   Generate | Modify | Explain | Debug | Refactor | Test | Secure | Optimize
 *
 * Each action pre-fills a context-aware prompt referencing the current
 * project, error state, or selected section.
 *
 * All AI calls go through the existing /api/ai/chat endpoint — no new
 * backend infrastructure.
 */
import { useState, useRef, useEffect, useCallback, useMemo } from "react";
import { apiFetch, parseJSON } from "../../../utils/api";

type CopilotAction =
  | "generate" | "modify" | "explain" | "debug"
  | "refactor" | "test" | "secure" | "optimize";

type ChatMsg = { role: "user" | "assistant"; content: string; timestamp: number };

interface Props {
  onBuild: (prompt: string) => void;
  projectName: string;
  isBuilding: boolean;
  buildError: string | null;
  fileCount: number;
  language: string;
  currentSection: string;
  /** Initial prompt stored from Dashboard → sessionStorage */
  initialPrompt?: string;
}

// Simplified to 3 friendly actions — advanced actions (debug/refactor/test/secure/optimize)
// remain in the CopilotAction type for programmatic use but are hidden from the UI.
const ACTIONS: { id: CopilotAction; label: string; desc: string; color: string }[] = [
  { id: "generate", label: "✨ أضف / أبنِ", desc: "أضف ميزة جديدة أو ابنِ التطبيق من الصفر", color: "var(--accent)" },
  { id: "modify",   label: "✏️ عدّل",       desc: "غيّر شيئاً موجوداً في تطبيقك",           color: "var(--blue)"   },
  { id: "explain",  label: "💡 اشرح",       desc: "افهم كيف يعمل تطبيقك",                  color: "var(--teal)"   },
];

function actionPlaceholder(action: CopilotAction, projectName: string, error: string | null): string {
  const project = projectName || "this project";
  switch (action) {
    case "generate":  return `Describe what to build or add to ${project}…`;
    case "modify":    return `What do you want to change in ${project}?`;
    case "explain":   return `What part of ${project} would you like explained?`;
    case "debug":     return error ? `Analyzing: ${error.slice(0, 80)}…` : `Describe the bug or unexpected behavior in ${project}…`;
    case "refactor":  return `Which part of ${project} should be refactored and why?`;
    case "test":      return `What functionality in ${project} needs test coverage?`;
    case "secure":    return `Which security concern should be reviewed in ${project}?`;
    case "optimize":  return `What performance issue should be optimized in ${project}?`;
  }
}

function buildContextPrompt(action: CopilotAction, userMsg: string, ctx: {
  projectName: string; error: string | null; fileCount: number;
  language: string; section: string;
}): string {
  const projectInfo = ctx.projectName
    ? `Project: ${ctx.projectName}${ctx.language ? ` (${ctx.language})` : ""}. ${ctx.fileCount > 0 ? `${ctx.fileCount} files generated.` : ""}`
    : "No project loaded.";

  const errorCtx = ctx.error ? `\nCurrent build error: ${ctx.error}` : "";
  const sectionCtx = ctx.section !== "overview" ? `\nCurrent view: ${ctx.section}` : "";

  return `[Context: ${projectInfo}${errorCtx}${sectionCtx}]\n[Action: ${action}]\n${userMsg}`;
}

export function AICopilotPanel({
  onBuild,
  projectName,
  isBuilding,
  buildError,
  fileCount,
  language,
  currentSection,
  initialPrompt,
}: Props) {
  const [action, setAction] = useState<CopilotAction>("generate");
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState<string>(() => {
    // Consume the one-shot Dashboard prompt stored in sessionStorage
    const stored = sessionStorage.getItem("flow_builder_prompt");
    if (stored) { sessionStorage.removeItem("flow_builder_prompt"); return stored; }
    return initialPrompt ?? "";
  });
  const [loading, setLoading] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  // When a build error appears, derive the effective action to show in the UI.
  // We avoid a setState-in-effect by computing this at render time instead.
  const effectiveAction = useMemo<CopilotAction>(
    () => (buildError && action !== "debug" ? "debug" : action),
    [buildError, action],
  );

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const send = useCallback(async () => {
    const val = input.trim();
    if (!val || loading || isBuilding) return;
    setInput("");

    const now = Date.now();
    setMessages(prev => [...prev, { role: "user", content: val, timestamp: now }]);
    setLoading(true);

    // "generate" and "modify" always route to the build pipeline
    // (/api/build/stream), which uses dev_mock for the owner account and
    // real Claude for normal users.  This is the only path that actually
    // changes files in the project workspace.
    if (action === "generate" || action === "modify") {
      onBuild(val);
      setLoading(false);
      return;
    }

    // Informational actions (explain, debug, refactor…) → /api/ai/chat
    const contextualMsg = buildContextPrompt(action, val, {
      projectName, error: buildError, fileCount, language, section: currentSection,
    });

    try {
      const r = await apiFetch("/api/ai/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: contextualMsg,
          context: `app_builder_${action}`,
          app_name: projectName,
        }),
      });
      if (r.ok) {
        const data = await parseJSON<{ response: string }>(r, "/api/ai/chat");
        setMessages(prev => [...prev, { role: "assistant", content: data.response, timestamp: Date.now() }]);
      } else {
        // Surface the real error — never hide it behind a generic English message
        const errBody = await r.text().catch(() => "");
        setMessages(prev => [...prev, {
          role: "assistant",
          content: `⚠️ خطأ ${r.status}${errBody ? ": " + errBody.slice(0, 120) : ""}. حاول مرة أخرى.`,
          timestamp: Date.now(),
        }]);
      }
    } catch (err) {
      setMessages(prev => [...prev, {
        role: "assistant",
        content: `⚠️ تعذّر الاتصال: ${err instanceof Error ? err.message : "حاول مرة أخرى."}`,
        timestamp: Date.now(),
      }]);
    }
    setLoading(false);
  }, [input, loading, isBuilding, action, onBuild, projectName, buildError, fileCount, language, currentSection]);

  const currentAction = ACTIONS.find(a => a.id === effectiveAction)!;
  const placeholder = actionPlaceholder(effectiveAction, projectName, buildError);

  return (
    <div className="ab-copilot" style={{
      width: 300, flexShrink: 0,
      borderLeft: "1px solid var(--b1)",
      background: "var(--bg-surface)",
      display: "flex", flexDirection: "column",
      overflow: "hidden",
    }}>
      {/* Header */}
      <div style={{
        padding: "12px 14px 0",
        borderBottom: "1px solid var(--b1)",
        flexShrink: 0,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
          <div style={{
            width: 26, height: 26, borderRadius: 7, flexShrink: 0,
            background: "linear-gradient(135deg, var(--accent) 0%, var(--teal) 100%)",
            display: "flex", alignItems: "center", justifyContent: "center",
          }}>
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.2">
              <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/>
            </svg>
          </div>
          <div>
            <div style={{ fontSize: 12, fontWeight: 700, color: "var(--t1)" }}>مساعدي الذكي 🤖</div>
            <div style={{ fontSize: 10, display: "flex", alignItems: "center", gap: 3, color: isBuilding ? "var(--accent)" : "var(--green)" }}>
              <span style={{
                width: 4, height: 4, borderRadius: "50%",
                background: isBuilding ? "var(--accent)" : "var(--green)",
                display: "inline-block",
                animation: isBuilding ? "pulse 1s ease-in-out infinite" : "none",
              }} />
              {isBuilding ? "جارٍ البناء…" : "جاهز"}
            </div>
          </div>
        </div>

        {/* Action tabs — scrollable row */}
        <div style={{
          display: "flex", gap: 4, overflowX: "auto", paddingBottom: 10,
          scrollbarWidth: "none", msOverflowStyle: "none",
        }}>
          {ACTIONS.map(a => (
            <button
              key={a.id}
              onClick={() => setAction(a.id)}
              title={a.desc}
              style={{
                flexShrink: 0, padding: "4px 10px", borderRadius: 6, border: "none",
                cursor: "pointer", fontSize: 11, fontWeight: effectiveAction === a.id ? 700 : 500,
                background: effectiveAction === a.id ? a.color + "18" : "transparent",
                color: effectiveAction === a.id ? a.color : "var(--t4)",
                transition: "all 0.1s",
                borderBottom: effectiveAction === a.id ? `2px solid ${a.color}` : "2px solid transparent",
              }}
            >
              {a.label}
            </button>
          ))}
        </div>
      </div>

      {/* Action description */}
      <div style={{
        padding: "8px 14px", fontSize: 10, color: "var(--t5)",
        borderBottom: "1px solid var(--b1)", fontStyle: "italic", flexShrink: 0,
      }}>
        {currentAction.desc} {projectName ? `· ${projectName}` : ""}
      </div>

      {/* Messages */}
      <div style={{ flex: 1, overflowY: "auto", padding: "10px 12px" }}>
        {messages.length === 0 && (
          <div style={{ textAlign: "center", padding: "20px 8px" }}>
            {/* Action-specific prompts */}
            {action === "generate" ? (
              <>
                <div style={{ fontSize: 12, color: "var(--t4)", lineHeight: 1.6, marginBottom: 12 }}>
                  صِف ما تريد بناءه وسأنشئ التطبيق الكامل لك ✨
                </div>
                {["ابنِ نظام إدارة عملاء", "أنشئ نظام مخزون", "ابنِ تطبيق دعم العملاء"].map(s => (
                  <button
                    key={s}
                    onClick={() => setInput(s)}
                    style={{
                      width: "100%", textAlign: "left", padding: "8px 10px",
                      borderRadius: 8, border: "1px solid var(--b1)",
                      background: "var(--bg-card)", color: "var(--t3)",
                      fontSize: 11, cursor: "pointer", marginBottom: 5,
                      transition: "border-color 0.12s",
                    }}
                    onMouseEnter={e => (e.currentTarget.style.borderColor = "var(--accent)")}
                    onMouseLeave={e => (e.currentTarget.style.borderColor = "var(--b1)")}
                  >
                    "{s}"
                  </button>
                ))}
              </>
            ) : action === "debug" && buildError ? (
              <div style={{
                padding: "10px 12px", borderRadius: 8, fontSize: 12, color: "var(--red)",
                background: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.2)",
                lineHeight: 1.5, textAlign: "left",
              }}>
                <div style={{ fontWeight: 700, marginBottom: 4 }}>Current error:</div>
                {buildError}
                <div style={{ marginTop: 8 }}>
                  <button
                    onClick={() => setInput(`Explain this error and how to fix it: ${buildError}`)}
                    style={{
                      fontSize: 11, padding: "4px 10px", borderRadius: 6,
                      border: "1px solid rgba(239,68,68,0.3)", background: "rgba(239,68,68,0.1)",
                      color: "var(--red)", cursor: "pointer", fontWeight: 600,
                    }}
                  >
                    Explain & Fix →
                  </button>
                </div>
              </div>
            ) : (
              <div style={{ fontSize: 12, color: "var(--t4)", lineHeight: 1.6 }}>
                {currentAction.desc} — ask anything about {projectName || "your project"}.
              </div>
            )}
          </div>
        )}

        {messages.map((msg, i) => (
          <div key={i} style={{ marginBottom: 10 }}>
            {msg.role === "user" ? (
              <div style={{ display: "flex", justifyContent: "flex-end" }}>
                <div style={{
                  maxWidth: "88%", padding: "9px 11px",
                  borderRadius: "11px 11px 3px 11px",
                  background: "var(--accent)", color: "white",
                  fontSize: 12, lineHeight: 1.5,
                }}>
                  {msg.content}
                </div>
              </div>
            ) : (
              <div style={{ display: "flex", gap: 7, alignItems: "flex-start" }}>
                <div style={{
                  width: 22, height: 22, borderRadius: 6, flexShrink: 0,
                  background: `linear-gradient(135deg, ${currentAction.color}, var(--teal))`,
                  display: "flex", alignItems: "center", justifyContent: "center",
                }}>
                  <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5">
                    <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/>
                  </svg>
                </div>
                <div style={{
                  maxWidth: "88%", padding: "9px 11px",
                  borderRadius: "11px 11px 11px 3px",
                  background: "var(--bg-card)", border: "1px solid var(--b1)",
                  fontSize: 12, color: "var(--t1)", lineHeight: 1.6,
                  whiteSpace: "pre-wrap",
                }}>
                  {msg.content}
                </div>
              </div>
            )}
          </div>
        ))}

        {loading && (
          <div style={{ display: "flex", gap: 7, alignItems: "center", padding: "6px 0" }}>
            <div style={{
              width: 22, height: 22, borderRadius: 6, flexShrink: 0,
              background: `linear-gradient(135deg, ${currentAction.color}, var(--teal))`,
              display: "flex", alignItems: "center", justifyContent: "center",
            }}>
              <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5">
                <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/>
              </svg>
            </div>
            <div style={{ display: "flex", gap: 3 }}>
              {[0, 1, 2].map(i => (
                <div key={i} style={{
                  width: 5, height: 5, borderRadius: "50%", background: currentAction.color,
                  animation: `bounce 1s ease-in-out ${i * 0.15}s infinite`,
                }} />
              ))}
            </div>
          </div>
        )}
        <div ref={endRef} />
      </div>

      {/* Input */}
      <div style={{ padding: "10px 12px", borderTop: "1px solid var(--b1)", flexShrink: 0 }}>
        <div style={{ display: "flex", gap: 5, alignItems: "flex-end" }}>
          <textarea
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send(); } }}
            placeholder={isBuilding ? "Building in progress…" : placeholder}
            disabled={isBuilding}
            rows={2}
            style={{
              flex: 1, padding: "8px 10px", fontSize: 12,
              borderRadius: 8, border: "1px solid var(--b1)",
              background: isBuilding ? "var(--bg-base)" : "var(--bg-card)",
              color: "var(--t1)", resize: "none", outline: "none",
              fontFamily: "inherit", opacity: isBuilding ? 0.6 : 1,
            }}
            onFocus={e => (e.target.style.borderColor = currentAction.color)}
            onBlur={e => (e.target.style.borderColor = "var(--b1)")}
          />
          <button
            onClick={() => void send()}
            disabled={!input.trim() || loading || isBuilding}
            style={{
              width: 34, height: 34, borderRadius: 8, border: "none",
              background: input.trim() && !loading && !isBuilding ? currentAction.color : "var(--bg-card)",
              color: input.trim() && !loading && !isBuilding ? "white" : "var(--t5)",
              cursor: input.trim() && !loading && !isBuilding ? "pointer" : "default",
              display: "flex", alignItems: "center", justifyContent: "center",
              flexShrink: 0, transition: "all 0.12s",
            }}
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <line x1="22" y1="2" x2="11" y2="13"/>
              <polygon points="22 2 15 22 11 13 2 9 22 2"/>
            </svg>
          </button>
        </div>
      </div>
    </div>
  );
}
