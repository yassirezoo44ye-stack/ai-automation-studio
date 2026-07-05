import { apiFetch, parseJSON, authH } from "../../../shared/utils/api";
import type { Agent } from "../../../shared/types";

export async function fetchAgents(): Promise<Agent[]> {
  const r = await apiFetch("/api/agents");
  return parseJSON<Agent[]>(r, "/api/agents");
}

export async function createAgent(data: Partial<Agent>): Promise<Agent> {
  const r = await apiFetch("/api/agents", {
    method: "POST",
    headers: authH(),
    body: JSON.stringify(data),
  });
  return parseJSON<Agent>(r, "/api/agents");
}

export async function updateAgent(id: string, data: Partial<Agent>): Promise<Agent> {
  const path = `/api/agents/${id}`;
  const r = await apiFetch(path, {
    method: "PUT",
    headers: authH(),
    body: JSON.stringify(data),
  });
  return parseJSON<Agent>(r, path);
}

export async function deleteAgent(id: string): Promise<void> {
  const r = await apiFetch(`/api/agents/${id}`, { method: "DELETE" });
  if (!r.ok) throw new Error("Delete agent failed");
}
