import { apiFetch, parseJSON } from "../../../utils/api";

export interface TextToImageParams {
  prompt:    string;
  width?:    number;
  height?:   number;
  style?:    "natural" | "vivid";
  n?:        number;
}

export interface ImageToImageParams {
  imageDataUrl: string;
  prompt:       string;
}

export interface BackgroundRemovalResult {
  resultDataUrl: string;
}

export interface TextToImageResult {
  images: string[]; // data URLs
}

// ── Text → Image ──────────────────────────────────────────────────────────────

export async function textToImage(
  params: TextToImageParams,
): Promise<TextToImageResult> {
  const res = await apiFetch("/api/ai/image/generate", {
    method: "POST",
    body:   JSON.stringify(params),
  });
  return parseJSON<TextToImageResult>(res, "/api/ai/image/generate");
}

// ── Background removal ────────────────────────────────────────────────────────

export async function removeBackground(
  imageDataUrl: string,
): Promise<BackgroundRemovalResult> {
  const res = await apiFetch("/api/ai/image/remove-background", {
    method: "POST",
    body:   JSON.stringify({ image: imageDataUrl }),
  });
  return parseJSON<BackgroundRemovalResult>(res, "/api/ai/image/remove-background");
}

// ── AI Design Assistant — chat-driven canvas edits ────────────────────────────

export interface DesignAssistantMessage {
  role:    "user" | "assistant";
  content: string;
}

export interface DesignAssistantResult {
  message:  string;
  actions?: DesignAction[];
}

export interface DesignAction {
  type:       "add_text" | "set_background" | "add_shape" | "set_color";
  payload:    Record<string, unknown>;
}

export async function askDesignAssistant(
  messages: DesignAssistantMessage[],
  canvasContext: object,
): Promise<DesignAssistantResult> {
  const res = await apiFetch("/api/ai/design/assistant", {
    method: "POST",
    body:   JSON.stringify({ messages, canvas_context: canvasContext }),
  });
  return parseJSON<DesignAssistantResult>(res, "/api/ai/design/assistant");
}
