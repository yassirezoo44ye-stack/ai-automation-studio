/**
 * AI Design Engine — expanded AI capabilities.
 * All AI calls return structured operations, not direct canvas mutations.
 * The caller is responsible for applying operations via Commands.
 */
import { apiFetch, parseJSON } from "../../../../utils/api";
import { designBus } from "../../core/events/DesignEventBus";

// ── Request / response types ──────────────────────────────────────────────────

export interface TextToImageParams {
  prompt:  string;
  width?:  number;
  height?: number;
  style?:  "natural" | "vivid";
  n?:      number;
}

export interface TextToImageResult { images: string[] }

export interface GenerateLayoutParams {
  description: string;
  width:       number;
  height:      number;
  style?:      "minimal" | "bold" | "elegant" | "playful";
}

export interface GenerateColorPaletteParams {
  prompt:  string;
  count?:  number;
  mode?:   "complementary" | "analogous" | "triadic" | "monochromatic";
}

export interface ColorPaletteResult {
  colors: Array<{ name: string; hex: string; role: string }>;
}

export interface FontPairingParams { style?: string; usage?: string }
export interface FontPairingResult {
  pairs: Array<{
    heading: { family: string; weight: number };
    body:    { family: string; weight: number };
    label:   string;
  }>;
}

export interface BackgroundRemovalResult { resultDataUrl: string }

export interface SmartResizeParams {
  sourceWidth:  number;
  sourceHeight: number;
  targetWidth:  number;
  targetHeight: number;
  canvasJson:   object;
}

export interface SmartResizeResult { canvasJson: object }

export interface MagicFillParams {
  imageDataUrl:  string;
  maskDataUrl:   string;
  prompt:        string;
}

export interface MagicFillResult { resultDataUrl: string }

export interface DesignSuggestion {
  type:    "color" | "layout" | "typography" | "spacing";
  title:   string;
  summary: string;
  action:  DesignOperation;
}

export interface DesignOperation {
  type:    string;
  payload: Record<string, unknown>;
}

export interface DesignAssistantMessage { role: "user" | "assistant"; content: string }
export interface DesignAssistantResult {
  message:  string;
  actions?: DesignOperation[];
}

// ── Engine ────────────────────────────────────────────────────────────────────

export class AIDesignEngine {

  // ── Text → Image ────────────────────────────────────────────────────────────

  async textToImage(params: TextToImageParams): Promise<TextToImageResult> {
    const res = await apiFetch("/api/ai/image/generate", {
      method: "POST", body: JSON.stringify(params),
    });
    return parseJSON<TextToImageResult>(res, "/api/ai/image/generate");
  }

  // ── Background removal ───────────────────────────────────────────────────────

  async removeBackground(imageDataUrl: string): Promise<BackgroundRemovalResult> {
    const res = await apiFetch("/api/ai/image/remove-background", {
      method: "POST", body: JSON.stringify({ image: imageDataUrl }),
    });
    return parseJSON<BackgroundRemovalResult>(res, "/api/ai/image/remove-background");
  }

  // ── Generate color palette ───────────────────────────────────────────────────

  async generateColorPalette(params: GenerateColorPaletteParams): Promise<ColorPaletteResult> {
    const res = await apiFetch("/api/ai/design/palette", {
      method: "POST", body: JSON.stringify(params),
    });
    if (!res.ok) {
      // Fallback: return a static palette
      return {
        colors: [
          { name: "Primary",   hex: "#4f46e5", role: "primary"   },
          { name: "Secondary", hex: "#06b6d4", role: "secondary" },
          { name: "Accent",    hex: "#f59e0b", role: "accent"    },
          { name: "Dark",      hex: "#111827", role: "dark"      },
          { name: "Light",     hex: "#f9fafb", role: "light"     },
        ],
      };
    }
    return parseJSON<ColorPaletteResult>(res, "/api/ai/design/palette");
  }

  // ── Font pairing ─────────────────────────────────────────────────────────────

  async getFontPairings(params: FontPairingParams): Promise<FontPairingResult> {
    const res = await apiFetch("/api/ai/design/fonts", {
      method: "POST", body: JSON.stringify(params),
    });
    if (!res.ok) {
      return {
        pairs: [
          { label: "Modern",   heading: { family: "Inter", weight: 700 },     body: { family: "Inter", weight: 400 } },
          { label: "Classic",  heading: { family: "Playfair Display", weight: 700 }, body: { family: "Lato", weight: 400 } },
          { label: "Friendly", heading: { family: "Poppins", weight: 600 },   body: { family: "Poppins", weight: 400 } },
        ],
      };
    }
    return parseJSON<FontPairingResult>(res, "/api/ai/design/fonts");
  }

  // ── Generate layout ──────────────────────────────────────────────────────────

  async generateLayout(params: GenerateLayoutParams): Promise<DesignOperation[]> {
    const res = await apiFetch("/api/ai/design/layout", {
      method: "POST", body: JSON.stringify(params),
    });
    if (!res.ok) return [];
    const data = await parseJSON<{ operations?: DesignOperation[] }>(res, "/api/ai/design/layout");
    return data.operations ?? [];
  }

  // ── Smart resize ─────────────────────────────────────────────────────────────

  async smartResize(params: SmartResizeParams): Promise<SmartResizeResult> {
    const res = await apiFetch("/api/ai/design/resize", {
      method: "POST", body: JSON.stringify(params),
    });
    if (!res.ok) return { canvasJson: params.canvasJson };
    return parseJSON<SmartResizeResult>(res, "/api/ai/design/resize");
  }

  // ── Magic fill ───────────────────────────────────────────────────────────────

  async magicFill(params: MagicFillParams): Promise<MagicFillResult> {
    const res = await apiFetch("/api/ai/image/inpaint", {
      method: "POST", body: JSON.stringify(params),
    });
    return parseJSON<MagicFillResult>(res, "/api/ai/image/inpaint");
  }

  // ── Design suggestions ───────────────────────────────────────────────────────

  async getSuggestions(canvasJson: object): Promise<DesignSuggestion[]> {
    const res = await apiFetch("/api/ai/design/suggestions", {
      method: "POST", body: JSON.stringify({ canvas: canvasJson }),
    });
    if (!res.ok) return [];
    const data = await parseJSON<{ suggestions?: DesignSuggestion[] }>(res, "/api/ai/design/suggestions");
    return data.suggestions ?? [];
  }

  // ── Design assistant chat ────────────────────────────────────────────────────

  async askAssistant(
    messages: DesignAssistantMessage[],
    canvasContext: object,
  ): Promise<DesignAssistantResult> {
    const res = await apiFetch("/api/ai/design/assistant", {
      method: "POST",
      body: JSON.stringify({ messages, canvas_context: canvasContext }),
    });
    return parseJSON<DesignAssistantResult>(res, "/api/ai/design/assistant");
  }

  // ── Object eraser ────────────────────────────────────────────────────────────

  async eraseObject(
    imageDataUrl: string,
    boundingBox: { x: number; y: number; width: number; height: number },
  ): Promise<{ resultDataUrl: string }> {
    const res = await apiFetch("/api/ai/image/erase", {
      method: "POST",
      body: JSON.stringify({ image: imageDataUrl, bbox: boundingBox }),
    });
    return parseJSON<{ resultDataUrl: string }>(res, "/api/ai/image/erase");
  }

  /** Emit a structured operation to the design bus for callers to handle */
  emitOperation(op: DesignOperation): void {
    designBus.emit("CommandExecuted", { description: `AI: ${op.type}` });
  }
}

export const aiDesignEngine = new AIDesignEngine();
