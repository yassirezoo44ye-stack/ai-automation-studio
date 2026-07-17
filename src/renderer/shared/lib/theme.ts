import type React from "react";

export const S: Record<string, React.CSSProperties> = {
  // Layout
  root: {
    display: "flex", height: "100vh", overflow: "hidden",
    background: "linear-gradient(150deg,#05070f 0%,#080c1a 55%,#05070f 100%)",
    color: "#e2e8f0",
  },

  // Sidebar
  sidebar: {
    flexShrink: 0, display: "flex", flexDirection: "column",
    background: "rgba(7,9,18,0.92)", backdropFilter: "blur(24px)",
    borderRight: "1px solid rgba(255,215,0,0.14)",
    transition: "width 220ms cubic-bezier(.4,0,.2,1), min-width 220ms cubic-bezier(.4,0,.2,1)",
    overflow: "hidden",
  },
  sidebarLogo: {
    borderBottom: "1px solid rgba(255,215,0,0.10)",
    marginBottom: 8, display: "flex", alignItems: "center",
  },
  nav:           { display: "flex", flexDirection: "column", gap: 1 },
  navItem: {
    borderRadius: 9, fontSize: 13, fontWeight: 500,
    color: "rgba(148,163,184,0.65)", cursor: "pointer",
    display: "flex", alignItems: "center", gap: 10,
    whiteSpace: "nowrap", overflow: "hidden",
    userSelect: "none",
  },
  navItemActive: {
    background: "linear-gradient(135deg,rgba(255,215,0,0.22),rgba(212,175,55,0.16))",
    color: "#e2e8f0",
    boxShadow: "inset 0 0 0 1px rgba(255,215,0,0.28)",
  },
  main: { flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" },

  // Header
  header: {
    padding: "0 28px", height: 57, minHeight: 57,
    borderBottom: "1px solid rgba(255,255,255,0.06)",
    display: "flex", justifyContent: "space-between", alignItems: "center", flexShrink: 0,
    background: "rgba(7,9,18,0.7)", backdropFilter: "blur(16px)",
  },
  headerTitle: { fontSize: 15, fontWeight: 600, color: "#f1f5f9", letterSpacing: "-0.2px" },
  headerSub:   { fontSize: 12, color: "rgba(148,163,184,0.45)", fontWeight: 400 },

  // Cards
  card: {
    background: "rgba(255,255,255,0.032)",
    border: "1px solid rgba(255,255,255,0.075)",
    borderRadius: 16, padding: "20px 22px",
    backdropFilter: "blur(10px)",
  },
  cardTitle: { fontSize: 14, fontWeight: 600, color: "#f1f5f9", letterSpacing: "-0.1px" },
  muted:     { fontSize: 13, color: "rgba(148,163,184,0.6)", lineHeight: 1.5 },
  emptyState:{ textAlign: "center", padding: "60px 20px", color: "rgba(148,163,184,0.35)" },

  // Chat sidebar
  chatSidebar: {
    width: 230, flexShrink: 0, display: "flex", flexDirection: "column",
    background: "rgba(7,9,18,0.72)", backdropFilter: "blur(16px)",
    borderRight: "1px solid rgba(255,255,255,0.05)",
  },
  projectSelect: {
    width: "100%", background: "rgba(255,255,255,0.04)",
    border: "1px solid rgba(255,255,255,0.08)", borderRadius: 9,
    padding: "8px 12px", color: "#e2e8f0", fontSize: 12,
    cursor: "pointer",
  },
  newChatBtn: {
    width: "100%", background: "rgba(255,215,0,0.10)",
    border: "1px solid rgba(255,215,0,0.20)", borderRadius: 9,
    padding: "9px 12px", color: "rgba(167,139,250,0.85)", fontSize: 12,
    cursor: "pointer", textAlign: "left",
  },
  convItem:      { padding: "10px 14px", cursor: "pointer", transition: "background .15s" },
  convItemActive:{ background: "rgba(255,215,0,0.11)", borderRight: "2px solid #D4AF37" },
  convTitle:     { fontSize: 12, fontWeight: 500, color: "#e2e8f0", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" },
  convTime:      { fontSize: 10, color: "rgba(148,163,184,0.4)" },

  // Messages
  messages: {
    flex: 1, overflowY: "auto", padding: "32px 0",
    display: "flex", flexDirection: "column", gap: 0,
  },
  empty: { margin: "auto", textAlign: "center", color: "rgba(148,163,184,0.35)", paddingBottom: 80 },

  msgRowAssist: {
    display: "flex", gap: 14, alignItems: "flex-start",
    padding: "16px 32px", maxWidth: 900, width: "100%",
    animation: "slideIn .22s ease",
  },
  msgRowUser: {
    display: "flex", gap: 14, alignItems: "flex-start",
    padding: "16px 32px", maxWidth: 900, width: "100%",
    alignSelf: "flex-end", flexDirection: "row-reverse",
    animation: "slideIn .22s ease",
  },
  avatar: {
    width: 34, height: 34, borderRadius: 9, flexShrink: 0,
    background: "linear-gradient(135deg,rgba(255,215,0,0.30),rgba(212,175,55,0.22))",
    border: "1px solid rgba(255,215,0,0.28)",
    display: "flex", alignItems: "center", justifyContent: "center",
    marginTop: 2,
  },
  avatarUser: {
    width: 34, height: 34, borderRadius: 9, flexShrink: 0,
    background: "linear-gradient(135deg,#D4AF37,#FFD700)",
    display: "flex", alignItems: "center", justifyContent: "center",
    fontSize: 13, fontWeight: 700, color: "#fff", marginTop: 2,
  },
  msgLabelAssist: {
    fontSize: 11, fontWeight: 600, color: "rgba(167,139,250,0.75)",
    marginBottom: 7, display: "flex", alignItems: "center", gap: 8,
    letterSpacing: "0.04em", textTransform: "uppercase",
  },
  msgLabelUser: {
    fontSize: 11, fontWeight: 600, color: "rgba(148,163,184,0.45)",
    marginBottom: 7, display: "flex", alignItems: "center", gap: 8,
    justifyContent: "flex-end", letterSpacing: "0.04em", textTransform: "uppercase",
  },
  msgTime: { fontSize: 10, color: "rgba(148,163,184,0.28)", fontWeight: 400 },
  msgBubbleAssist: { fontSize: 15, color: "#e2e8f0", lineHeight: 1.8 },
  msgBubbleUser: {
    fontSize: 15, color: "#e2e8f0", lineHeight: 1.75,
    background: "linear-gradient(135deg,rgba(212,175,55,0.22),rgba(255,215,0,0.17))",
    border: "1px solid rgba(255,215,0,0.28)",
    borderRadius: 16, borderTopRightRadius: 4,
    padding: "12px 18px",
    boxShadow: "0 2px 16px rgba(212,175,55,0.10)",
    display: "inline-block",
  },

  // Input row
  inputRow: {
    padding: "14px 22px", gap: 10,
    borderTop: "1px solid rgba(255,255,255,0.06)",
    display: "flex", alignItems: "flex-end",
    background: "rgba(7,9,18,0.65)", backdropFilter: "blur(16px)",
  },
  input: {
    flex: 1, fontSize: 14, lineHeight: 1.6,
    background: "rgba(255,255,255,0.045)",
    border: "1px solid rgba(255,255,255,0.09)",
    borderRadius: 13, padding: "11px 16px",
    color: "#e2e8f0", maxHeight: 160, overflowY: "auto",
    transition: "border-color .18s, box-shadow .18s",
  },
  sendBtn: {
    width: 42, height: 42, borderRadius: 11, flexShrink: 0,
    background: "linear-gradient(135deg,#D4AF37,#FFD700)",
    color: "#fff", border: "none", fontSize: 18, cursor: "pointer",
    display: "flex", alignItems: "center", justifyContent: "center",
    boxShadow: "0 4px 14px rgba(255,215,0,0.40)",
  },

  // Forms
  textInput: {
    width: "100%", fontSize: 13,
    background: "rgba(255,255,255,0.040)",
    border: "1px solid rgba(255,255,255,0.08)",
    borderRadius: 9, padding: "10px 14px",
    color: "#e2e8f0", transition: "border-color .18s, box-shadow .18s",
  },
  label: { fontSize: 12, color: "rgba(148,163,184,0.6)", display: "block", marginBottom: 6, fontWeight: 500 },

  // Buttons
  btnPrimary: {
    background: "linear-gradient(135deg,#D4AF37,#FFD700)",
    color: "#fff", border: "none", borderRadius: 9,
    padding: "9px 20px", fontSize: 13, fontWeight: 600, cursor: "pointer",
    boxShadow: "0 3px 12px rgba(255,215,0,0.32)",
    transition: "filter .15s, transform .15s, box-shadow .15s",
  },
  btnSecondary: {
    background: "rgba(255,255,255,0.05)",
    color: "rgba(148,163,184,0.8)",
    border: "1px solid rgba(255,255,255,0.09)",
    borderRadius: 9, padding: "9px 20px", fontSize: 13, cursor: "pointer",
    transition: "background .15s, border-color .15s",
  },

  // Misc
  code: {
    background: "rgba(255,215,0,0.15)", padding: "2px 8px",
    borderRadius: 6, fontSize: 12, color: "#c4b5fd",
    fontFamily: "'Consolas','Courier New',monospace",
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
  badgeNeutral: { background: "rgba(148,163,184,.1)",  color: "rgba(148,163,184,.75)", border: "1px solid rgba(148,163,184,.18)" },
  badgeInfo:    { background: "rgba(212,175,55,.15)",  color: "#a5b4fc",               border: "1px solid rgba(212,175,55,.3)" },
  badgeSuccess: { background: "rgba(52,211,153,.12)",  color: "#34d399",               border: "1px solid rgba(52,211,153,.3)" },
  badgeWarning: { background: "rgba(251,191,36,.12)",  color: "#fbbf24",               border: "1px solid rgba(251,191,36,.3)" },
  badgeError:   { background: "rgba(248,113,113,.12)", color: "#f87171",               border: "1px solid rgba(248,113,113,.3)" },
  dot:          { width: 6, height: 6, borderRadius: "50%", background: "currentColor" },

  // Panels — dark glass surfaces used by Build/Run so the workspace UI shares
  // the same palette as the rest of the app instead of its own blue-gray set.
  panelDark:     { background: "rgba(5,7,15,.6)", borderRight: "1px solid rgba(255,255,255,.06)" },
  panelDivider:  { borderBottom: "1px solid rgba(255,255,255,.06)" },
  errorPanel: {
    margin: "10px 12px", padding: "12px 14px", borderRadius: 12,
    background: "rgba(248,113,113,.08)", border: "1px solid rgba(248,113,113,.25)",
    fontSize: 12, color: "#fca5a5", lineHeight: 1.6,
  },
  errorPanelTitle: { display: "flex", alignItems: "center", gap: 6, fontWeight: 600, color: "#f87171", marginBottom: 6, fontSize: 12 },
};

export type StatusBadgeKind = "neutral" | "info" | "success" | "warning" | "error";
export const BADGE_STYLE: Record<StatusBadgeKind, React.CSSProperties> = {
  neutral: S.badgeNeutral, info: S.badgeInfo, success: S.badgeSuccess, warning: S.badgeWarning, error: S.badgeError,
};

// ── Semantic color tokens ─────────────────────────────────────────────────────
// Single source for the status/accent colors that were previously hardcoded
// per-file (values unchanged — this is centralization, not a redesign).
export const C = {
  green:       "#00C853",   // success
  greenBright: "#00E676",   // success (bright variant)
  red:         "#FF5252",   // danger
  redSoft:     "#FF6E6E",   // danger (soft)
  amber:       "#FFB300",   // warning
  blue:        "#6c8ef7",   // info / running
  purple:      "#E6C558",
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
