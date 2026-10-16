import { apiJSON } from "../../../shared/utils/api";
import type {
  FactoryProject,
  ListProjectsResponse,
  SubmitIdeaResponse,
} from "../types/saasFactory.types";

const BASE = "/api/saas-factory";

export async function submitIdea(idea: string): Promise<SubmitIdeaResponse> {
  return apiJSON<SubmitIdeaResponse>(`${BASE}/projects`, {
    method: "POST",
    body: JSON.stringify({ idea }),
  });
}

export async function listProjects(): Promise<ListProjectsResponse> {
  return apiJSON<ListProjectsResponse>(`${BASE}/projects`);
}

export async function getProject(id: string): Promise<FactoryProject> {
  return apiJSON<FactoryProject>(`${BASE}/projects/${id}`);
}

export async function resumeProject(id: string): Promise<{ project_id: string; resumed_from: string }> {
  return apiJSON(`${BASE}/projects/${id}/resume`, { method: "POST" });
}

export async function deleteProject(id: string): Promise<void> {
  await apiJSON(`${BASE}/projects/${id}`, { method: "DELETE" });
}
