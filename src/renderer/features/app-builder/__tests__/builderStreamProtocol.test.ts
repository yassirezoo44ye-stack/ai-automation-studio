import { describe, expect, it, vi } from "vitest";

vi.mock("../../../shared/utils/api", () => ({
  apiFetch: vi.fn(),
  parseJSON: vi.fn(),
  APIError: class APIError extends Error {},
  BillingRequiredError: class BillingRequiredError extends Error {},
}));

import { apiFetch } from "../../../shared/utils/api";
import { streamBuild } from "../services/builderService";

function sseResponse(chunks: string[]): Response {
  const encoder = new TextEncoder();
  return new Response(new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  }), { status: 200, headers: { "content-type": "text/event-stream" } });
}

describe("App Builder streaming protocol", () => {
  it("parses CRLF frames even when the delimiter spans chunks", async () => {
    vi.mocked(apiFetch).mockResolvedValueOnce(sseResponse([
      'data: {"type":"status","message":"building"}\\r',
      '\\n\\r',
      '\\ndata: {"type":"done","description":"ok","files":[],"run_command":"npm run dev","language":"ts"}\\r\\n\\r\\n',
    ].map(s => s.replace(/\\r/g, "\r").replace(/\\n/g, "\n"))));
    const events = [];
    for await (const event of streamBuild("project-1", "build anime app")) events.push(event);
    expect(events.map(e => e.type)).toEqual(["status", "done"]);
  });

  it("combines multiple data lines and skips malformed frames", async () => {
    vi.mocked(apiFetch).mockResolvedValueOnce(sseResponse([
      'data: not-json\n\ndata: {"type":"status",\ndata: "message":"working"}\n\n',
    ]));
    // An unfinished build is raised as an error (the page shows it and keeps the files).
    const events: unknown[] = [];
    await expect((async () => {
      for await (const event of streamBuild("project-1", "build anime app")) events.push(event);
    })()).rejects.toThrow(/interrupted before completion/);
    expect(events).toEqual([{ type: "status", message: "working" }]);
  });
  it("reports an interrupted build instead of silently ending", async () => {
    vi.mocked(apiFetch).mockResolvedValueOnce(sseResponse([
      'data: {"type":"status","message":"building"}\\n\\n'.replace(/\\n/g, "\n"),
    ]));
    const events: { type: string }[] = [];
    await expect((async () => {
      for await (const event of streamBuild("project-1", "build anime app")) events.push(event);
    })()).rejects.toThrow(/interrupted before completion/);
    expect(events.map(event => event.type)).toEqual(["status"]);
  });

  it("does not report interruption after a terminal error", async () => {
    vi.mocked(apiFetch).mockResolvedValueOnce(sseResponse([
      'data: {"type":"error","message":"invalid project"}\\n\\n'.replace(/\\n/g, "\n"),
    ]));
    const events = [];
    for await (const event of streamBuild("project-1", "build anime app")) events.push(event);
    expect(events).toEqual([{ type: "error", message: "invalid project" }]);
  });

});
