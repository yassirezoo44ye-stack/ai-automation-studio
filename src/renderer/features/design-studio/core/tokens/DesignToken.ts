/**
 * Design Token system — centralized values for colors, typography,
 * spacing, radius, shadows, and effects. Objects reference token IDs
 * instead of raw values wherever possible.
 */
import { uid } from "../../utils/geometryUtils";

// ── Token categories ──────────────────────────────────────────────────────────

export type TokenCategory =
  | "color"
  | "typography"
  | "spacing"
  | "radius"
  | "shadow"
  | "effect"
  | "gradient"
  | "border";

// ── Base token ────────────────────────────────────────────────────────────────

export interface BaseToken {
  id:          string;
  name:        string;
  category:    TokenCategory;
  description?: string;
  /** Raw CSS value (fallback when token-aware props unavailable) */
  value:       string;
  createdAt:   string;
  updatedAt:   string;
}

// ── Specialised token shapes ──────────────────────────────────────────────────

export interface ColorToken extends BaseToken {
  category: "color";
  /** HEX / RGB / RGBA / HSL */
  value: string;
  alpha?: number;
}

export interface GradientStop { color: string; position: number }
export interface GradientToken extends BaseToken {
  category: "gradient";
  type:     "linear" | "radial" | "conic";
  angle?:   number;
  stops:    GradientStop[];
}

export interface TypographyToken extends BaseToken {
  category:   "typography";
  fontFamily: string;
  fontSize:   number;
  fontWeight: number | "bold" | "normal";
  lineHeight?: number;
  letterSpacing?: number;
  textTransform?: "none" | "uppercase" | "lowercase" | "capitalize";
}

export interface SpacingToken extends BaseToken {
  category: "spacing";
  /** px value */
  px: number;
}

export interface RadiusToken extends BaseToken {
  category: "radius";
  /** px value */
  px: number;
}

export interface ShadowToken extends BaseToken {
  category: "shadow";
  shadows: Array<{
    offsetX: number;
    offsetY: number;
    blur:    number;
    spread?: number;
    color:   string;
    inset?:  boolean;
  }>;
}

export interface EffectToken extends BaseToken {
  category: "effect";
  effects: Array<{
    type:    "blur" | "backdrop-blur" | "brightness" | "contrast" | "grayscale";
    amount:  number;
    unit:    "px" | "%";
  }>;
}

export interface BorderToken extends BaseToken {
  category: "border";
  width:    number;
  style:    "solid" | "dashed" | "dotted" | "double" | "none";
  color:    string;
}

export type DesignToken =
  | ColorToken
  | GradientToken
  | TypographyToken
  | SpacingToken
  | RadiusToken
  | ShadowToken
  | EffectToken
  | BorderToken;

// ── Factory helpers ───────────────────────────────────────────────────────────

function now() { return new Date().toISOString(); }

export function createColorToken(name: string, value: string, alpha?: number): ColorToken {
  return { id: uid(), name, category: "color", value, alpha, createdAt: now(), updatedAt: now() };
}

export function createSpacingToken(name: string, px: number): SpacingToken {
  return { id: uid(), name, category: "spacing", px, value: `${px}px`, createdAt: now(), updatedAt: now() };
}

export function createRadiusToken(name: string, px: number): RadiusToken {
  return { id: uid(), name, category: "radius", px, value: `${px}px`, createdAt: now(), updatedAt: now() };
}

export function createTypographyToken(name: string, props: Omit<TypographyToken, "id" | "name" | "category" | "value" | "createdAt" | "updatedAt">): TypographyToken {
  return {
    id: uid(), name, category: "typography",
    value: `${props.fontWeight} ${props.fontSize}px/${props.lineHeight ?? 1.5} ${props.fontFamily}`,
    createdAt: now(), updatedAt: now(),
    ...props,
  };
}
