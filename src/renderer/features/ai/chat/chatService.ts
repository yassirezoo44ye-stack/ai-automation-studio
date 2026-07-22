import { apiFetch, parseJSON, authH, API } from "../../../shared/utils/api";
import type { Conv, Message, Project, Agent, Task } from "../../../shared/types";

export async function fetchProjects(): Promise<Project[]> {
  const r = await apiFetch("/api/projects");
  return parseJSON<Project[]>(r, "/api/projects");
}

export async function fetchAgents(): Promise<Agent[]> {
  const r = await apiFetch("/api/agents");
  return parseJSON<Agent[]>(r, "/api/agents");
}

export async function fetchConversations(projectId: string): Promise<Conv[]> {
  const path = `/api/conversations?project_id=${projectId}`;
  const r = await apiFetch(path);
  return parseJSON<Conv[]>(r, path);
}

export async function fetchMessages(convId: string): Promise<Message[]> {
  const path = `/api/conversations/${convId}/messages`;
  const r = await apiFetch(path);
  const msgs = await parseJSON<{ id: string; role: string; content: string }[]>(r, path);
  return msgs.map(m => ({ id: m.id, role: m.role as "user" | "assistant", content: m.content }));
}

export async function deleteConversation(convId: string): Promise<void> {
  await apiFetch(`/api/conversations/${convId}`, { method: "DELETE" });
}

export async function exportConversation(convId: string): Promise<Blob> {
  const r = await apiFetch(`/api/export/conversations/${convId}`);
  if (!r.ok) throw new Error("Export failed");
  return r.blob();
}

export async function extractTasksFromConversation(convId: string): Promise<{ created: Task[] }> {
  const path = `/api/tasks/from-conversation/${convId}`;
  const r = await apiFetch(path, { method: "POST" });
  return parseJSON<{ created: Task[] }>(r, path);
}

export async function updateTaskStatus(taskId: string, status: Task["status"]): Promise<void> {
  await apiFetch(`/api/tasks/${taskId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  });
}

export async function fetchRecentTasks(limit = 6): Promise<Task[]> {
  const r = await apiFetch(`/api/tasks?sort=created_at`);
  if (!r.ok) return [];
  const d = await parseJSON<{ tasks?: Task[] }>(r, "/api/tasks");
  return (d.tasks ?? []).slice(0, limit);
}

export function buildChatStreamUrl(agentId: string, isCustomAgent: boolean): string {
  return isCustomAgent
    ? `${API}/api/agents/${agentId}/chat/stream`
    : `${API}/api/run/stream`;
}

export function getChatStreamHeaders(): Record<string, string> {
  return authH();
}
