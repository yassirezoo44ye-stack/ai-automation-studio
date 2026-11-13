import { beforeEach, afterEach, expect, it, vi } from "vitest";
import type { Canvas } from "fabric";
import { exportCanvas } from "./exportService";

beforeEach(() => {
  vi.useFakeTimers();
  URL.createObjectURL = vi.fn(() => "blob:design-export");
  URL.revokeObjectURL = vi.fn();
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
});
afterEach(() => { vi.runOnlyPendingTimers(); vi.useRealTimers(); vi.restoreAllMocks(); });

it("downloads raster bytes through a retained blob URL and restores editor zoom", () => {
  const original = [0.5, 0, 0, 0.5, 90, 30];
  const canvas = {
    viewportTransform: original,
    setViewportTransform: vi.fn(), requestRenderAll: vi.fn(),
    toDataURL: vi.fn(() => "data:image/png;base64,aGVsbG8="),
  };
  exportCanvas(canvas as unknown as Canvas, { format: "png", multiplier: 3 });
  expect(canvas.setViewportTransform.mock.calls).toEqual([[[1, 0, 0, 1, 0, 0]], [original]]);
  const blob = vi.mocked(URL.createObjectURL).mock.calls[0][0] as Blob;
  expect(blob.type).toBe("image/png");
  expect(blob.size).toBe(5);
  expect(URL.revokeObjectURL).not.toHaveBeenCalled();
  vi.advanceTimersByTime(10_000);
  expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:design-export");
});

it("restores the document view and propagates rasterization failures", () => {
  const original = [0.7, 0, 0, 0.7, 12, 8];
  const canvas = { viewportTransform: original, setViewportTransform: vi.fn(), requestRenderAll: vi.fn(), toDataURL: () => { throw new Error("tainted canvas"); } };
  expect(() => exportCanvas(canvas as unknown as Canvas, { format: "jpg" })).toThrow("tainted canvas");
  expect(canvas.setViewportTransform).toHaveBeenLastCalledWith(original);
  expect(URL.createObjectURL).not.toHaveBeenCalled();
});
