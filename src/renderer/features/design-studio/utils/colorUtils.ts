// Color utilities for the design studio

export interface RGB { r: number; g: number; b: number }
export interface RGBA extends RGB { a: number }
export interface HSL { h: number; s: number; l: number }

// ── Parsing ───────────────────────────────────────────────────────────────────
export function hexToRgb(hex: string): RGB | null {
  const clean = hex.replace("#", "");
  const full  = clean.length === 3
    ? clean.split("").map(c => c + c).join("")
    : clean;
  if (full.length !== 6) return null;
  return {
    r: parseInt(full.slice(0, 2), 16),
    g: parseInt(full.slice(2, 4), 16),
    b: parseInt(full.slice(4, 6), 16),
  };
}

export function rgbToHex({ r, g, b }: RGB): string {
  return "#" + [r, g, b].map(v => Math.round(v).toString(16).padStart(2, "0")).join("");
}

export function rgbToHsl({ r, g, b }: RGB): HSL {
  const rn = r / 255, gn = g / 255, bn = b / 255;
  const max = Math.max(rn, gn, bn), min = Math.min(rn, gn, bn);
  let h = 0, s = 0;
  const l = (max + min) / 2;
  if (max !== min) {
    const d = max - min;
    s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
    switch (max) {
      case rn: h = ((gn - bn) / d + (gn < bn ? 6 : 0)) / 6; break;
      case gn: h = ((bn - rn) / d + 2) / 6; break;
      case bn: h = ((rn - gn) / d + 4) / 6; break;
    }
  }
  return { h: Math.round(h * 360), s: Math.round(s * 100), l: Math.round(l * 100) };
}

export function hslToRgb({ h, s, l }: HSL): RGB {
  const hn = h / 360, sn = s / 100, ln = l / 100;
  const hue2rgb = (p: number, q: number, t: number) => {
    let tt = t;
    if (tt < 0) tt += 1;
    if (tt > 1) tt -= 1;
    if (tt < 1 / 6) return p + (q - p) * 6 * tt;
    if (tt < 1 / 2) return q;
    if (tt < 2 / 3) return p + (q - p) * (2 / 3 - tt) * 6;
    return p;
  };
  if (sn === 0) {
    const v = Math.round(ln * 255);
    return { r: v, g: v, b: v };
  }
  const q = ln < 0.5 ? ln * (1 + sn) : ln + sn - ln * sn;
  const p = 2 * ln - q;
  return {
    r: Math.round(hue2rgb(p, q, hn + 1 / 3) * 255),
    g: Math.round(hue2rgb(p, q, hn)         * 255),
    b: Math.round(hue2rgb(p, q, hn - 1 / 3) * 255),
  };
}

export function parseColor(value: string): RGBA {
  const def: RGBA = { r: 0, g: 0, b: 0, a: 1 };
  if (!value) return def;

  if (value.startsWith("#")) {
    const rgb = hexToRgb(value);
    return rgb ? { ...rgb, a: 1 } : def;
  }

  const match = value.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?\)/);
  if (match) {
    return {
      r: parseInt(match[1]),
      g: parseInt(match[2]),
      b: parseInt(match[3]),
      a: match[4] !== undefined ? parseFloat(match[4]) : 1,
    };
  }
  return def;
}

export function toRgbaString({ r, g, b, a }: RGBA): string {
  return `rgba(${r},${g},${b},${a})`;
}

// ── Contrast ──────────────────────────────────────────────────────────────────
export function relativeLuminance({ r, g, b }: RGB): number {
  const c = [r, g, b].map(v => {
    const n = v / 255;
    return n <= 0.03928 ? n / 12.92 : ((n + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
}

export function contrastRatio(a: RGB, b: RGB): number {
  const la = relativeLuminance(a) + 0.05;
  const lb = relativeLuminance(b) + 0.05;
  return la > lb ? la / lb : lb / la;
}

export function readableOnColor(bg: string): "#000000" | "#ffffff" {
  const rgb = hexToRgb(bg) ?? { r: 255, g: 255, b: 255 };
  return relativeLuminance(rgb) > 0.179 ? "#000000" : "#ffffff";
}

// ── Manipulation ──────────────────────────────────────────────────────────────
export function lighten(hex: string, amount: number): string {
  const rgb = hexToRgb(hex);
  if (!rgb) return hex;
  const hsl = rgbToHsl(rgb);
  return rgbToHex(hslToRgb({ ...hsl, l: Math.min(100, hsl.l + amount) }));
}

export function darken(hex: string, amount: number): string {
  const rgb = hexToRgb(hex);
  if (!rgb) return hex;
  const hsl = rgbToHsl(rgb);
  return rgbToHex(hslToRgb({ ...hsl, l: Math.max(0, hsl.l - amount) }));
}

export function withAlpha(hex: string, alpha: number): string {
  const rgb = hexToRgb(hex);
  if (!rgb) return hex;
  return `rgba(${rgb.r},${rgb.g},${rgb.b},${alpha})`;
}

// ── Palettes ──────────────────────────────────────────────────────────────────
export const PALETTE_BASIC = [
  "#000000","#ffffff","#f87171","#fb923c","#fbbf24","#a3e635",
  "#34d399","#22d3ee","#60a5fa","#a78bfa","#f472b6","#94a3b8",
];

export const PALETTE_PASTEL = [
  "#fecaca","#fed7aa","#fef08a","#d9f99d","#bbf7d0","#a5f3fc",
  "#bfdbfe","#ddd6fe","#fbcfe8","#e2e8f0","#f1f5f9","#ffffff",
];
