/**
 * SSE parser for the /api/ai/stream endpoint.
 * Yields typed StreamChunk objects; hides all transport details from callers.
 */
import type { InferenceRequest } from "./types";
import type { StreamChunk } from "./types";
import { streamRaw } from "./client";

/**
 * Async generator that streams AI chunks from the backend.
 *
 * Usage:
 *   for await (const chunk of streamChunks(req)) {
 *     if (chunk.type === "delta") appendText(chunk.text);
 *   }
 */
export async function* streamChunks(
  req: InferenceRequest,
): AsyncGenerator<StreamChunk> {
  const res = await streamRaw(req);
  const reader = res.body?.getReader();
  if (!reader) throw new Error("Response body is not readable");

  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      // SSE lines are separated by double newline
      const events = buffer.split("\n\n");
      buffer = events.pop() ?? "";   // keep incomplete tail

      for (const event of events) {
        const line = event.trim();
        if (!line.startsWith("data: ")) continue;
        const json = line.slice(6).trim();
        if (!json || json === "[DONE]") continue;

        try {
          const chunk = JSON.parse(json) as StreamChunk;
          yield chunk;
          if (chunk.type === "done" || chunk.type === "error") return;
        } catch {
          // Malformed JSON — skip silently
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}

/**
 * Convenience helper: collect full text from a streaming request.
 * Reports intermediate deltas via onDelta.
 */
export async function streamToText(
  req: InferenceRequest,
  onDelta?: (text: string) => void,
): Promise<string> {
  let result = "";
  for await (const chunk of streamChunks(req)) {
    if (chunk.type === "delta" && chunk.text) {
      result += chunk.text;
      onDelta?.(chunk.text);
    }
    if (chunk.type === "error") throw new Error(chunk.error ?? "Stream error");
  }
  return result;
}
