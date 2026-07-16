/**
 * Expanded Brand Kit types.
 * Extends the basic BrandKit from canvas.types.ts with
 * gradients, icons, spacing presets, and typography presets.
 */
import { uid } from "../../utils/geometryUtils";

// ── Primitives ────────────────────────────────────────────────────────────────

export interface BrandColor {
  id:    string;
  name:  string;
  value: string;   // HEX
  shade?: "50" | "100" | "200" | "300" | "400" | "500" | "600" | "700" | "800" | "900";
}

export interface BrandGradient {
  id:    string;
  name:  string;
  css:   string;   // full CSS gradient string
  stops: Array<{ color: string; position: number }>;
  angle?: number;
  type:  "linear" | "radial" | "conic";
}

export interface BrandFont {
  id:      string;
  name:    string;
  family:  string;
  weights: number[];
  url?:    string;  // Google Fonts or CDN URL
}

export interface BrandLogo {
  id:      string;
  name:    string;
  src:     string;  // data URL
  variant: "primary" | "inverted" | "monochrome" | "icon";
}

export interface BrandIcon {
  id:   string;
  name: string;
  src:  string;   // SVG string or data URL
  tags: string[];
}

export interface BrandSpacing {
  id:   string;
  name: string;
  px:   number;
}

export interface BrandTypographyPreset {
  id:           string;
  name:         string;
  fontFamily:   string;
  fontSize:     number;
  fontWeight:   number | "bold" | "normal";
  lineHeight?:  number;
  letterSpacing?: number;
  color?:       string;
  usage:        "heading" | "subheading" | "body" | "caption" | "label" | "display";
}

// ── Full Brand Kit ─────────────────────────────────────────────────────────────

export interface FullBrandKit {
  id:          string;
  name:        string;
  description?: string;
  colors:      BrandColor[];
  gradients:   BrandGradient[];
  fonts:       BrandFont[];
  logos:       BrandLogo[];
  icons:       BrandIcon[];
  spacing:     BrandSpacing[];
  typography:  BrandTypographyPreset[];
  createdAt:   string;
  updatedAt:   string;
}

// ── Defaults ──────────────────────────────────────────────────────────────────

function now() { return new Date().toISOString(); }

export function makeDefaultBrandKit(): FullBrandKit {
  return {
    id:          uid(),
    name:        "Default Brand",
    description: "Axon Studio default brand kit",
    colors: [
      { id: uid(), name: "Primary",   value: "#D4AF37" },
      { id: uid(), name: "Secondary", value: "#E8C87D" },
      { id: uid(), name: "Accent",    value: "#FFB300" },
      { id: uid(), name: "Dark",      value: "#111111" },
      { id: uid(), name: "Light",     value: "#F2F2F2" },
      { id: uid(), name: "White",     value: "#ffffff" },
    ],
    gradients: [
      { id: uid(), name: "Brand Gradient", type: "linear", angle: 135, css: "linear-gradient(135deg,#D4AF37,#E8C87D)", stops: [{ color: "#D4AF37", position: 0 }, { color: "#E8C87D", position: 1 }] },
    ],
    fonts: [
      { id: uid(), name: "Inter",     family: "Inter, sans-serif",     weights: [300, 400, 500, 600, 700] },
      { id: uid(), name: "Poppins",   family: "Poppins, sans-serif",   weights: [400, 500, 600, 700] },
    ],
    logos:    [],
    icons:    [],
    spacing: [
      { id: uid(), name: "xs",  px: 4  },
      { id: uid(), name: "sm",  px: 8  },
      { id: uid(), name: "md",  px: 16 },
      { id: uid(), name: "lg",  px: 24 },
      { id: uid(), name: "xl",  px: 32 },
    ],
    typography: [
      { id: uid(), name: "Heading XL", fontFamily: "Inter, sans-serif", fontSize: 48, fontWeight: 700, lineHeight: 1.2, usage: "heading" },
      { id: uid(), name: "Heading LG", fontFamily: "Inter, sans-serif", fontSize: 36, fontWeight: 700, lineHeight: 1.25, usage: "heading" },
      { id: uid(), name: "Body",       fontFamily: "Inter, sans-serif", fontSize: 16, fontWeight: 400, lineHeight: 1.6, usage: "body" },
      { id: uid(), name: "Caption",    fontFamily: "Inter, sans-serif", fontSize: 12, fontWeight: 400, lineHeight: 1.4, usage: "caption" },
    ],
    createdAt: now(),
    updatedAt: now(),
  };
}
