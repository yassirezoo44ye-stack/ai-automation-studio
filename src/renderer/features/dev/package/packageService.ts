import { apiFetch, parseJSON } from "../../../shared/utils/api";

export interface RuntimesResponse {
  [key: string]: { available: boolean; path: string | null; version: string | null };
}

export async function fetchRuntimes(): Promise<RuntimesResponse> {
  const r = await apiFetch("/api/package/runtimes");
  return parseJSON<RuntimesResponse>(r, "/api/package/runtimes");
}
