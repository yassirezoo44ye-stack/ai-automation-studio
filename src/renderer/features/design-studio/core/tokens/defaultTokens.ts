/**
 * Default design token set — Axon Studio baseline.
 * Loaded into the TokenRegistry on startup.
 */
import {
  createColorToken, createSpacingToken, createRadiusToken, createTypographyToken,
} from "./DesignToken";
import type { ShadowToken, GradientToken } from "./DesignToken";
import { uid } from "../../utils/geometryUtils";

const now = () => new Date().toISOString();

// ── Colors ────────────────────────────────────────────────────────────────────

export const DEFAULT_COLOR_TOKENS = [
  createColorToken("primary",      "#4f46e5"),
  createColorToken("primary-light","#818cf8"),
  createColorToken("primary-dark", "#3730a3"),
  createColorToken("secondary",    "#06b6d4"),
  createColorToken("accent",       "#f59e0b"),
  createColorToken("success",      "#10b981"),
  createColorToken("warning",      "#f59e0b"),
  createColorToken("error",        "#ef4444"),
  createColorToken("neutral-50",   "#f9fafb"),
  createColorToken("neutral-100",  "#f3f4f6"),
  createColorToken("neutral-200",  "#e5e7eb"),
  createColorToken("neutral-300",  "#d1d5db"),
  createColorToken("neutral-400",  "#9ca3af"),
  createColorToken("neutral-500",  "#6b7280"),
  createColorToken("neutral-600",  "#4b5563"),
  createColorToken("neutral-700",  "#374151"),
  createColorToken("neutral-800",  "#1f2937"),
  createColorToken("neutral-900",  "#111827"),
  createColorToken("white",        "#ffffff"),
  createColorToken("black",        "#000000"),
];

// ── Spacing ───────────────────────────────────────────────────────────────────

export const DEFAULT_SPACING_TOKENS = [
  createSpacingToken("xs",    4),
  createSpacingToken("sm",    8),
  createSpacingToken("md",    16),
  createSpacingToken("lg",    24),
  createSpacingToken("xl",    32),
  createSpacingToken("2xl",   48),
  createSpacingToken("3xl",   64),
  createSpacingToken("4xl",   96),
];

// ── Radii ─────────────────────────────────────────────────────────────────────

export const DEFAULT_RADIUS_TOKENS = [
  createRadiusToken("none",   0),
  createRadiusToken("sm",     4),
  createRadiusToken("md",     8),
  createRadiusToken("lg",     12),
  createRadiusToken("xl",     16),
  createRadiusToken("2xl",    24),
  createRadiusToken("full",   9999),
];

// ── Typography ────────────────────────────────────────────────────────────────

export const DEFAULT_TYPOGRAPHY_TOKENS = [
  createTypographyToken("heading-xl",  { fontFamily: "Inter, sans-serif", fontSize: 48, fontWeight: 700, lineHeight: 1.2 }),
  createTypographyToken("heading-lg",  { fontFamily: "Inter, sans-serif", fontSize: 36, fontWeight: 700, lineHeight: 1.25 }),
  createTypographyToken("heading-md",  { fontFamily: "Inter, sans-serif", fontSize: 28, fontWeight: 600, lineHeight: 1.3 }),
  createTypographyToken("heading-sm",  { fontFamily: "Inter, sans-serif", fontSize: 22, fontWeight: 600, lineHeight: 1.35 }),
  createTypographyToken("body-lg",     { fontFamily: "Inter, sans-serif", fontSize: 18, fontWeight: 400, lineHeight: 1.6 }),
  createTypographyToken("body-md",     { fontFamily: "Inter, sans-serif", fontSize: 16, fontWeight: 400, lineHeight: 1.6 }),
  createTypographyToken("body-sm",     { fontFamily: "Inter, sans-serif", fontSize: 14, fontWeight: 400, lineHeight: 1.5 }),
  createTypographyToken("label",       { fontFamily: "Inter, sans-serif", fontSize: 12, fontWeight: 500, lineHeight: 1.4, letterSpacing: 0.05 }),
  createTypographyToken("caption",     { fontFamily: "Inter, sans-serif", fontSize: 11, fontWeight: 400, lineHeight: 1.4 }),
  createTypographyToken("mono",        { fontFamily: "'JetBrains Mono', monospace", fontSize: 14, fontWeight: 400, lineHeight: 1.5 }),
];

// ── Shadows ───────────────────────────────────────────────────────────────────

export const DEFAULT_SHADOW_TOKENS: ShadowToken[] = [
  { id: uid(), name: "shadow-sm",  category: "shadow", value: "0 1px 2px rgba(0,0,0,0.05)",  createdAt: now(), updatedAt: now(), shadows: [{ offsetX: 0, offsetY: 1, blur: 2,  color: "rgba(0,0,0,0.05)" }] },
  { id: uid(), name: "shadow-md",  category: "shadow", value: "0 4px 6px rgba(0,0,0,0.07)",  createdAt: now(), updatedAt: now(), shadows: [{ offsetX: 0, offsetY: 4, blur: 6,  color: "rgba(0,0,0,0.07)" }] },
  { id: uid(), name: "shadow-lg",  category: "shadow", value: "0 10px 15px rgba(0,0,0,0.1)", createdAt: now(), updatedAt: now(), shadows: [{ offsetX: 0, offsetY: 10, blur: 15, color: "rgba(0,0,0,0.1)"  }] },
  { id: uid(), name: "shadow-xl",  category: "shadow", value: "0 20px 25px rgba(0,0,0,0.1)", createdAt: now(), updatedAt: now(), shadows: [{ offsetX: 0, offsetY: 20, blur: 25, color: "rgba(0,0,0,0.1)"  }] },
];

// ── Gradients ─────────────────────────────────────────────────────────────────

export const DEFAULT_GRADIENT_TOKENS: GradientToken[] = [
  { id: uid(), name: "brand-gradient", category: "gradient", type: "linear", angle: 135, value: "linear-gradient(135deg, #4f46e5, #06b6d4)", createdAt: now(), updatedAt: now(), stops: [{ color: "#4f46e5", position: 0 }, { color: "#06b6d4", position: 1 }] },
  { id: uid(), name: "warm-gradient",  category: "gradient", type: "linear", angle: 135, value: "linear-gradient(135deg, #f59e0b, #ef4444)", createdAt: now(), updatedAt: now(), stops: [{ color: "#f59e0b", position: 0 }, { color: "#ef4444", position: 1 }] },
  { id: uid(), name: "cool-gradient",  category: "gradient", type: "linear", angle: 135, value: "linear-gradient(135deg, #06b6d4, #10b981)", createdAt: now(), updatedAt: now(), stops: [{ color: "#06b6d4", position: 0 }, { color: "#10b981", position: 1 }] },
];

// ── All combined ──────────────────────────────────────────────────────────────

export const ALL_DEFAULT_TOKENS = [
  ...DEFAULT_COLOR_TOKENS,
  ...DEFAULT_SPACING_TOKENS,
  ...DEFAULT_RADIUS_TOKENS,
  ...DEFAULT_TYPOGRAPHY_TOKENS,
  ...DEFAULT_SHADOW_TOKENS,
  ...DEFAULT_GRADIENT_TOKENS,
];
