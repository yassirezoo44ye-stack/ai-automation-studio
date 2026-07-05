/**
 * AgentClient — frontend client for the multi-agent system.
 */
import { apiJSON, apiFetch, parseJSON } from "../../../shared/utils/api";

export interface AgentInfo {
  name:   string;
  status: "ready" | "busy" | "error";
}

export interface AgentRunRequest {
  agent_name: string;
  prompt:     string;
  user_id?:   string;
}

export interface AgentRunResult {
  success:    boolean;
  content:    string;
  tool_calls: unknown[];
  rounds:     number;
  error?:     string;
}

export class AgentClient {
  async list(): Promise<AgentInfo[]> {
    const res = await apiJSON<{ agents: AgentInfo[] }>("/api/ai/agents/builtin");
    return res.agents;
  }

  async run(request: AgentRunRequest): Promise<AgentRunResult> {
    return apiJSON<AgentRunResult>("/api/ai/agents/builtin/run", {
      method: "POST",
      body:   JSON.stringify(request),
    });
  }

  async *stream(
    request: AgentRunRequest,
  ): AsyncGenerator<{ type: string; content?: string }> {
    const res = await apiFetch("/api/ai/agents/builtin/stream", {
      method: "POST",
      body:   JSON.stringify(request),
    });
    if (!res.ok || !res.body) {
      const err = await parseJSON<{ detail?: string }>(res, "/api/ai/agents/builtin/stream").catch(() => ({ detail: "Stream failed" }));
      throw new Error(err.detail ?? "Agent stream failed");
    }
    const reader  = res.body.getReader();
    const decoder = new TextDecoder();
    let   buffer  = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split("\n\n");
      buffer = parts.pop() ?? "";
      for (const part of parts) {
        const dataLine = part.split("\n").find(l => l.startsWith("data:"));
        if (dataLine) {
          try { yield JSON.parse(dataLine.slice(5).trim()); } catch { /* skip */ }
        }
      }
    }
  }
}

export const agentClient = new AgentClient();
