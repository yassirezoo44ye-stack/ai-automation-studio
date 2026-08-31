/**
 * AICommandBarInline — persistent AI command bar at the bottom of Design Studio.
 *
 * This is the primary entry point for the AI-first design workflow. Always
 * visible at the bottom of the canvas — the user types a design command and the
 * AI executes it directly on the canvas via structured design operations.
 *
 * Context-awareness:
 *  - When an element is selected, commands like "make it bigger" or "change color to blue"
 *    are scoped to that element automatically.
 *  - When nothing is selected, commands apply to the whole page.
 *
 * Quick actions:
 *  - Pre-filled chips for the most common tasks so the user never has to type
 *    from scratch.
 */
import { useState, useRef, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";

// ── Types ─────────────────────────────────────────────────────────────────────

export type AICommandStatus = "idle" | "running" | "done" | "error";

export interface AICommandResult {
  /** Human-readable summary of what the AI did, e.g. "Added a Hero section." */
  message: string;
  /** Whether the AI automatically switched to a fallback provider */
  providerSwitched?: boolean;
  previousProvider?: string;
  currentProvider?: string;
}

interface Props {
  /** IDs of currently selected canvas elements (empty = nothing selected) */
  selectedIds: string[];
  /** Called when the user submits a command; implementation runs AI and returns result */
  onCommand: (prompt: string, selectedIds: string[]) => Promise<AICommandResult>;
  /** i18n namespace is "designStudio" */
  className?: string;
}

// ── Quick action chips ────────────────────────────────────────────────────────

const QUICK_ACTIONS_AR = [
  "صمم صفحة هبوط SaaS",
  "أضف قسم Hero",
  "حسّن التصميم",
  "اجعلها مناسبة للجوال",
  "اجعل العنوان أكبر",
  "غيّر اللون إلى أزرق",
  "أضف زر Call to Action",
  "اجعلها RTL",
];

const QUICK_ACTIONS_EN = [
  "Design a SaaS landing page",
  "Add a Hero section",
  "Improve the design",
  "Make it mobile-friendly",
  "Make the title bigger",
  "Change color to blue",
  "Add a CTA button",
  "Make it RTL",
];

// ── Component ─────────────────────────────────────────────────────────────────

export function AICommandBarInline({ selectedIds, onCommand, className }: Props) {
  const { i18n } = useTranslation("designStudio");
  const isAr = i18n.language.startsWith("ar");

  const [prompt, setPrompt]     = useState("");
  const [status, setStatus]     = useState<AICommandStatus>("idle");
  const [result, setResult]     = useState<AICommandResult | null>(null);
  const [error, setError]       = useState<string | null>(null);

  const inputRef    = useRef<HTMLTextAreaElement>(null);
  const mountedRef  = useRef(true);

  useEffect(() => {
    return () => { mountedRef.current = false; };
  }, []);

  const hasSelection = selectedIds.length > 0;
  const quickActions = isAr ? QUICK_ACTIONS_AR : QUICK_ACTIONS_EN;

  const placeholder = isAr
    ? (hasSelection ? "عدّل العنصر المحدد…" : "ماذا تريد أن أصمم؟")
    : (hasSelection ? "Edit the selected element…" : "What would you like to design?");

  const handleSubmit = useCallback(async () => {
    const p = prompt.trim();
    if (!p || status === "running") return;

    setStatus("running");
    setResult(null);
    setError(null);

    try {
      const res = await onCommand(p, selectedIds);
      if (!mountedRef.current) return;
      setResult(res);
      setStatus("done");
      setPrompt("");
    } catch (err) {
      if (!mountedRef.current) return;
      setError(err instanceof Error ? err.message : String(err));
      setStatus("error");
    }
  }, [prompt, status, onCommand, selectedIds]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void handleSubmit();
    }
  }, [handleSubmit]);

  const handleQuickAction = useCallback((text: string) => {
    setPrompt(text);
    inputRef.current?.focus();
  }, []);

  const handleReset = useCallback(() => {
    setStatus("idle");
    setResult(null);
    setError(null);
    setPrompt("");
    inputRef.current?.focus();
  }, []);

  // ── Layout tokens ──────────────────────────────────────────────────────────

  const dir = isAr ? "rtl" : "ltr";

  return (
    <div
      dir={dir}
      className={className}
      style={{
        display:          "flex",
        flexDirection:    "column",
        gap:              8,
        padding:          "10px 14px 10px",
        borderTop:        "1px solid var(--border)",
        background:       "var(--surface-1)",
        flexShrink:       0,
        /* Android safe-area: padding-bottom includes home bar */
        paddingBottom:    "calc(10px + env(safe-area-inset-bottom, 0px))",
      }}
    >
      {/* ── Context badge ───────────────────────────────────────────────── */}
      {hasSelection && (
        <div style={{
          display:      "inline-flex",
          alignItems:   "center",
          gap:          4,
          padding:      "2px 8px",
          background:   "color-mix(in srgb, var(--accent) 12%, var(--surface-2))",
          borderRadius: 20,
          fontSize:     11,
          color:        "var(--text-accent)",
          alignSelf:    "flex-start",
        }}>
          <span style={{ opacity: 0.7 }}>✦</span>
          <span>
            {isAr
              ? `${selectedIds.length} عنصر محدد`
              : `${selectedIds.length} element${selectedIds.length > 1 ? "s" : ""} selected`}
          </span>
        </div>
      )}

      {/* ── Input row ──────────────────────────────────────────────────── */}
      <div style={{ display: "flex", gap: 8, alignItems: "flex-end" }}>
        <textarea
          ref={inputRef}
          value={prompt}
          onChange={e => setPrompt(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          rows={1}
          disabled={status === "running"}
          style={{
            flex:         1,
            resize:       "none",
            overflowY:    "auto",
            maxHeight:    100,
            padding:      "10px 12px",
            border:       "1.5px solid var(--border)",
            borderRadius: 10,
            background:   "var(--surface-2)",
            color:        "var(--text-primary)",
            fontSize:     14,
            lineHeight:   1.45,
            fontFamily:   "inherit",
            outline:      "none",
            transition:   "border-color 0.15s",
            direction:    dir,
          }}
          onFocus={e  => { e.target.style.borderColor = "var(--border-accent, var(--accent))"; }}
          onBlur={e   => { e.target.style.borderColor = "var(--border)"; }}
          aria-label={isAr ? "أمر تصميم AI" : "AI design command"}
        />

        {/* Submit button */}
        <button
          onClick={() => void handleSubmit()}
          disabled={!prompt.trim() || status === "running"}
          title={isAr ? "تنفيذ (Enter)" : "Execute (Enter)"}
          aria-label={isAr ? "تنفيذ" : "Execute"}
          style={{
            width:        44,
            height:       44,
            flexShrink:   0,
            border:       "none",
            borderRadius: 10,
            background:   prompt.trim() && status !== "running"
                            ? "var(--fill-accent, var(--accent))"
                            : "var(--surface-2)",
            color:        prompt.trim() && status !== "running" ? "#fff" : "var(--text-muted)",
            fontSize:     20,
            cursor:       prompt.trim() && status !== "running" ? "pointer" : "default",
            display:      "flex",
            alignItems:   "center",
            justifyContent: "center",
            transition:   "background 0.15s, color 0.15s",
            touchAction:  "manipulation",
          }}
        >
          {status === "running" ? (
            <span style={{ animation: "spin 1s linear infinite", display: "inline-block", fontSize: 16 }}>⟳</span>
          ) : (
            "↵"
          )}
        </button>
      </div>

      {/* ── Status feedback ─────────────────────────────────────────────── */}
      {status === "done" && result && (
        <div style={{
          display:      "flex",
          alignItems:   "center",
          gap:          8,
          padding:      "6px 10px",
          borderRadius: 8,
          background:   "color-mix(in srgb, var(--color-success, #22c55e) 10%, var(--surface-2))",
          border:       "1px solid color-mix(in srgb, var(--color-success, #22c55e) 25%, transparent)",
        }}>
          <span style={{ color: "var(--color-success, #22c55e)", fontSize: 14 }}>✓</span>
          <span style={{ fontSize: 12, color: "var(--text-primary)", flex: 1 }}>
            {result.message}
          </span>
          {result.providerSwitched && (
            <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
              {isAr
                ? `تم التحويل إلى ${result.currentProvider}`
                : `Switched to ${result.currentProvider}`}
            </span>
          )}
          <button
            onClick={handleReset}
            style={{
              border: "none", background: "none",
              color: "var(--text-muted)", cursor: "pointer",
              fontSize: 14, padding: "0 2px",
            }}
            aria-label={isAr ? "إغلاق" : "Dismiss"}
          >
            ×
          </button>
        </div>
      )}

      {(status === "error" || error) && (
        <div style={{
          display:      "flex",
          alignItems:   "center",
          gap:          8,
          padding:      "6px 10px",
          borderRadius: 8,
          background:   "color-mix(in srgb, var(--color-danger, #ef4444) 10%, var(--surface-2))",
          border:       "1px solid color-mix(in srgb, var(--color-danger, #ef4444) 25%, transparent)",
        }}>
          <span style={{ color: "var(--color-danger, #ef4444)", fontSize: 14 }}>⚠</span>
          <span style={{ fontSize: 12, color: "var(--text-primary)", flex: 1 }}>
            {error ?? (isAr ? "حدث خطأ. حاول مجدداً." : "An error occurred. Please try again.")}
          </span>
          <button
            onClick={handleReset}
            style={{
              border: "none", background: "none",
              color: "var(--text-muted)", cursor: "pointer",
              fontSize: 14, padding: "0 2px",
            }}
            aria-label={isAr ? "إغلاق" : "Dismiss"}
          >
            ×
          </button>
        </div>
      )}

      {/* ── Quick action chips ──────────────────────────────────────────── */}
      {status === "idle" && (
        <ul
          aria-label={isAr ? "إجراءات سريعة" : "Quick actions"}
          style={{
            display:    "flex",
            gap:        6,
            overflowX:  "auto",
            scrollbarWidth: "none",
            paddingBottom: 2,
            listStyle:  "none",
            margin:     0,
            padding:    0,
          }}
        >
          {quickActions.map((action, i) => (
            <li key={i} style={{ flexShrink: 0 }}>
              <button
                onClick={() => handleQuickAction(action)}
                style={{
                  padding:      "5px 12px",
                  fontSize:     12,
                  background:   "var(--surface-2)",
                  border:       "1px solid var(--border)",
                  borderRadius: 20,
                  color:        "var(--text-secondary)",
                  cursor:       "pointer",
                  whiteSpace:   "nowrap",
                  transition:   "border-color 0.12s, color 0.12s",
                  touchAction:  "manipulation",
                  minHeight:    32,  /* touch target */
                }}
                onMouseEnter={e => {
                  const el = e.currentTarget as HTMLButtonElement;
                  el.style.borderColor = "var(--border-accent, var(--accent))";
                  el.style.color = "var(--text-accent, var(--accent))";
                }}
                onMouseLeave={e => {
                  const el = e.currentTarget as HTMLButtonElement;
                  el.style.borderColor = "var(--border)";
                  el.style.color = "var(--text-secondary)";
                }}
              >
                {action}
              </button>
            </li>
          ))}
        </ul>
      )}

      {/* Spin keyframe */}
      <style>{`@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}
