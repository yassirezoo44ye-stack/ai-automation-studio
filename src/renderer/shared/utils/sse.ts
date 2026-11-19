/** Decode JSON SSE frames across byte/chunk boundaries, including a final frame
 * without a newline. Consumers decide which events count as completion. */
export async function* readSSE<T extends object = Record<string, unknown>>(body: ReadableStream<Uint8Array>): AsyncGenerator<T> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  function parse(frame: string): T | null {
    const data = frame.split("\n").filter(line => line.startsWith("data:"))
      .map(line => line.slice(5).replace(/^ /, "")).join("\n");
    if (!data.trim()) return null;
    try {
      const event = JSON.parse(data);
      return event && typeof event === "object" && typeof event.type === "string" ? event as T : null;
    } catch { return null; }
  }
  try {
    while (true) {
      const { done, value } = await reader.read();
      buffer += done ? decoder.decode() : decoder.decode(value, { stream: true });
      buffer = buffer.replace(/\r\n/g, "\n");
      let boundary: number;
      while ((boundary = buffer.indexOf("\n\n")) >= 0) {
        const event = parse(buffer.slice(0, boundary));
        buffer = buffer.slice(boundary + 2);
        if (event) yield event;
      }
      if (done) {
        const event = parse(buffer);
        if (event) yield event;
        break;
      }
    }
  } finally {
    try { await reader.cancel?.(); } catch { /* already aborted/closed */ }
    reader.releaseLock?.();
  }
}
