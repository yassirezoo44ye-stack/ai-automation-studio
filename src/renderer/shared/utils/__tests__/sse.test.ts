import { describe, expect, it, vi } from "vitest";
import { readSSE } from "../sse";

function stream(text: string, splitBytes = false) {
  const bytes = new TextEncoder().encode(text);
  return new ReadableStream<Uint8Array>({
    start(controller) {
      if (splitBytes) for (const byte of bytes) controller.enqueue(new Uint8Array([byte]));
      else controller.enqueue(bytes);
      controller.close();
    },
  });
}

describe("stream transport", () => {
  it("preserves Arabic across individual bytes, CRLF boundaries and a final unpadded completion", async () => {
    const body = stream(': heartbeat\r\ndata:{"type":"delta","text":"مرحبا"}\r\n\r\ndata: {"type":"done"}', true);
    const events = [];
    for await (const event of readSSE(body)) events.push(event);
    expect(events).toEqual([{ type: "delta", text: "مرحبا" }, { type: "done" }]);
    expect(body.locked).toBe(false);
  });

  it("ignores comments and malformed frames while accepting multiline JSON data", async () => {
    const events = [];
    for await (const event of readSSE(stream(': ping\n\ndata: invalid\n\ndata: {"type":\ndata: "done"}\n\n'))) events.push(event);
    expect(events).toEqual([{ type: "done" }]);
  });

  it("cancels the connection when a consumer stops at a terminal event", async () => {
    const cancel = vi.fn();
    const body = new ReadableStream<Uint8Array>({
      start(controller) { controller.enqueue(new TextEncoder().encode('data: {"type":"done"}\n\n')); }, cancel,
    });
    for await (const event of readSSE(body)) { expect(event.type).toBe("done"); break; }
    expect(cancel).toHaveBeenCalledOnce();
    expect(body.locked).toBe(false);
  });
});
