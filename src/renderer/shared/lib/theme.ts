import type React from "react";

export const S: Record<string, React.CSSProperties> = {
  // Layout
  root: {
    display: "flex", height: "100vh", overflow: "hidden",
    background: "linear-gradient(150deg,#090909 0%,#111111 55%,#090909 100%)",
    color: "#F2F2F2",
  },

  // Sidebar
  sidebar: {
    flexShrink: 0, display: "flex", flexDirection: "column",
    background: "rgba(9,9,9,0.92)", backdropFilter: "blur(24px)",
    borderRight: "1px solid rgba(255,215,0,0.12)",
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
    color: "rgba(189,189,189,0.65)", cursor: "pointer",
    display: "flex", alignItems: "center", gap: 10,
    whiteSpace: "nowrap", overflow: "hidden",
    userSelect: "none",
  },
  navItemActive: {
    background: "linear-gradient(135deg,rgba(255,215,0,0.16),rgba(212,175,55,0.10))",
    color: "#FFD700",
    boxShadow: "inset 0 0 0 1px rgba(255,215,0,0.25)",
  },
  main: { flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" },

  // Header
  header: {
    padding: "0 28px", height: 57, minHeight: 57,
    borderBottom: "1px solid rgba(255,215,0,0.08)",
    display: "flex", justifyContent: "space-between", alignItems: "center", flexShrink: 0,
    background: "rgba(9,9,9,0.7)", backdropFilter: "blur(16px)",
  },
  headerTitle: { fontSize: 15, fontWeight: 600, color: "#FFFFFF", letterSpacing: "-0.2px" },
  headerSub:   { fontSize: 12, color: "rgba(189,189,189,0.45)", fontWeight: 400 },

  // Cards
  card: {
    background: "rgba(255,255,255,0.028)",
    border: "1px solid rgba(255,215,0,0.12)",
    borderRadius: 16, padding: "20px 22px",
    backdropFilter: "blur(10px)",
  },
  cardTitle: { fontSize: 14, fontWeight: 600, color: "#FFFFFF", letterSpacing: "-0.1px" },
  muted:     { fontSize: 13, color: "rgba(189,189,189,0.6)", lineHeight: 1.5 },
  emptyState:{ textAlign: "center", padding: "60px 20px", color: "rgba(189,189,189,0.35)" },

  // Chat sidebar
  chatSidebar: {
    width: 230, flexShrink: 0, display: "flex", flexDirection: "column",
    background: "rgba(9,9,9,0.72)", backdropFilter: "blur(16px)",
    borderRight: "1px solid rgba(255,215,0,0.08)",
  },
  projectSelect: {
    width: "100%", background: "rgba(255,255,255,0.04)",
    border: "1px solid rgba(255,215,0,0.12)", borderRadius: 9,
    padding: "8px 12px", color: "#F2F2F2", fontSize: 12,
    cursor: "pointer",
  },
  newChatBtn: {
    width: "100%", background: "rgba(255,215,0,0.08)",
    border: "1px solid rgba(255,215,0,0.20)", borderRadius: 9,
    padding: "9px 12px", color: "rgba(255,215,0,0.85)", fontSize: 12,
    cursor: "pointer", textAlign: "left",
  },
  convItem:      { padding: "10px 14px", cursor: "pointer", transition: "background .15s" },
  convItemActive:{ background: "rgba(255,215,0,0.09)", borderRight: "2px solid #FFD700" },
  convTitle:     { fontSize: 12, fontWeight: 500, color: "#F2F2F2", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" },
  convTime:      { fontSize: 10, color: "rgba(189,189,189,0.4)" },

  // Messages
  messages: {
    flex: 1, overflowY: "auto", padding: "32px 0",
    display: "flex", flexDirection: "column", gap: 0,
  },
  empty: { margin: "auto", textAlign: "center", color: "rgba(189,189,189,0.35)", paddingBottom: 80 },

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
    background: "linear-gradient(135deg,rgba(255,215,0,0.28),rgba(212,175,55,0.20))",
    border: "1px solid rgba(255,215,0,0.25)",
    display: "flex", alignItems: "center", justifyContent: "center",
    marginTop: 2,
  },
  avatarUser: {
    width: 34, height: 34, borderRadius: 9, flexShrink: 0,
    background: "linear-gradient(135deg,#FFD700,#D4AF37)",
    display: "flex", alignItems: "center", justifyContent: "center",
    fontSize: 13, fontWeight: 700, color: "#0a0a0a", marginTop: 2,
  },
  msgLabelAssist: {
    fontSize: 11, fontWeight: 600, color: "rgba(255,215,0,0.75)",
    marginBottom: 7, display: "flex", alignItems: "center", gap: 8,
    letterSpacing: "0.04em", textTransform: "uppercase",
  },
  msgLabelUser: {
    fontSize: 11, fontWeight: 600, color: "rgba(189,189,189,0.45)",
    marginBottom: 7, display: "flex", alignItems: "center", gap: 8,
    justifyContent: "flex-end", letterSpacing: "0.04em", textTransform: "uppercase",
  },
  msgTime: { fontSize: 10, color: "rgba(189,189,189,0.28)", fontWeight: 400 },
  msgBubbleAssist: { fontSize: 15, color: "#F2F2F2", lineHeight: 1.8 },
  msgBubbleUser: {
    fontSize: 15, color: "#F2F2F2", lineHeight: 1.75,
    background: "linear-gradient(135deg,rgba(255,215,0,0.14),rgba(212,175,55,0.10))",
    border: "1px solid rgba(255,215,0,0.25)",
    borderRadius: 16, borderTopRightRadius: 4,
    padding: "12px 18px",
    boxShadow: "0 2px 16px rgba(255,215,0,0.06)",
    display: "inline-block",
  },

  // Input row
  inputRow: {
    padding: "14px 22px", gap: 10,
    borderTop: "1px solid rgba(255,215,0,0.08)",
    display: "flex", alignItems: "flex-end",
    background: "rgba(9,9,9,0.65)", backdropFilter: "blur(16px)",
  },
  input: {
    flex: 1, fontSize: 14, lineHeight: 1.6,
    background: "rgba(255,255,255,0.045)",
    border: "1px solid rgba(255,215,0,0.12)",
    borderRadius: 13, padding: "11px 16px",
    color: "#F2F2F2", maxHeight: 160, overflowY: "auto",
    transition: "border-color .18s, box-shadow .18s",
  },
  sendBtn: {
    width: 42, height: 42, borderRadius: 11, flexShrink: 0,
    background: "linear-gradient(135deg,#FFD700,#D4AF37)",
    color: "#0a0a0a", border: "none", fontSize: 18, cursor: "pointer",
    display: "flex", alignItems: "center", justifyContent: "center",
    boxShadow: "0 4px 14px rgba(255,215,0,0.30)",
  },

  // Forms
  textInput: {
    width: "100%", fontSize: 13,
    background: "rgba(255,255,255,0.040)",
    border: "1px solid rgba(255,215,0,0.12)",
    borderRadius: 9, padding: "10px 14px",
    color: "#F2F2F2", transition: "border-color .18s, box-shadow .18s",
  },
  label: { fontSize: 12, color: "rgba(189,189,189,0.6)", display: "block", marginBottom: 6, fontWeight: 500 },

  // Buttons
  btnPrimary: {
    background: "linear-gradient(135deg,#FFD700,#D4AF37)",
    color: "#0a0a0a", border: "none", borderRadius: 9,
    padding: "9px 20px", fontSize: 13, fontWeight: 700, cursor: "pointer",
    boxShadow: "0 3px 12px rgba(255,215,0,0.25)",
    transition: "filter .15s, transform .15s, box-shadow .15s",
  },
  btnSecondary: {
    background: "rgba(255,255,255,0.05)",
    color: "rgba(189,189,189,0.8)",
    border: "1px solid rgba(255,215,0,0.12)",
    borderRadius: 9, padding: "9px 20px", fontSize: 13, cursor: "pointer",
    transition: "background .15s, border-color .15s",
  },

  // Misc
  code: {
    background: "rgba(255,215,0,0.10)", padding: "2px 8px",
    borderRadius: 6, fontSize: 12, color: "#FFE58A",
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
  badgeNeutral: { background: "rgba(189,189,189,.1)",  color: "rgba(189,189,189,.75)", border: "1px solid rgba(189,189,189,.18)" },
  badgeInfo:    { background: "rgba(232,200,125,.12)", color: "#E8C87D",               border: "1px solid rgba(232,200,125,.3)" },
  badgeSuccess: { background: "rgba(0,200,83,.12)",    color: "#00C853",               border: "1px solid rgba(0,200,83,.3)" },
  badgeWarning: { background: "rgba(255,179,0,.12)",   color: "#FFB300",               border: "1px solid rgba(255,179,0,.3)" },
  badgeError:   { background: "rgba(255,82,82,.12)",   color: "#FF5252",               border: "1px solid rgba(255,82,82,.3)" },
  dot:          { width: 6, height: 6, borderRadius: "50%", background: "currentColor" },

  // Panels — dark glass surfaces used by Build/Run so the workspace UI shares
  // the same palette as the rest of the app instead of its own blue-gray set.
  panelDark:     { background: "rgba(9,9,9,.6)", borderRight: "1px solid rgba(255,215,0,.08)" },
  panelDivider:  { borderBottom: "1px solid rgba(255,215,0,.08)" },
  errorPanel: {
    margin: "10px 12px", padding: "12px 14px", borderRadius: 12,
    background: "rgba(255,82,82,.08)", border: "1px solid rgba(255,82,82,.25)",
    fontSize: 12, color: "#FF8A80", lineHeight: 1.6,
  },
  errorPanelTitle: { display: "flex", alignItems: "center", gap: 6, fontWeight: 600, color: "#FF5252", marginBottom: 6, fontSize: 12 },
};

export type StatusBadgeKind = "neutral" | "info" | "success" | "warning" | "error";
export const BADGE_STYLE: Record<StatusBadgeKind, React.CSSProperties> = {
  neutral: S.badgeNeutral, info: S.badgeInfo, success: S.badgeSuccess, warning: S.badgeWarning, error: S.badgeError,
};
