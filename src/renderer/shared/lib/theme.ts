import type React from "react";

// Only keys with real consumers are kept here (verified via `grep -rn "S\.<key>"
// src/renderer` against the files that actually `import { S } from ".../theme"` —
// several page-local `const S = {...}` objects elsewhere share the name but are
// unrelated). Dead keys from earlier redesign passes were removed rather than
// re-themed.
export const S: Record<string, React.CSSProperties> = {
  // Header — uses the same theme-reactive tokens GlassCard/GoldButton read
  // (var(--bg-glass)/var(--border)/var(--t1)/var(--t4)), not fixed hex/rgba,
  // so every page's header follows Light/Dark/High Contrast switches instead
  // of staying permanently dark underneath a now-light page body.
  header: {
    padding: "0 28px", height: 57, minHeight: 57,
    borderBottom: "1px solid var(--border)",
    display: "flex", justifyContent: "space-between", alignItems: "center", flexShrink: 0,
    background: "var(--bg-glass)",
  },
  headerTitle: { fontSize: 15, fontWeight: 600, color: "var(--t1)", letterSpacing: "-0.2px" },
  headerSub:   { fontSize: 12, color: "var(--t4)", fontWeight: 400 },

  // Cards
  card: {
    background: "var(--bg-card)",
    border: "1px solid var(--b1)",
    borderRadius: 16, padding: "20px 22px",
  },
  cardTitle: { fontSize: 14, fontWeight: 600, color: "var(--t1)", letterSpacing: "-0.1px" },

  // Chat / Social Q&A shared bits
  projectSelect: {
    width: "100%", background: "var(--bg-input)",
    border: "1px solid var(--b1)", borderRadius: 9,
    padding: "8px 12px", color: "var(--t1)", fontSize: 12,
    cursor: "pointer",
  },
  avatar: {
    width: 34, height: 34, borderRadius: 9, flexShrink: 0,
    background: "linear-gradient(135deg,rgba(110,50,224,0.30),rgba(11,122,112,0.22))",
    border: "1px solid rgba(110,50,224,0.28)",
    display: "flex", alignItems: "center", justifyContent: "center",
    marginTop: 2,
  },
  msgLabelAssist: {
    fontSize: 11, fontWeight: 600, color: "var(--ta)",
    marginBottom: 7, display: "flex", alignItems: "center", gap: 8,
    letterSpacing: "0.04em", textTransform: "uppercase",
  },

  // Input row
  inputRow: {
    padding: "14px 22px", gap: 10,
    borderTop: "1px solid var(--b1)",
    display: "flex", alignItems: "flex-end",
    background: "var(--bg-surface)",
  },
  input: {
    flex: 1, fontSize: 14, lineHeight: 1.6,
    background: "var(--bg-input)",
    border: "1px solid var(--b1)",
    borderRadius: 13, padding: "11px 16px",
    color: "var(--t1)", maxHeight: 160, overflowY: "auto",
    transition: "border-color .18s, box-shadow .18s",
  },
  sendBtn: {
    width: 42, height: 42, borderRadius: 11, flexShrink: 0,
    background: "linear-gradient(135deg,var(--accent),var(--teal))",
    color: "#fff", border: "none", fontSize: 18, cursor: "pointer",
    display: "flex", alignItems: "center", justifyContent: "center",
    boxShadow: "0 4px 14px rgba(110,50,224,0.40)",
  },

  // Forms
  textInput: {
    width: "100%", fontSize: 13,
    background: "var(--bg-input)",
    border: "1px solid var(--b1)",
    borderRadius: 9, padding: "10px 14px",
    color: "var(--t1)", transition: "border-color .18s, box-shadow .18s",
  },

  // Buttons
  btnPrimary: {
    background: "linear-gradient(135deg,var(--accent),var(--teal))",
    color: "#fff", border: "none", borderRadius: 9,
    padding: "9px 20px", fontSize: 13, fontWeight: 600, cursor: "pointer",
    boxShadow: "0 3px 12px rgba(110,50,224,0.32)",
    transition: "filter .15s, transform .15s, box-shadow .15s",
  },
  btnSecondary: {
    background: "var(--bg-hover)",
    color: "var(--t3)",
    border: "1px solid var(--b1)",
    borderRadius: 9, padding: "9px 20px", fontSize: 13, cursor: "pointer",
    transition: "background .15s, border-color .15s",
  },

  // Status badges — shared vocabulary for Build Status / Runtime Status / any
  // other state indicator, so every page reads the same visual language
  // instead of ad-hoc colored text.
  badge: {
    display: "inline-flex", alignItems: "center", gap: 6,
    padding: "3px 10px", borderRadius: 999,
    fontSize: 11, fontWeight: 600, letterSpacing: "0.01em",
    whiteSpace: "nowrap",
  },
  badgeNeutral: { background: "var(--bg-hover)",       color: "var(--t3)", border: "1px solid var(--b1)" },
  badgeInfo:    { background: "rgba(110,50,224,.15)",  color: "var(--ta)", border: "1px solid rgba(110,50,224,.3)" },
  badgeSuccess: { background: "rgba(22,163,74,.12)",   color: "#16A34A",   border: "1px solid rgba(22,163,74,.3)" },
  badgeWarning: { background: "rgba(161,98,7,.12)",    color: "#A16207",   border: "1px solid rgba(161,98,7,.3)" },
  badgeError:   { background: "rgba(220,38,38,.12)",   color: "#DC2626",   border: "1px solid rgba(220,38,38,.3)" },
  dot:          { width: 6, height: 6, borderRadius: "50%", background: "currentColor" },
};

export type StatusBadgeKind = "neutral" | "info" | "success" | "warning" | "error";
export const BADGE_STYLE: Record<StatusBadgeKind, React.CSSProperties> = {
  neutral: S.badgeNeutral, info: S.badgeInfo, success: S.badgeSuccess, warning: S.badgeWarning, error: S.badgeError,
};

// ── Semantic color tokens ─────────────────────────────────────────────────────
// Single source for the status/accent colors that were previously hardcoded
// per-file (values unchanged — this is centralization, not a redesign).
export const C = {
  green:       "#16A34A",   // success
  greenBright: "#22C55E",   // success (bright variant)
  red:         "#DC2626",   // danger
  redSoft:     "#EF4444",   // danger (soft)
  amber:       "#A16207",   // warning
  blue:        "#2563EB",   // info / running
  purple:      "#8B5CF6",   // was mislabeled gold (#E6C558) — now an actual purple
  sky:         "#38bdf8",
  pink:        "#f472b6",
  orange:      "#fb923c",
  gray:        "#6b7280",   // muted / pending
  grayBlue:    "#6b7a99",   // muted text on dark
  slate:       "#4b5980",
} as const;

/** `withAlpha(C.red, "22")` — replaces the `color + "22"` literal-suffix pattern. */
export function withAlpha(hex: string, alpha: string): string {
  return hex + alpha;
}
