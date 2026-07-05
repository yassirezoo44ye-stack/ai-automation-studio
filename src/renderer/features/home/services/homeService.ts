import { apiFetch, parseJSON } from "../../../shared/utils/api";
import type { Project } from "../../../shared/types";

export interface StatsResponse {
  conversations: number;
  messages: number;
  agent_runs: number;
  projects: number;
  success_rate: number;
  recent_activity: { action: string; details: Record<string, string>; time: string }[];
}

export interface TimeseriesResponse {
  labels: string[];
  messages: number[];
  builds: number[];
}

export async function fetchStats(): Promise<StatsResponse> {
  const r = await apiFetch("/api/stats");
  return parseJSON<StatsResponse>(r, "/api/stats");
}

export async function fetchTimeseries(days = 14): Promise<TimeseriesResponse> {
  const path = `/api/stats/timeseries?days=${days}`;
  const r = await apiFetch(path);
  return parseJSON<TimeseriesResponse>(r, path);
}

export async function fetchProjects(): Promise<Project[]> {
  const r = await apiFetch("/api/projects");
  return parseJSON<Project[]>(r, "/api/projects");
}

export async function createProject(name: string, description: string): Promise<Project> {
  const r = await apiFetch("/api/projects", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, description }),
  });
  return parseJSON<Project>(r, "/api/projects");
}

export async function deleteProject(id: string): Promise<void> {
  const r = await apiFetch(`/api/projects/${id}`, { method: "DELETE" });
  if (!r.ok) throw new Error(`Delete project failed: ${r.status}`);
}

export async function checkHealth(): Promise<boolean> {
  try {
    const r = await apiFetch("/health");
    return r.ok;
  } catch {
    return false;
  }
}
