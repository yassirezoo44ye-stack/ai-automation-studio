/**
 * Default component definitions shipped with Axon Studio.
 * These are Fabric.js JSON objects for common UI patterns.
 */
import { createComponent } from "./ComponentLibrary";
import type { ComponentDefinition } from "./ComponentLibrary";

// ── Button ────────────────────────────────────────────────────────────────────

const button: ComponentDefinition = createComponent("Primary Button", "button", {
  version: "6.6.0",
  objects: [
    {
      type: "rect",
      left: 0, top: 0, width: 160, height: 48,
      rx: 8, ry: 8,
      fill: "#4f46e5",
      shadow: null,
      _meta: { id: "btn_bg", name: "Button BG", type: "shape", locked: false, visible: true },
    },
    {
      type: "i-text",
      left: 80, top: 24, originX: "center", originY: "center",
      text: "Button",
      fontFamily: "Inter, sans-serif",
      fontSize: 16, fontWeight: "600",
      fill: "#ffffff",
      _meta: { id: "btn_label", name: "Button Label", type: "text", locked: false, visible: true },
    },
  ],
});

// ── Card ──────────────────────────────────────────────────────────────────────

const card: ComponentDefinition = createComponent("Content Card", "card", {
  version: "6.6.0",
  objects: [
    {
      type: "rect",
      left: 0, top: 0, width: 320, height: 200,
      rx: 12, ry: 12,
      fill: "#ffffff",
      stroke: "#e5e7eb", strokeWidth: 1,
      shadow: { color: "rgba(0,0,0,0.08)", blur: 16, offsetX: 0, offsetY: 4 },
      _meta: { id: "card_bg", name: "Card BG", type: "shape", locked: false, visible: true },
    },
    {
      type: "i-text",
      left: 24, top: 24,
      text: "Card Title",
      fontFamily: "Inter, sans-serif",
      fontSize: 20, fontWeight: "700",
      fill: "#111827",
      _meta: { id: "card_title", name: "Card Title", type: "text", locked: false, visible: true },
    },
    {
      type: "i-text",
      left: 24, top: 60,
      text: "Card description goes here.\nAdd your content.",
      fontFamily: "Inter, sans-serif",
      fontSize: 14, fontWeight: "400",
      fill: "#6b7280",
      _meta: { id: "card_body", name: "Card Body", type: "text", locked: false, visible: true },
    },
  ],
});

// ── Heading section ───────────────────────────────────────────────────────────

const heading: ComponentDefinition = createComponent("Section Heading", "header", {
  version: "6.6.0",
  objects: [
    {
      type: "i-text",
      left: 0, top: 0,
      text: "Section Heading",
      fontFamily: "Inter, sans-serif",
      fontSize: 36, fontWeight: "700",
      fill: "#111827",
      _meta: { id: "heading_h1", name: "Heading", type: "text", locked: false, visible: true },
    },
    {
      type: "i-text",
      left: 0, top: 52,
      text: "Add a supporting subtitle that explains the section.",
      fontFamily: "Inter, sans-serif",
      fontSize: 18, fontWeight: "400",
      fill: "#6b7280",
      _meta: { id: "heading_sub", name: "Subtitle", type: "text", locked: false, visible: true },
    },
  ],
});

// ── Social post card ──────────────────────────────────────────────────────────

const socialCard: ComponentDefinition = createComponent("Social Post Card", "social", {
  version: "6.6.0",
  objects: [
    {
      type: "rect",
      left: 0, top: 0, width: 400, height: 400,
      fill: "linear-gradient(135deg, #4f46e5, #06b6d4)",
      rx: 16, ry: 16,
      _meta: { id: "social_bg", name: "Background", type: "shape", locked: false, visible: true },
    },
    {
      type: "i-text",
      left: 32, top: 160, width: 336,
      text: "Your headline\ngoes here.",
      fontFamily: "Inter, sans-serif",
      fontSize: 36, fontWeight: "700",
      fill: "#ffffff",
      textAlign: "center",
      _meta: { id: "social_text", name: "Headline", type: "text", locked: false, visible: true },
    },
  ],
});

// ── All defaults ──────────────────────────────────────────────────────────────

export const DEFAULT_COMPONENTS: ComponentDefinition[] = [
  button,
  card,
  heading,
  socialCard,
];
