import { beforeEach, expect, it, vi } from "vitest";
import { apiFetch } from "../../../utils/api";
import { loadLatestCanvas, saveCanvasSnapshot } from "./canvasPersistence";
vi.mock("../../../utils/api", () => ({ apiFetch: vi.fn() }));
beforeEach(() => { vi.resetAllMocks(); });

it("loads only the active project's design", async () => {
  vi.mocked(apiFetch).mockResolvedValueOnce(new Response(JSON.stringify([{ id: "canvas-1" }])))
    .mockResolvedValueOnce(new Response(JSON.stringify({ id: "canvas-1", canvas_json: {}, width: 1080, height: 1920 })));
  expect(await loadLatestCanvas("project-2")).toMatchObject({ id: "canvas-1", height: 1920 });
  expect(vi.mocked(apiFetch).mock.calls[0][0]).toBe("/api/design/canvases?limit=1&project_id=project-2");
});

it("does not fall back to another project's design when this one is empty", async () => {
  vi.mocked(apiFetch).mockResolvedValue(new Response("[]"));
  expect(await loadLatestCanvas("empty-project")).toBeNull();
  expect(apiFetch).toHaveBeenCalledOnce();
});

it("reports history failure rather than claiming the project has no saved design", async () => {
  vi.mocked(apiFetch).mockResolvedValue(new Response(null, { status: 503 }));
  await expect(loadLatestCanvas("project-2")).rejects.toThrow("could not be loaded");
});

it("retains the active project, actual image size and existing design id on save", async () => {
  vi.mocked(apiFetch).mockResolvedValue(new Response('{"id":"canvas-1"}'));
  const snapshot = { project_id: "project-2", design_id: "canvas-1", name: "تعلم بصري", canvas_json: { objects: [] }, thumbnail: "", width: 1080, height: 1920 };
  expect(await saveCanvasSnapshot(snapshot)).toBe("canvas-1");
  expect(JSON.parse(vi.mocked(apiFetch).mock.calls[0][1]!.body as string)).toEqual(snapshot);
});

it("does not acknowledge an unsuccessful save", async () => {
  vi.mocked(apiFetch).mockResolvedValue(new Response(null, { status: 403 }));
  await expect(saveCanvasSnapshot({ project_id: "project-2", design_id: null, name: "Draft", canvas_json: {}, thumbnail: "", width: 1080, height: 1080 })).rejects.toThrow("save rejected");
});
