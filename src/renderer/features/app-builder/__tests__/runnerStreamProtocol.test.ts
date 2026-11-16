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
});
