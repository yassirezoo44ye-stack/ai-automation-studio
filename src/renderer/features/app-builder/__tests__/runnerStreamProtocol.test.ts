import { describe, expect, it, vi } from "vitest";

vi.mock("../../../shared/utils/api", () => ({
  apiFetch: vi.fn(),
}));

import { apiFetch } from "../../../shared/utils/api";
import { streamRun } from "../services/runnerService";

describe("App Builder runtime SSE", () => {
  it("preserves server_ready and error events across fragmented CRLF frames", async () => {
    const encoder = new TextEncoder();
    const chunks = [
      'data: {"type":"status","message":"starting"}\r',
      '\n\r',
      '\ndata: {"type":"server_ready","preview_url":"/preview","port":3000,"project_type":"vite","message":"ready","command":"npm run dev"}\r\n\r\n',
    ];
    vi.mocked(apiFetch).mockResolvedValueOnce(new Response(new ReadableStream<Uint8Array>({
      start(controller) {
        for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
        controller.close();
      },
    }), { status: 200 }));
    const events = [];
    for await (const event of streamRun("project-1")) events.push(event);
    expect(events.map(event => event.type)).toEqual(["status", "server_ready"]);
  });
  it("reports an interrupted run when the stream has no terminal event", async () => {
    const encoder = new TextEncoder();
    vi.mocked(apiFetch).mockResolvedValueOnce(new Response(new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode('data: {"type":"status","message":"starting"}\\n\\n'.replace(/\\n/g, "\n")));
        controller.close();
      },
    }), { status: 200 }));
    const events = [];
    for await (const event of streamRun("project-1")) events.push(event);
    expect(events.map(event => event.type)).toEqual(["status", "error"]);
    expect(events[1]).toMatchObject({ type: "error", category: "network", recoverable: true });
  });

  it("does not report an interruption after server_ready", async () => {
    const encoder = new TextEncoder();
    vi.mocked(apiFetch).mockResolvedValueOnce(new Response(new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode('data: {"type":"server_ready","preview_url":"/preview","port":3000,"project_type":"vite","message":"ready","command":"npm run dev"}\\n\\n'.replace(/\\n/g, "\n")));
        controller.close();
      },
    }), { status: 200 }));
    const events = [];
    for await (const event of streamRun("project-1")) events.push(event);
    expect(events.map(event => event.type)).toEqual(["server_ready"]);
  });

});
