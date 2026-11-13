import { apiFetch } from "../../../utils/api";

interface CanvasSnapshot {
  project_id: string | null;
  design_id: string | null;
  name: string;
  canvas_json: object;
  thumbnail: string;
  width: number;
  height: number;
}

export interface SavedCanvas {
  id: string;
  canvas_json: object;
  width: number;
  height: number;
}

export async function loadLatestCanvas(projectId: string | null): Promise<SavedCanvas | null> {
  const query = projectId ? `&project_id=${encodeURIComponent(projectId)}` : "";
  const listResponse = await apiFetch(`/api/design/canvases?limit=1${query}`);
  if (!listResponse.ok) throw new Error("Design history could not be loaded");
  const list = await listResponse.json() as { id: string }[];
  if (!list.length) return null;
  const detailResponse = await apiFetch(`/api/design/canvases/${encodeURIComponent(list[0].id)}`);
  if (!detailResponse.ok) throw new Error("Saved design could not be loaded");
  return detailResponse.json() as Promise<SavedCanvas>;
}

export async function saveCanvasSnapshot(snapshot: CanvasSnapshot): Promise<string> {
  const response = await apiFetch("/api/design/canvases", { method: "POST", body: JSON.stringify(snapshot) });
  if (!response.ok) throw new Error("Design save rejected");
  const data = await response.json() as { id?: unknown };
  if (typeof data.id !== "string" || !data.id) throw new Error("Missing saved design identifier");
  return data.id;
}
