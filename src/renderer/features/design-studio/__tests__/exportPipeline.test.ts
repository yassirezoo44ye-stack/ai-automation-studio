/**
 * Export Pipeline tests.
 */
/// <reference types="vitest/globals" />
import { describe, it, expect, beforeEach, vi } from "vitest";
import { ExportPipeline } from "../core/export/ExportPipeline";
import type { Canvas as FabricCanvas } from "fabric";

// ── Minimal canvas mock ───────────────────────────────────────────────────────

function mockCanvas(): FabricCanvas {
  return {
    toDataURL: vi.fn(() => "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwADhQGAWjR9awAAAABJRU5ErkJggg=="),
    toSVG:     vi.fn(() => "<svg><rect/></svg>"),
    toObject:  vi.fn(() => ({ version: "6.6.0", objects: [] })),
    width:  1280,
    height: 720,
  } as unknown as FabricCanvas;
}

describe("ExportPipeline", () => {
  let pipeline: ExportPipeline;

  beforeEach(() => {
    pipeline = new ExportPipeline();

    // Stub browser APIs not available in jsdom
    vi.stubGlobal("URL", {
      createObjectURL: vi.fn(() => "blob:mock"),
      revokeObjectURL: vi.fn(),
    });

    const fakeAnchor = {
      click: vi.fn(), style: {}, href: "", download: "",
      setAttribute: vi.fn(),
    };
    vi.spyOn(document, "createElement").mockReturnValue(fakeAnchor as unknown as HTMLElement);
    vi.spyOn(document.body, "appendChild").mockImplementation(() => fakeAnchor as unknown as Node);
    vi.spyOn(document.body, "removeChild").mockImplementation(() => fakeAnchor as unknown as Node);
  });

  it("lists all built-in formats", () => {
    const formats = pipeline.supportedFormats();
    expect(formats).toContain("png");
    expect(formats).toContain("jpg");
    expect(formats).toContain("svg");
    expect(formats).toContain("json");
    expect(formats).toContain("html");
  });

  it("png export produces an image/png blob", async () => {
    const canvas = mockCanvas();
    const result = await pipeline.run({ format: "png", canvas });
    expect(result.format).toBe("png");
    expect(result.blob.type).toBe("image/png");
    expect(result.bytes).toBeGreaterThan(0);
  });

  it("svg export produces an image/svg+xml blob", async () => {
    const canvas = mockCanvas();
    const result = await pipeline.run({ format: "svg", canvas });
    expect(result.blob.type).toBe("image/svg+xml");
  });

  it("json export produces an application/json blob", async () => {
    const canvas = mockCanvas();
    const result = await pipeline.run({ format: "json", canvas });
    expect(result.blob.type).toBe("application/json");
  });

  it("throws for unsupported format", async () => {
    const canvas = mockCanvas();
    await expect(
      pipeline.run({ format: "psd" as never, canvas })
    ).rejects.toThrow("Unsupported export format");
  });

  it("custom exporter can be registered", async () => {
    pipeline.register({
      format: "custom" as never,
      mimeType: "text/plain",
      extension: "txt",
      export: () => new Blob(["hello"], { type: "text/plain" }),
    });
    const canvas = mockCanvas();
    const result = await pipeline.run({ format: "custom" as never, canvas });
    expect(result.blob.type).toBe("text/plain");
  });
});
