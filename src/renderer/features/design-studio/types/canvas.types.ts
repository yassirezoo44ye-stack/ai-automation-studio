import type { FabricObject } from "fabric";

// ── Tool identifiers ──────────────────────────────────────────────────────────
export type Tool =
  | "select" | "text" | "rect" | "circle" | "triangle"
  | "polygon" | "star" | "line" | "arrow" | "pen"
  | "image" | "video" | "frame" | "hand" | "crop" | "eyedropper";

// ── Element metadata stored alongside Fabric objects ──────────────────────────
export interface ElementMeta {
  id: string;
  name: string;
  type: "text" | "image" | "shape" | "video" | "audio" | "group" | "frame" | "path";
  locked: boolean;
  visible: boolean;
  groupId?: string;
}

// ── Canvas page ───────────────────────────────────────────────────────────────
export interface CanvasPage {
  id: string;
  name: string;
  width: number;
  height: number;
  backgroundColor: string;
  backgroundImage?: string;
  json: object;          // Fabric.js serialised state
  thumbnail?: string;   // base64 preview
}

// ── Project ───────────────────────────────────────────────────────────────────
export interface DesignProject {
  id: string;
  name: string;
  description: string;
  pages: CanvasPage[];
  currentPageId: string;
  createdAt: string;
  updatedAt: string;
  version: "1";
}

// ── Brand kit ─────────────────────────────────────────────────────────────────
export interface BrandColor { id: string; name: string; value: string }
export interface BrandFont  { id: string; name: string; family: string; weights: number[] }
export interface BrandLogo  { id: string; name: string; src: string }

export interface BrandKit {
  colors: BrandColor[];
  fonts:  BrandFont[];
  logos:  BrandLogo[];
}

// ── Photo-filter values ───────────────────────────────────────────────────────
export interface PhotoFilters {
  brightness:  number;   // -1 … 1
  contrast:    number;   // -1 … 1
  saturation:  number;   // -1 … 1
  hue:         number;   // -1 … 1
  exposure:    number;   // -1 … 1
  blur:        number;   //  0 … 50
  sepia:       number;   //  0 … 1
  pixelate:    number;   //  1 … 20
  noise:       number;   //  0 … 1
  invert:      boolean;
  grayscale:   boolean;
}

export const DEFAULT_FILTERS: PhotoFilters = {
  brightness: 0, contrast: 0, saturation: 0, hue: 0, exposure: 0,
  blur: 0, sepia: 0, pixelate: 1, noise: 0, invert: false, grayscale: false,
};

// ── Animation ─────────────────────────────────────────────────────────────────
export type AnimationType = "fade" | "scale" | "slide" | "rotate" | "bounce" | "none";

export interface ElementAnimation {
  type: AnimationType;
  duration: number;   // ms
  delay: number;      // ms
  easing: string;     // CSS easing
  direction: "in" | "out" | "both";
}

// ── Asset library ─────────────────────────────────────────────────────────────
export type AssetType = "image" | "svg" | "video" | "audio" | "font" | "pdf";

export interface Asset {
  id: string;
  name: string;
  type: AssetType;
  src: string;          // data URL or object URL
  thumbnail?: string;
  tags?: string[];
  isFavorite: boolean;
  size: number;         // bytes
  mimeType?: string;
  uploadedAt: string;
}

// ── Template ──────────────────────────────────────────────────────────────────
export interface Template {
  id: string;
  name: string;
  category: string;
  tags: string[];
  thumbnail: string;
  width: number;
  height: number;
  isPremium: boolean;
  json: object;
}

// ── History entry (for undo / redo) ───────────────────────────────────────────
export interface HistoryEntry {
  json: object;
  description: string;
  ts: number;
}

// ── Guide lines ───────────────────────────────────────────────────────────────
export interface Guide {
  id: string;
  axis: "x" | "y";
  position: number;
}

// ── Viewport ──────────────────────────────────────────────────────────────────
export interface Viewport {
  zoom: number;
  panX: number;
  panY: number;
}

// ── UI panel identifiers ──────────────────────────────────────────────────────
export type PanelId =
  | "layers" | "assets" | "templates" | "brand"
  | "components" | "tokens" | "history" | "ai" | "pages"
  | "none";

// ── Store state ───────────────────────────────────────────────────────────────
export interface DesignState {
  project:          DesignProject;
  tool:             Tool;
  viewport:         Viewport;
  selectedIds:      string[];
  activePanel:      PanelId;
  guides:           Guide[];
  showGrid:         boolean;
  showGuides:       boolean;
  snapEnabled:      boolean;
  rulerVisible:     boolean;
  historyIndex:     number;   // current position in history stack
  historyLength:    number;   // total entries
  brandKit:         BrandKit;
  assets:           Asset[];
  unsaved:          boolean;
}

// ── Store actions ─────────────────────────────────────────────────────────────
export type DesignAction =
  | { type: "SET_TOOL";          tool: Tool }
  | { type: "SET_VIEWPORT";      viewport: Partial<Viewport> }
  | { type: "SET_SELECTED_IDS";  ids: string[] }
  | { type: "SET_PANEL";         panel: PanelId }
  | { type: "SET_PROJECT";       project: DesignProject }
  | { type: "UPDATE_PAGE_JSON";  pageId: string; json: object }
  | { type: "UPDATE_PAGE_THUMB"; pageId: string; thumbnail: string }
  | { type: "ADD_PAGE";          page: CanvasPage }
  | { type: "REMOVE_PAGE";       pageId: string }
  | { type: "SET_PAGE";          pageId: string }
  | { type: "RENAME_PAGE";       pageId: string; name: string }
  | { type: "SET_HISTORY";       index: number; length: number }
  | { type: "ADD_GUIDE";         guide: Guide }
  | { type: "REMOVE_GUIDE";      guideId: string }
  | { type: "TOGGLE_GRID" }
  | { type: "TOGGLE_GUIDES" }
  | { type: "TOGGLE_SNAP" }
  | { type: "TOGGLE_RULER" }
  | { type: "SET_BRAND_KIT";     brandKit: BrandKit }
  | { type: "SET_ASSETS";        assets: Asset[] }
  | { type: "ADD_ASSET";         asset: Asset }
  | { type: "REMOVE_ASSET";      assetId: string }
  | { type: "TOGGLE_ASSET_FAV";  assetId: string }
  | { type: "REORDER_PAGE";     fromIndex: number; toIndex: number }
  | { type: "DUPLICATE_PAGE";   pageId: string }
  | { type: "MARK_SAVED" }
  | { type: "MARK_UNSAVED" };

// ── Fabric object extended with our meta ──────────────────────────────────────
export type FabricObjWithMeta = FabricObject & { _meta?: ElementMeta };
